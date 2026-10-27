import socket
import threading
import unittest

from coway400s.provision import packet, provision, read_exact
from test_protocol import SERIAL

ACK = b"\x0205FEF2\x03"


class ProvisionTests(unittest.TestCase):
    def exchange(self, close_at=None):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        seen, errors = [], []

        def device():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(2)
                    for expected in range(1, 5):
                        prefix = read_exact(connection, 3)
                        data = prefix + read_exact(connection, int(prefix[1:3], 16))
                        seen.append(data)
                        if expected == close_at:
                            return
                        connection.sendall(ACK)
            except Exception as error:
                errors.append(error)
            finally:
                listener.close()

        worker = threading.Thread(target=device, daemon=True)
        worker.start()
        try:
            result = provision(SERIAL, "Example_2G", "example-passphrase", "127.0.0.1",
                               listener.getsockname()[1], timeout=2)
            return result, seen
        finally:
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])

    def test_exact_four_commands(self):
        result, seen = self.exchange()
        self.assertIn("All four", result)
        self.assertEqual(seen, [packet(1, "Example_2G"), packet(2, "example-passphrase"),
                                packet(3, SERIAL), packet(4, None)])
        self.assertEqual(packet(4, None)[5:-3], b"\0\0")

    def test_final_radio_switch_is_reported_as_unconfirmed(self):
        result, seen = self.exchange(close_at=4)
        self.assertEqual(len(seen), 4)
        self.assertIn("verify", result)

    def test_early_disconnect_stops_setup(self):
        with self.assertRaises(ConnectionError):
            self.exchange(close_at=2)
