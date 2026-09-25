"""Wake-on-LAN: powers a NAS on over the network (enable WoL in QTS: Control Panel >
Hardware > General). Magic packets are broadcast, so they normally only reach a NAS on
the same local network as this machine."""

import ipaddress
import re
import socket

from typing import Iterable

_MAC_RE = re.compile(r"^[0-9a-f]{2}([:-]?)([0-9a-f]{2}\1){4}[0-9a-f]{2}$", re.IGNORECASE)


def magic_packet(mac: str) -> bytes:
    """6 x 0xFF followed by the MAC repeated 16 times."""
    if not _MAC_RE.match(mac.strip()):
        raise ValueError(f"not a MAC address: {mac!r}")
    raw = bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", mac))
    return b"\xff" * 6 + raw * 16


def broadcast_targets(candidate_ips: Iterable[str], extra: Iterable[str] = ()) -> list[str]:
    """Limited broadcast plus the /24 directed broadcast of each candidate address (the
    usual bench subnet); duplicates removed, order kept."""
    targets = ["255.255.255.255", *extra]
    for ip in candidate_ips:
        try:
            targets.append(str(ipaddress.ip_network(f"{ip}/24", strict=False).broadcast_address))
        except ValueError:
            continue
    return list(dict.fromkeys(targets))


def send_magic_packet(mac: str, targets: Iterable[str], ports: Iterable[int] = (9, 7)) -> int:
    """Sends the packet to every target/port; returns how many sends succeeded."""
    packet = magic_packet(mac)
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in targets:
            for port in ports:
                try:
                    sock.sendto(packet, (target, port))
                    sent += 1
                except OSError:
                    continue
    return sent
