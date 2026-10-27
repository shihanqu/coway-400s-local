import asyncio
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch
import warnings

from coway400s.config import Config
from coway400s.controller import Controller
from coway400s.protocol import Frame, receive
from coway400s.security import tls_context
from coway400s.server import ControlHTTPServer, api_handler, stop_tls
from test_protocol import SERIAL, MAC, frame


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(SERIAL, "127.0.0.1", data_dir=Path(self.temp.name), bind="127.0.0.1")
        self.controller = Controller(self.config)
        self.server = await asyncio.start_server(self.controller.handle, "127.0.0.1", 0,
                                                ssl=tls_context(self.config.data_dir), ssl_shutdown_timeout=1)
        self.writer = None
        self.simulation = None
        self.observed = []
        self.state = {"0001": 1, "0002": 0, "0003": 3, "0007": 2, "000A": 2}

    async def connect(self, serial=SERIAL, mac=MAC):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1
        context.set_ciphers("DEFAULT:@SECLEVEL=0")
        reader, self.writer = await asyncio.open_connection("127.0.0.1", self.server.sockets[0].getsockname()[1],
                                                          ssl=context, server_hostname="localhost")
        self.writer.write(Frame(serial, mac, b"F" * 16, b"A1000QMV0.0.0.10").encode())
        await self.writer.drain()
        return reader

    def state_frame(self, code):
        pairs = "".join(key + f"{value:04X}" for key, value in self.state.items())
        return frame(code + f"{len(self.state):04X}" + pairs).encode()

    async def start_device(self):
        reader = await self.connect()
        self.assertEqual((await receive(reader)).payload, b"A1000SG")

        async def simulate():
            try:
                while True:
                    message = await receive(reader)
                    self.observed.append(message.payload)
                    if message.payload == b"A1012QG":
                        self.writer.write(self.state_frame("A1012SM"))
                    elif message.code == "A1011" and message.flags == "QG":
                        self.state.update(message.attributes())
                        self.writer.write(frame("A1011SM").encode() + self.state_frame("A1010RM"))
                    await self.writer.drain()
            except (asyncio.IncompleteReadError, OSError):
                pass
        self.simulation = asyncio.create_task(simulate())

    async def asyncTearDown(self):
        await asyncio.wait_for(stop_tls(self.server, self.controller), timeout=4)
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except OSError:
                pass
        if self.simulation:
            await self.simulation
        self.temp.cleanup()

    async def test_bootstrap_write_ack_and_fresh_readback(self):
        await self.start_device()
        self.assertEqual((await self.controller.command())["speed"], 3)
        for setting, value, expected in [("speed", 2, 2), ("speed", 1, 1), ("speed", 3, 3),
                                          ("light", "off", "off"), ("light", "on", "on"),
                                          ("sensitivity", "sensitive", "sensitive"),
                                          ("sensitivity", "insensitive", "insensitive"),
                                          ("sensitivity", "moderate", "moderate")]:
            result = await self.controller.command(setting, value)
            self.assertEqual(result[setting], expected)
        self.assertIn(b"A1011QG000100030002", self.observed)
        self.assertEqual(json.loads(self.controller.identity_path.read_text())["mac"], MAC)

    async def test_wrong_serial_rejected_before_ack_or_identity_saved(self):
        reader = await self.connect(serial="B" * 18)
        self.assertEqual(await reader.read(), b"")
        self.assertFalse(self.controller.identity_path.exists())
        self.assertIsNone(self.controller.device)

    async def test_learned_mac_must_match(self):
        self.controller.mac = "020000000099"
        reader = await self.connect()
        self.assertEqual(await reader.read(), b"")
        self.assertIsNone(self.controller.device)

    async def test_shutdown_with_live_connection_does_not_wait_for_peer(self):
        await self.start_device()
        await asyncio.wait_for(stop_tls(self.server, self.controller), timeout=3)
        self.assertFalse(self.controller.tasks)
        self.assertIsNone(self.controller.device)

    async def test_powered_off_rejects_setting_write(self):
        await self.start_device()
        self.state["0001"] = 0
        with self.assertRaises(ValueError):
            await self.controller.command("speed", 2)
        self.assertFalse(any(value.startswith(b"A1011") for value in self.observed))

    async def test_api_auth_validation_and_state(self):
        await self.start_device()
        secret = "test-token-" * 4
        with patch("socket.getfqdn", side_effect=AssertionError("Local API must not reverse-resolve")):
            api = ControlHTTPServer(("127.0.0.1", 0), api_handler(asyncio.get_running_loop(), self.controller, secret))
        worker = threading.Thread(target=api.serve_forever, daemon=True)
        worker.start()

        def call(path, body=None, authorized=True):
            headers = {"Content-Type": "application/json"}
            if authorized:
                headers["Authorization"] = "Bearer " + secret
            data = None if body is None else json.dumps(body).encode()
            request = Request(f"http://127.0.0.1:{api.server_port}" + path, data=data, headers=headers)
            try:
                with build_opener(ProxyHandler({})).open(request, timeout=4) as response:
                    return response.status, json.load(response)
            except HTTPError as error:
                with error:
                    return error.code, json.load(error)
        try:
            self.assertEqual((await asyncio.to_thread(call, "/api/state", None, False))[0], 401)
            self.assertEqual(self.observed, [])
            status, data = await asyncio.to_thread(call, "/api/state")
            self.assertEqual((status, data["speed"]), (200, 3))
            status, data = await asyncio.to_thread(call, "/api/speed", {"value": 2})
            self.assertEqual((status, data["speed"]), (200, 2))
            for value in [True, 0, 4, {}, []]:
                self.assertEqual((await asyncio.to_thread(call, "/api/speed", {"value": value}))[0], 400)
            self.assertEqual((await asyncio.to_thread(call, "/api/light", {"value": {}}))[0], 400)
        finally:
            await asyncio.to_thread(api.shutdown)
            api.server_close()
            worker.join(2)
