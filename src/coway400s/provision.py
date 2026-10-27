"""The four observed Airmega Wi-Fi setup commands; standard library only."""

import getpass
import socket
import sys

from .protocol import serial_number


def packet(command: int, text: str | None) -> bytes:
    body = b"\0\0" if text is None else text.encode("utf-8")
    if not 0 <= command <= 255 or len(body) + 5 > 255:
        raise ValueError("Provisioning field exceeds its wire length.")
    prefix = b"\x02" + f"{len(body) + 5:02X}{command:02X}".encode("ascii") + body
    return prefix + f"{sum(prefix) & 255:02X}".encode("ascii") + b"\x03"


def read_exact(connection, count):
    data = bytearray()
    while len(data) < count:
        chunk = connection.recv(count - len(data))
        if not chunk:
            raise ConnectionError("Purifier closed the setup connection.")
        data.extend(chunk)
    return bytes(data)


def acknowledgment(connection):
    prefix = read_exact(connection, 3)
    if prefix[:1] != b"\x02":
        raise ValueError("Invalid setup acknowledgement.")
    size = int(prefix[1:3], 16)
    if not 5 <= size <= 255:
        raise ValueError("Invalid setup acknowledgement length.")
    frame = prefix + read_exact(connection, size)
    if (frame[-1:] != b"\x03" or int(frame[-3:-1], 16) != sum(frame[:-3]) & 255
            or frame[3:5] != b"FE"):
        raise ValueError("Setup command was not acknowledged; stopped.")


def provision(serial: str, ssid: str, password: str, host: str = "192.168.12.101",
              port: int = 5000, timeout: float = 8) -> str:
    serial = serial_number(serial)
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("Wi-Fi name must contain 1–32 UTF-8 bytes.")
    if not 8 <= len(password.encode("utf-8")) <= 63:
        raise ValueError("Use an 8–63 byte WPA/WPA2 Wi-Fi password.")
    frames = (packet(1, ssid), packet(2, password), packet(3, serial), packet(4, None))
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        for command, frame in enumerate(frames, 1):
            connection.sendall(frame)
            try:
                acknowledgment(connection)
            except (TimeoutError, ConnectionError):
                if command == 4:
                    return "Settings sent. The final reply may disappear as Wi-Fi switches; verify the purifier joins your router before retrying."
                raise
    return "All four setup commands acknowledged. Check your router for the purifier."


def interactive(serial: str | None = None, host: str = "192.168.12.101"):
    if not sys.stdin.isatty():
        raise ValueError("Wi-Fi setup needs an interactive terminal for private password entry.")
    print("Turn on the 400S. Hold Wi-Fi + Light for more than three seconds.")
    print("Connect THIS computer's Wi-Fi to Airmega_400s. No Coway app is needed.")
    input("Press Enter when connected: ")
    serial = serial_number(serial or input("18-character label serial: "))
    ssid = input("Home Wi-Fi name (2.4 GHz): ")
    password = getpass.getpass("Home Wi-Fi password (not saved): ")
    try:
        print(provision(serial, ssid, password, host))
    finally:
        password = None
