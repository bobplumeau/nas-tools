# AI-Assisted: Generated with assistance from AI tools.
"""Network throughput sampling for a NAS over SSH.

Throughput is derived from deltas in the NAS's own /proc/net/dev byte counters
between polls, so it reflects what the NAS NIC actually moved - writes arriving
from clients show up as RX. Negotiated link speed is also read from
/sys/class/net/<iface>/speed so a link renegotiating downward under heat
(e.g. 10GbE falling back to 1GbE) is visible in the logs.
"""

import time

from dataclasses import dataclass
from typing import Optional

from nas_t.config import DeviceProfile
from nas_t.ssh_client import run_remote_command

_SPEED_MARKER = "@@NAS_T_SPEED@@"


@dataclass
class NetworkSample:
    interface: str
    rx_mbps: float
    tx_mbps: float
    link_speed_mbps: Optional[int]


def _parse_interface_names(proc_net_dev: str) -> list[str]:
    """Extracts non-loopback interface names from /proc/net/dev text."""
    interfaces = []
    for line in proc_net_dev.splitlines():
        if ":" not in line:
            continue
        name = line.split(":", 1)[0].strip()
        if name and name != "lo":
            interfaces.append(name)
    return interfaces


def list_interfaces(device: DeviceProfile) -> list[str]:
    """Lists network interface names on the NAS, excluding loopback."""
    result = run_remote_command(device, "cat /proc/net/dev")
    if result.exit_code != 0:
        return []
    return _parse_interface_names(result.stdout)


def _parse_counters(proc_net_dev: str, interface: str) -> Optional[tuple[int, int]]:
    """Extracts (rx_bytes, tx_bytes) for an interface from /proc/net/dev text."""
    for line in proc_net_dev.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        if name.strip() != interface:
            continue
        fields = rest.split()
        # /proc/net/dev field order: rx_bytes is field 0, tx_bytes is field 8.
        if len(fields) < 9:
            return None
        try:
            return int(fields[0]), int(fields[8])
        except ValueError:
            return None
    return None


def read_counters(device: DeviceProfile, interface: str) -> Optional[tuple[int, int]]:
    """Reads (rx_bytes, tx_bytes) for the given interface from /proc/net/dev."""
    result = run_remote_command(device, "cat /proc/net/dev")
    if result.exit_code != 0:
        return None
    return _parse_counters(result.stdout, interface)


def detect_primary_interface(device: DeviceProfile) -> Optional[str]:
    """Picks the non-loopback interface with the most received bytes, which on a NAS
    under offload load is the one carrying the data traffic.

    A single /proc/net/dev read already contains every interface, so this parses all of
    them from one round trip rather than re-reading it per interface.
    """
    result = run_remote_command(device, "cat /proc/net/dev")
    if result.exit_code != 0:
        return None

    best_interface = None
    best_rx = -1
    for interface in _parse_interface_names(result.stdout):
        counters = _parse_counters(result.stdout, interface)
        if counters is None:
            continue
        rx_bytes = counters[0]
        if rx_bytes > best_rx:
            best_rx = rx_bytes
            best_interface = interface
    return best_interface


def read_link_speed(device: DeviceProfile, interface: str) -> Optional[int]:
    """Reads the negotiated link speed in Mb/s, or None if the NAS doesn't expose it."""
    result = run_remote_command(device, f"cat /sys/class/net/{interface}/speed 2>/dev/null")
    if result.exit_code != 0:
        return None
    return _parse_link_speed(result.stdout)


def _parse_link_speed(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except ValueError:
        return None


def read_counters_and_speed(
    device: DeviceProfile, interface: str
) -> tuple[Optional[tuple[int, int]], Optional[int]]:
    """Reads byte counters and link speed for an interface in a single SSH round trip."""
    result = run_remote_command(
        device,
        f"cat /proc/net/dev; echo '{_SPEED_MARKER}'; cat /sys/class/net/{interface}/speed 2>/dev/null",
    )
    if result.exit_code != 0:
        return None, None

    proc_net_dev, _, speed_text = result.stdout.partition(_SPEED_MARKER)
    return _parse_counters(proc_net_dev, interface), _parse_link_speed(speed_text)


class NetworkSampler:
    """Stateful sampler that converts /proc/net/dev counter deltas into Mb/s.

    The first call to sample() only establishes a baseline and returns None, since
    throughput requires two readings to compute.
    """

    def __init__(self, device: DeviceProfile, interface: Optional[str] = None) -> None:
        self.device = device
        self.interface = interface or detect_primary_interface(device)
        self._prev_counters: Optional[tuple[int, int]] = None
        self._prev_time: Optional[float] = None

    def sample(self) -> Optional[NetworkSample]:
        if self.interface is None:
            return None

        counters, link_speed_mbps = read_counters_and_speed(self.device, self.interface)
        now = time.monotonic()
        if counters is None:
            return None

        prev_counters = self._prev_counters
        prev_time = self._prev_time
        self._prev_counters = counters
        self._prev_time = now

        if prev_counters is None or prev_time is None:
            return None

        elapsed = now - prev_time
        if elapsed <= 0:
            return None

        rx_mbps = (counters[0] - prev_counters[0]) * 8 / 1e6 / elapsed
        tx_mbps = (counters[1] - prev_counters[1]) * 8 / 1e6 / elapsed

        return NetworkSample(
            interface=self.interface,
            rx_mbps=max(rx_mbps, 0.0),
            tx_mbps=max(tx_mbps, 0.0),
            link_speed_mbps=link_speed_mbps,
        )
