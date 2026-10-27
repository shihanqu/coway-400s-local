"""Small explicit configuration; Wi-Fi passwords are never configuration."""

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path

from .protocol import serial_number


def environment(path: Path = Path(".env")) -> dict[str, str]:
    values = {}
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not key.startswith("COWAY_"):
                raise ValueError("The .env file must contain COWAY_NAME=value lines.")
            values[key] = value.strip().strip('"').strip("'")
    values.update(os.environ)
    return values


def ipv4(value: str) -> str:
    return str(ipaddress.IPv4Address(value))


@dataclass(frozen=True)
class Config:
    serial: str
    host_ip: str
    device_ip: str | None = None
    data_dir: Path = Path(".coway")
    bind: str = "0.0.0.0"
    tls_port: int = 9090
    dns_port: int = 1053
    api_bind: str = "127.0.0.1"
    api_port: int = 8080

    @classmethod
    def load(cls):
        env = environment()
        if not env.get("COWAY_SERIAL") or not env.get("COWAY_HOST_IP"):
            raise ValueError("Run python3 tools/setup.py, or set COWAY_SERIAL and COWAY_HOST_IP.")
        config = cls(
            serial_number(env["COWAY_SERIAL"]), ipv4(env["COWAY_HOST_IP"]),
            ipv4(env["COWAY_DEVICE_IP"]) if env.get("COWAY_DEVICE_IP") else None,
            Path(env.get("COWAY_DATA_DIR", ".coway")),
            env.get("COWAY_BIND", "0.0.0.0"), int(env.get("COWAY_TLS_PORT", "9090")),
            int(env.get("COWAY_DNS_PORT", "1053")),
            env.get("COWAY_API_BIND", "127.0.0.1"), int(env.get("COWAY_API_PORT", "8080")),
        )
        for port in (config.tls_port, config.dns_port, config.api_port):
            if not 1 <= port <= 65535:
                raise ValueError("Ports must be between 1 and 65535.")
        return config
