"""Observed AP-2015E/WizFi250 wire format; no device-specific identifiers."""

import asyncio
from dataclasses import dataclass
import re

MAX_PAYLOAD = 4096
SETTINGS = {
    "speed": ("0003", {1: 1, 2: 2, 3: 3}),
    "light": ("0007", {"off": 0, "on": 2}),
    "sensitivity": ("000A", {"sensitive": 1, "moderate": 2, "insensitive": 3}),
}


class ProtocolError(ValueError):
    pass


def serial_number(value: str) -> str:
    value = "".join(value.split()).upper()
    if not re.fullmatch(r"[A-Z0-9]{18}", value):
        raise ValueError("Use the 18-character serial printed on the purifier label.")
    return value


@dataclass(frozen=True)
class Frame:
    serial: str
    mac: str
    request_id: bytes
    payload: bytes

    @property
    def code(self) -> str:
        return self.payload[:5].decode("ascii")

    @property
    def flags(self) -> str:
        return self.payload[5:7].decode("ascii")

    def encode(self, payload: str | bytes | None = None) -> bytes:
        body = self.payload if payload is None else payload
        if isinstance(body, str):
            body = body.encode("ascii")
        serial = serial_number(self.serial).encode("ascii")
        if not re.fullmatch(r"[0-9A-Fa-f]{12}", self.mac):
            raise ProtocolError("Invalid MAC field.")
        if len(self.request_id) != 16 or not 7 <= len(body) <= MAX_PAYLOAD:
            raise ProtocolError("Invalid field length.")
        if any(byte < 32 or byte > 126 for byte in self.request_id + body):
            raise ProtocolError("Expected printable ASCII fields.")
        prefix = (b"\x020101" + serial + self.mac.upper().encode("ascii") + self.request_id
                  + f"{len(body) + 3:04X}".encode("ascii") + body)
        return prefix + f"{sum(prefix) & 255:02X}".encode("ascii") + b"\x03"

    def attributes(self) -> dict[str, int] | None:
        body = self.payload[7:]
        if len(body) < 4:
            return None
        try:
            count = int(body[:4], 16)
            if len(body) != 4 + count * 8:
                return None
            result = {}
            for index in range(4, len(body), 8):
                key = f"{int(body[index:index + 4], 16):04X}"
                if key in result:
                    raise ProtocolError("Duplicate attribute.")
                result[key] = int(body[index + 4:index + 8], 16)
            return result
        except ValueError as error:
            if isinstance(error, ProtocolError):
                raise
            return None


def decode(data: bytes) -> Frame:
    if len(data) < 65 or data[:1] != b"\x02" or data[-1:] != b"\x03":
        raise ProtocolError("Invalid frame markers or length.")
    try:
        declared = int(data[51:55], 16)
        checksum = int(data[-3:-1], 16)
        serial = data[5:23].decode("ascii")
        mac = data[23:35].decode("ascii")
        if data[1:5] != b"0101" or not re.fullmatch(r"[0-9A-F]{12}", mac):
            raise ProtocolError("Unsupported header.")
        serial_number(serial)
        if declared != len(data) - 55 or not 10 <= declared <= MAX_PAYLOAD + 3:
            raise ProtocolError("Invalid declared length.")
        if checksum != sum(data[:-3]) & 255:
            raise ProtocolError("Invalid checksum.")
        frame = Frame(serial, mac, data[35:51], data[55:-3])
        if frame.encode() != data:
            raise ProtocolError("Invalid ASCII fields.")
        return frame
    except (ValueError, UnicodeError) as error:
        raise ProtocolError(str(error)) from error


async def receive(reader: asyncio.StreamReader) -> Frame:
    prefix = await reader.readexactly(55)
    if prefix[:1] != b"\x02":
        raise ProtocolError("Invalid frame marker.")
    try:
        size = int(prefix[51:55], 16)
    except ValueError as error:
        raise ProtocolError("Invalid length field.") from error
    if not 10 <= size <= MAX_PAYLOAD + 3:
        raise ProtocolError("Frame exceeds the supported length.")
    return decode(prefix + await reader.readexactly(size))


def setting_payload(setting: str, value) -> tuple[str, int, str]:
    if setting not in SETTINGS:
        raise ValueError("Unknown setting.")
    attribute, values = SETTINGS[setting]
    if isinstance(value, bool):
        raise ValueError("Invalid setting value.")
    if setting == "speed":
        if type(value) is not int or value not in values:
            raise ValueError("Speed must be 1, 2, or 3.")
    elif not isinstance(value, str) or value not in values:
        raise ValueError(f"{setting} must be one of: {', '.join(values)}.")
    number = values[value]
    return attribute, number, f"A1011QG0001{attribute}{number:04X}"
