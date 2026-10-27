import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dnslib import DNSRecord, QTYPE, RCODE

from coway400s.config import Config
from coway400s.protocol import serial_number
from coway400s.security import token
from coway400s.server import LocalDNS
from test_protocol import SERIAL


class SetupTests(unittest.TestCase):
    def test_configuration_is_not_tied_to_investigation_device(self):
        with patch.dict(os.environ, {"COWAY_SERIAL": SERIAL, "COWAY_HOST_IP": "192.168.10.20"}, clear=True):
            config = Config.load()
        self.assertEqual(config.serial, SERIAL)
        self.assertEqual(config.host_ip, "192.168.10.20")
        self.assertIsNone(config.device_ip)
        self.assertEqual(config.api_bind, "127.0.0.1")
        self.assertEqual(serial_number("TEST SERIAL 0O000001"), "TESTSERIAL0O000001")

    def test_tokens_are_private_stable_and_per_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            value = token(first)
            self.assertEqual(token(first), value)
            self.assertNotEqual(token(second), value)
            self.assertEqual((first / "api-token").stat().st_mode & 0o077, 0)

    def test_dns_only_answers_vendor_a_queries(self):
        class Transport:
            def sendto(self, data, address):
                self.data, self.address = data, address
        config = Config(SERIAL, "192.168.10.20", device_ip="192.168.10.50")
        service, transport = LocalDNS(config), Transport()
        service.connection_made(transport)
        # The source can be the hairpin-NAT gateway, not the purifier itself.
        source = ("192.168.10.1", 30016)
        service.datagram_received(DNSRecord.question("iocgwo.coway.co.kr").pack(), source)
        response = DNSRecord.parse(transport.data)
        self.assertEqual(transport.address, source)
        self.assertEqual(str(response.rr[0].rdata), config.host_ip)
        self.assertEqual(response.rr[0].ttl, 5)
        service.datagram_received(DNSRecord.question("example.org").pack(), source)
        self.assertEqual(DNSRecord.parse(transport.data).header.rcode, RCODE.REFUSED)
        service.datagram_received(DNSRecord.question("iocgwo.coway.co.kr", "AAAA").pack(), source)
        self.assertEqual(DNSRecord.parse(transport.data).rr, [])
