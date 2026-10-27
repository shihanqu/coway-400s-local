"""Local DNS, legacy TLS endpoint and authenticated HTTP control API."""

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
import json
import logging
import signal
import threading

from dnslib import A, DNSRecord, QTYPE, RCODE, RR

from .config import Config
from .controller import Controller, Unavailable
from .protocol import SETTINGS
from .security import tls_context, token

LOG = logging.getLogger(__name__)


class ControlHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer normally reverse-resolves its bind address. This local
        # endpoint needs no DNS lookup (and must work with DNS offline).
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class LocalDNS(asyncio.DatagramProtocol):
    def __init__(self, config):
        self.config = config

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        try:
            request = DNSRecord.parse(data)
            if request.header.qr or len(request.questions) != 1:
                return
            name = str(request.q.qname).lower().rstrip(".")
            answer = request.reply()
            if name.endswith((".coway.co.kr", ".coway.com")):
                if request.q.qtype == QTYPE.A:
                    answer.add_answer(RR(request.q.qname, QTYPE.A, rdata=A(self.config.host_ip), ttl=5))
            else:
                answer.header.rcode = RCODE.REFUSED
            self.transport.sendto(answer.pack(), address)
        except Exception:
            LOG.debug("Malformed DNS query ignored")


def api_handler(loop, controller, secret):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CowayLocal"

        def log_message(self, *_args):
            pass

        def respond(self, status, data):
            body = (json.dumps(data) + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + secret).encode("utf-8")):
                self.respond(401, {"ok": False, "error": "Bearer token required."})
                return False
            return True

        def run_command(self, setting=None, value=None):
            future = asyncio.run_coroutine_threadsafe(controller.command(setting, value), loop)
            try:
                self.respond(200, future.result(timeout=15))
            except ValueError as error:
                self.respond(400, {"ok": False, "error": str(error)})
            except Unavailable as error:
                self.respond(503, {"ok": False, "error": str(error)})
            except FutureTimeout:
                future.cancel()
                self.respond(504, {"ok": False, "error": "Controller request timed out."})
            except Exception:
                LOG.exception("Controller request failed")
                self.respond(500, {"ok": False, "error": "Controller request failed."})

        def do_GET(self):
            if self.path == "/health":
                self.respond(200, {"ok": True, "connected": controller.device is not None})
            elif not self.authorized():
                return
            elif self.path == "/api/state":
                self.run_command()
            else:
                self.respond(404, {"ok": False, "error": "Unknown endpoint."})

        def do_POST(self):
            if not self.authorized():
                return
            setting = self.path.removeprefix("/api/")
            if self.path != "/api/" + setting or setting not in SETTINGS:
                self.respond(404, {"ok": False, "error": "Unknown endpoint."})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 2048 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Use a JSON body no larger than 2048 bytes.")
                self.connection.settimeout(5)
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or set(body) != {"value"}:
                    raise ValueError('Expected {"value": ...}.')
            except (ValueError, OSError) as error:
                self.respond(400, {"ok": False, "error": str(error)})
                return
            self.run_command(setting, body["value"])
    return Handler


async def stop_tls(server, controller):
    server.close()
    server.abort_clients()
    await controller.close()
    await server.wait_closed()


async def serve(config: Config, stop: asyncio.Event | None = None):
    config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret = token(config.data_dir)
    context = tls_context(config.data_dir)
    controller = Controller(config)
    loop = asyncio.get_running_loop()
    stop = stop or asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    dns = None
    tls = None
    api = None
    thread = None
    try:
        dns, _ = await loop.create_datagram_endpoint(lambda: LocalDNS(config),
                                                    local_addr=(config.bind, config.dns_port))
        tls = await asyncio.start_server(controller.handle, config.bind, config.tls_port,
                                        ssl=context, ssl_handshake_timeout=15, ssl_shutdown_timeout=2)
        api = ControlHTTPServer((config.api_bind, config.api_port), api_handler(loop, controller, secret))
        api.daemon_threads = True
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        LOG.info("Ready: TLS %s:%s, DNS UDP %s:%s, API %s:%s", config.bind, config.tls_port,
                 config.bind, config.dns_port, config.api_bind, config.api_port)
        await stop.wait()
    finally:
        if api:
            await asyncio.to_thread(api.shutdown)
            api.server_close()
        if tls:
            await stop_tls(tls, controller)
        else:
            await controller.close()
        if dns:
            dns.close()
        if thread:
            await asyncio.to_thread(thread.join, 2)
