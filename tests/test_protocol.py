import asyncio
import unittest

from coway400s.protocol import Frame, ProtocolError, decode, receive, setting_payload

SERIAL = "TESTSERIAL00000001"
MAC = "020000000001"


def frame(payload):
    return Frame(SERIAL, MAC, b"F" * 16, payload.encode())


class ProtocolTests(unittest.TestCase):
    def test_observed_commands_and_lengths(self):
        samples = ["A1000QMV0.0.0.10", "A1000SG", "A1012QG", "A1011SM",
                   "A1011QG000100030001", "A1011QG000100030002", "A1011QG000100030003",
                   "A1011QG000100070000", "A1011QG000100070002",
                   "A1011QG0001000A0001", "A1011QG0001000A0003", "A1011QG0001000A0002"]
        for payload in samples:
            with self.subTest(payload=payload):
                data = frame(payload).encode()
                self.assertEqual(decode(data), frame(payload))
                self.assertEqual(int(data[51:55], 16), len(payload) + 3)
        self.assertEqual(len(frame(samples[4]).encode()), 77)
        self.assertEqual(setting_payload("speed", 2)[2], "A1011QG000100030002")
        self.assertEqual(setting_payload("light", "on")[2], "A1011QG000100070002")
        self.assertEqual(setting_payload("sensitivity", "insensitive")[2], "A1011QG0001000A0003")

    def test_corrupt_frames_rejected(self):
        good = frame("A1012QG").encode()
        for index in (0, 1, 51, -3, -1):
            bad = bytearray(good)
            bad[index] ^= 1
            with self.subTest(index=index), self.assertRaises(ProtocolError):
                decode(bytes(bad))
        with self.assertRaises(ProtocolError):
            decode(good[:-1])

    def test_map_is_counted_hex_pairs(self):
        self.assertEqual(frame("A1012SM0003000100010003000200070002").attributes(),
                         {"0001": 1, "0003": 2, "0007": 2})
        self.assertIsNone(frame("A1012SM000200030001").attributes())
        with self.assertRaises(ProtocolError):
            frame("A1012SM00020003000100030002").attributes()

    def test_only_captured_settings_are_writable(self):
        for action, value in [("power", 1), ("speed", 0), ("speed", 4), ("speed", True),
                              ("light", 2), ("light", {}), ("sensitivity", [])]:
            with self.subTest(action=action, value=value), self.assertRaises(ValueError):
                setting_payload(action, value)


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_and_coalesced_frames(self):
        reader = asyncio.StreamReader()
        first, second = frame("A1000SG"), frame("A1012QG")
        data = first.encode() + second.encode()
        for index in range(0, len(data), 3):
            reader.feed_data(data[index:index + 3])
        self.assertEqual(await receive(reader), first)
        self.assertEqual(await receive(reader), second)

    async def test_length_bound_precedes_body_allocation(self):
        reader = asyncio.StreamReader()
        prefix = bytearray(frame("A1012QG").encode()[:55])
        prefix[51:55] = b"FFFF"
        reader.feed_data(prefix)
        with self.assertRaises(ProtocolError):
            await receive(reader)
