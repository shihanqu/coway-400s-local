"""Exercise the actual CLI process, generated secrets, DNS and API startup."""
import asyncio
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
from urllib.request import Request, urlopen
import warnings

from coway400s.protocol import receive
from test_protocol import SERIAL, frame


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_entrypoint_and_shutdown_with_open_device(self):
        with tempfile.TemporaryDirectory() as directory:
            api_port, tls_port, dns_port = free_port(), free_port(), free_port(socket.SOCK_DGRAM)
            env = dict(os.environ, COWAY_SERIAL=SERIAL, COWAY_HOST_IP="127.0.0.1",
                       COWAY_BIND="127.0.0.1", COWAY_API_BIND="127.0.0.1",
                       COWAY_DATA_DIR=directory, COWAY_API_PORT=str(api_port),
                       COWAY_TLS_PORT=str(tls_port), COWAY_DNS_PORT=str(dns_port))
            process = subprocess.Popen([sys.executable, "-m", "coway400s.cli", "serve"], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            writer = None
            try:
                def health():
                    with urlopen(f"http://127.0.0.1:{api_port}/health", timeout=0.3) as result:
                        return json.load(result)
                for _ in range(60):
                    if process.poll() is not None:
                        self.fail(process.stdout.read().decode())
                    try:
                        ready = await asyncio.to_thread(health)
                        break
                    except OSError:
                        await asyncio.sleep(0.1)
                else:
                    self.fail("Service did not start")
                self.assertFalse(ready["connected"])
                secret = (Path(directory) / "api-token").read_text().strip()
                self.assertEqual((Path(directory) / "server.key").stat().st_mode & 0o077, 0)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1
                context.set_ciphers("DEFAULT:@SECLEVEL=0")
                reader, writer = await asyncio.open_connection("127.0.0.1", tls_port, ssl=context,
                                                               server_hostname="localhost")
                writer.write(frame("A1000QMV0.0.0.10").encode())
                await writer.drain()
                self.assertEqual((await receive(reader)).payload, b"A1000SG")

                def state():
                    request = Request(f"http://127.0.0.1:{api_port}/api/state",
                                      headers={"Authorization": "Bearer " + secret})
                    with urlopen(request, timeout=4) as response:
                        return json.load(response)
                query = asyncio.create_task(asyncio.to_thread(state))
                self.assertEqual((await receive(reader)).payload, b"A1012QG")
                writer.write(frame("A1012SM0003000100010003000300070002").encode())
                await writer.drain()
                self.assertEqual((await query)["speed"], 3)
                process.terminate()
                await asyncio.to_thread(process.wait, 5)
                self.assertEqual(process.returncode, 0)
                try:
                    self.assertEqual(await asyncio.wait_for(reader.read(), timeout=2), b"")
                except OSError:
                    pass
            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
                if process.poll() is None:
                    process.kill()
                    await asyncio.to_thread(process.wait, 3)
                process.stdout.close()
