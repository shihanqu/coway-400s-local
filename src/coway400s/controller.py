"""Single-purifier local connection, observed acknowledgements and readback."""

import asyncio
import json
import logging

from .config import Config
from .protocol import Frame, ProtocolError, receive, setting_payload

LOG = logging.getLogger(__name__)


class Unavailable(Exception):
    pass


class Device:
    def __init__(self, writer, identity: Frame):
        self.writer = writer
        self.identity = identity
        self.responses = asyncio.Queue()
        self.ack = asyncio.Event()

    async def send(self, payload):
        self.writer.write(self.identity.encode(payload))
        await self.writer.drain()

    async def state(self):
        self.responses = asyncio.Queue()
        await self.send("A1012QG")
        return await asyncio.wait_for(self.responses.get(), timeout=4)


class Controller:
    def __init__(self, config: Config):
        self.config = config
        self.device = None
        self.lock = asyncio.Lock()
        self.tasks = set()
        self.closing = False
        self.identity_path = config.data_dir / "identity.json"
        self.mac = None
        if self.identity_path.exists():
            saved = json.loads(self.identity_path.read_text())
            if saved.get("serial") != config.serial:
                raise ValueError("The data directory belongs to another purifier; use a separate data directory.")
            self.mac = saved["mac"]

    def validate(self, frame: Frame):
        if frame.serial != self.config.serial or (self.mac and frame.mac != self.mac):
            raise ProtocolError("Purifier identity does not match configuration.")

    def remember(self, frame):
        if self.mac is None:
            self.config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.identity_path.open("x") as out:
                json.dump({"serial": frame.serial, "mac": frame.mac}, out)
            self.mac = frame.mac

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        device = None
        try:
            if self.closing:
                return
            peer = writer.get_extra_info("peername")[0]
            if self.config.device_ip and peer != self.config.device_ip:
                raise ProtocolError("Unexpected source IP.")
            first = await asyncio.wait_for(receive(reader), timeout=15)
            self.validate(first)
            if not first.payload.startswith(b"A1000QMV"):
                raise ProtocolError("Unsupported startup message.")
            self.remember(first)
            device = Device(writer, first)
            if self.device:
                self.device.writer.close()
            self.device = device
            await device.send("A1000SG")
            LOG.info("Purifier connected from %s", peer)
            while True:
                frame = await receive(reader)
                self.validate(frame)
                if frame.code == "A1012" and frame.flags == "SM":
                    attributes = frame.attributes()
                    if attributes is not None:
                        device.responses.put_nowait(attributes)
                if frame.code == "A1011" and frame.flags == "SM":
                    device.ack.set()
                if frame.code in ("A1010", "A1020", "A1051") and frame.flags == "RM":
                    await device.send(frame.code + "SG")
                elif frame.payload.startswith(b"A1000QMV"):
                    await device.send("A1000SG")
        except asyncio.IncompleteReadError:
            LOG.info("Purifier disconnected")
        except (OSError, ValueError, TimeoutError) as error:
            LOG.warning("Purifier connection closed: %s", str(error) or type(error).__name__)
        finally:
            if self.device is device:
                self.device = None
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, TimeoutError):
                pass
            self.tasks.discard(task)

    @staticmethod
    def describe(attributes):
        return {"ok": True, "connected": True, "power": attributes.get("0001"),
                "speed": attributes.get("0003"), "mode": attributes.get("0002"),
                "light": {0: "off", 2: "on"}.get(attributes.get("0007")),
                "sensitivity": {1: "sensitive", 2: "moderate", 3: "insensitive"}.get(attributes.get("000A")),
                "attributes": attributes}

    async def command(self, setting=None, value=None):
        change = setting_payload(setting, value) if setting else None
        async with self.lock:
            device = self.device
            if device is None or device.writer.is_closing():
                raise Unavailable("Waiting for the purifier. Check DNS redirection and restart the purifier.")
            try:
                state = await device.state()
                if change:
                    key, expected, payload = change
                    if state.get("0001") != 1:
                        raise ValueError("Turn the purifier on before changing settings.")
                    device.ack.clear()
                    await device.send(payload)
                    await asyncio.wait_for(device.ack.wait(), timeout=4)
                    state = await device.state()
                    if state.get(key) != expected:
                        raise Unavailable("The purifier did not report the requested setting; no automatic retry was sent.")
                    LOG.info("Verified %s=%s", setting, value)
                return self.describe(state)
            except (OSError, TimeoutError) as error:
                raise Unavailable("The purifier did not respond in time.") from error

    async def close(self):
        self.closing = True
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
