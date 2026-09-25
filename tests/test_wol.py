import unittest

from unittest import mock

from nas_t.wol import broadcast_targets, magic_packet, send_magic_packet


class TestWol(unittest.TestCase):
    def test_packet_layout(self):
        packet = magic_packet("00:11:22:33:44:55")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("001122334455"))
        self.assertEqual(packet[-6:], bytes.fromhex("001122334455"))

    def test_accepts_common_formats(self):
        expected = magic_packet("00:11:22:33:44:55")
        for mac in ("00-11-22-33-44-55", "001122334455", "00:11:22:33:44:55\n"):
            self.assertEqual(magic_packet(mac), expected)

    def test_rejects_bad_mac(self):
        for bad in ("00:11:22:33:44", "zz:11:22:33:44:55", "00:11-22:33:44:55"):
            with self.assertRaises(ValueError):
                magic_packet(bad)

    def test_targets_include_subnet_broadcasts(self):
        self.assertEqual(broadcast_targets(["192.0.2.11", "192.0.2.10", "bad"]),
                         ["255.255.255.255", "192.0.2.255"])

    def test_send_counts_successes(self):
        with mock.patch("nas_t.wol.socket.socket") as sock_cls:
            sock = sock_cls.return_value.__enter__.return_value
            sent = send_magic_packet("00:11:22:33:44:55", ["255.255.255.255", "192.0.2.255"])
        self.assertEqual(sent, 4)
        self.assertEqual(sock.sendto.call_count, 4)


if __name__ == "__main__":
    unittest.main()
