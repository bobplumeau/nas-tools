# AI-Assisted: Generated with assistance from AI tools.
"""Unit tests for /proc/net/dev parsing and throughput math, which run without a real NAS."""

import unittest

from unittest import mock

from nas_t import network_monitor
from nas_t.config import DeviceProfile
from nas_t.ssh_client import SshResult

_PROC_NET_DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:  123456     100    0    0    0     0          0         0   123456     100    0    0    0     0       0          0
  eth0: 1000000    5000    0    0    0     0          0         0   400000    2000    0    0    0     0       0          0
  eth1:      50       1    0    0    0     0          0         0       25       1    0    0    0     0       0          0
"""

_DEVICE = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin")


def _ok(stdout: str) -> SshResult:
    return SshResult(exit_code=0, stdout=stdout, stderr="")


class TestInterfaceParsing(unittest.TestCase):
    def test_list_interfaces_excludes_loopback(self):
        with mock.patch.object(
            network_monitor, "run_remote_command", return_value=_ok(_PROC_NET_DEV)
        ):
            self.assertEqual(network_monitor.list_interfaces(_DEVICE), ["eth0", "eth1"])

    def test_read_counters_picks_rx_and_tx_fields(self):
        with mock.patch.object(
            network_monitor, "run_remote_command", return_value=_ok(_PROC_NET_DEV)
        ):
            self.assertEqual(network_monitor.read_counters(_DEVICE, "eth0"), (1000000, 400000))

    def test_read_counters_unknown_interface_returns_none(self):
        with mock.patch.object(
            network_monitor, "run_remote_command", return_value=_ok(_PROC_NET_DEV)
        ):
            self.assertIsNone(network_monitor.read_counters(_DEVICE, "eth9"))

    def test_detect_primary_interface_picks_busiest(self):
        with mock.patch.object(
            network_monitor, "run_remote_command", return_value=_ok(_PROC_NET_DEV)
        ):
            self.assertEqual(network_monitor.detect_primary_interface(_DEVICE), "eth0")


class TestSampler(unittest.TestCase):
    def test_first_sample_is_baseline_then_computes_rate(self):
        # 12,500,000 bytes over 10s = 10 Mb/s.
        samples = [((0, 0), 10000), ((12_500_000, 0), 10000)]
        times = [100.0, 110.0]

        with (
            mock.patch.object(network_monitor, "read_counters_and_speed", side_effect=samples),
            mock.patch.object(network_monitor.time, "monotonic", side_effect=times),
        ):
            sampler = network_monitor.NetworkSampler(_DEVICE, interface="eth0")

            self.assertIsNone(sampler.sample(), "first sample only establishes a baseline")

            sample = sampler.sample()
            self.assertIsNotNone(sample)
            self.assertAlmostEqual(sample.rx_mbps, 10.0)
            self.assertAlmostEqual(sample.tx_mbps, 0.0)
            self.assertEqual(sample.link_speed_mbps, 10000)
            self.assertEqual(sample.interface, "eth0")

    def test_counter_reset_does_not_report_negative_rate(self):
        samples = [((5_000_000, 0), None), ((10, 0), None)]
        times = [100.0, 110.0]

        with (
            mock.patch.object(network_monitor, "read_counters_and_speed", side_effect=samples),
            mock.patch.object(network_monitor.time, "monotonic", side_effect=times),
        ):
            sampler = network_monitor.NetworkSampler(_DEVICE, interface="eth0")
            sampler.sample()
            sample = sampler.sample()

        self.assertEqual(sample.rx_mbps, 0.0)


if __name__ == "__main__":
    unittest.main()
