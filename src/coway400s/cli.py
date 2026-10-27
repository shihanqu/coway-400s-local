"""Configuration wizard, optional pairing, service and small HTTP client."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .config import Config, environment, ipv4
from .protocol import serial_number


def configure():
    target = Path(".env")
    if target.exists():
        raise ValueError(".env already exists and was preserved. Edit it to change configuration.")
    serial = serial_number(input("18-character serial from the purifier label: "))
    suggestion = ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            # UDP connect chooses a local route; it sends no datagram.
            route.connect(("192.0.2.1", 9))
            suggestion = route.getsockname()[0]
    except OSError:
        pass
    print("Use the stable LAN IP of the server computer, not a Docker/container IP.")
    host = ipv4(input(f"Controller LAN IP [{suggestion}]: ").strip() or suggestion)
    with target.open("x") as out:
        out.write(f"COWAY_SERIAL={serial}\nCOWAY_HOST_IP={host}\nCOWAY_DEVICE_IP=\n")
    print("Saved .env. Start with: docker compose up -d --build")
    print("Then follow docs/network.md for the per-purifier DNS redirect.")
    print("If the purifier is not on Wi-Fi yet: python3 tools/pair.py")


def request(action, value=None, url=None):
    env = environment()
    data_dir = Path(env.get("COWAY_DATA_DIR", ".coway"))
    secret = env.get("COWAY_API_TOKEN")
    if not secret:
        path = data_dir / "api-token"
        if not path.exists():
            raise ValueError("Start the server first, or set COWAY_API_TOKEN for a remote server.")
        secret = path.read_text().strip()
    base = (url or env.get("COWAY_URL", f"http://127.0.0.1:{env.get('COWAY_API_PORT', '8080')}" )).rstrip("/")
    path = "/api/state" if action == "status" else f"/api/{action}"
    body = None if action == "status" else json.dumps({"value": value}).encode()
    message = Request(base + path, data=body,
                      headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"})
    try:
        # The target is an explicitly selected local controller. Do not send
        # its bearer token through ambient system/corporate HTTP proxies.
        with build_opener(ProxyHandler({})).open(message, timeout=16) as reply:
            result = json.load(reply)
    except HTTPError as error:
        try:
            with error:
                result = json.load(error)
        except ValueError:
            result = {"ok": False, "error": f"HTTP {error.code}"}
    except (OSError, URLError) as error:
        raise ValueError("Cannot reach the controller. Is the service running?") from error
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Coway Airmega 400S control")
    parser.add_argument("--url", help="Controller URL; default http://127.0.0.1:8080")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Write local configuration interactively")
    commands.add_parser("serve", help="Run the local controller (no Coway connection)")
    commands.add_parser("status", help="Read fresh device state")
    commands.add_parser("token", help="Print this installation's private API token")
    speed = commands.add_parser("speed", help="Set a factory fan speed")
    speed.add_argument("value", type=int, choices=(1, 2, 3))
    light = commands.add_parser("light")
    light.add_argument("value", choices=("on", "off"))
    sensitivity = commands.add_parser("sensitivity")
    sensitivity.add_argument("value", choices=("sensitive", "moderate", "insensitive"))
    wifi = commands.add_parser("wifi", help="Set up the purifier Wi-Fi without the app")
    wifi.add_argument("--serial")
    wifi.add_argument("--host", default="192.168.12.101")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "init":
            configure()
        elif args.command == "wifi":
            from .provision import interactive
            interactive(args.serial or environment().get("COWAY_SERIAL"), args.host)
        elif args.command == "serve":
            from .server import serve
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
            asyncio.run(serve(Config.load()))
        elif args.command == "token":
            path = Path(environment().get("COWAY_DATA_DIR", ".coway")) / "api-token"
            print(path.read_text().strip())
        else:
            return request(args.command, getattr(args, "value", None), args.url)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
