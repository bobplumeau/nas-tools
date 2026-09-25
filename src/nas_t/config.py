# AI-Assisted: Generated with assistance from AI tools.
"""Loads NAS-T device connection profiles from a YAML file."""

import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import yaml


@dataclass
class DeviceProfile:
    name: str
    # Either a single IP, or a list of candidate IPs to probe in order. A list is useful
    # on a bench where the same unit may come up on one of several known addresses.
    nas_ip: Union[str, list[str]]
    ssh_user: str
    jump_host: Optional[str] = None
    ssh_password_env: Optional[str] = None
    # Name of an env var holding the password for sudo on the NAS. QNAP's getsysinfo
    # only reports real values under sudo. Defaults to the SSH password when unset.
    sudo_password_env: Optional[str] = None
    # Selects the SMART collection backend: "qnap" uses the built-in getsysinfo (units
    # that ship no smartctl), anything else uses smartctl.
    vendor: str = "qnap"
    # Interface to sample throughput on (e.g. eth0, bond0). If unset, NAS-T picks the
    # non-loopback interface carrying the most received traffic.
    network_interface: Optional[str] = None
    # MAC address of the NAS NIC, for `nas_t wake` (Wake-on-LAN).
    mac: Optional[str] = None
    # Populated once a candidate IP has been probed successfully, so the rest of the run
    # sticks to the address that actually answered.
    active_ip: Optional[str] = field(default=None, init=False, repr=False, compare=False)

    @property
    def candidate_ips(self) -> list[str]:
        """All addresses to try for this device, in priority order."""
        if isinstance(self.nas_ip, str):
            return [self.nas_ip]
        return list(self.nas_ip)

    @property
    def target_ip(self) -> str:
        """The address to connect to: the probed one if known, else the first candidate."""
        return self.active_ip or self.candidate_ips[0]

    @property
    def ssh_password(self) -> Optional[str]:
        from nas_t import credentials

        return credentials.resolve(self.ssh_password_env)

    @property
    def missing_password_env_vars(self) -> list[str]:
        """Env vars named by this profile that aren't actually set in the environment.

        Lets the CLI warn up front instead of failing later with an auth error or, worse,
        an empty table.
        """
        from nas_t import credentials

        missing = []
        for env_var in (self.ssh_password_env, self.sudo_password_env):
            if env_var and credentials.resolve(env_var) is None:
                missing.append(env_var)
        return missing

    @property
    def sudo_password(self) -> Optional[str]:
        """Password for sudo on the NAS, falling back to the SSH password."""
        from nas_t import credentials

        if self.sudo_password_env is None:
            return self.ssh_password
        return credentials.resolve(self.sudo_password_env)


_DEVICES_FILENAME = "devices.yaml"
_DEVICES_ENV_VAR = "NAS_T_DEVICES_FILE"


def default_devices_file() -> Path:
    """Locates devices.yaml so the CLI works when invoked from any directory.

    Search order: $NAS_T_DEVICES_FILE, ./devices.yaml, ~/.config/nas_t/devices.yaml (next
    to the credential store), then ~/.config/nas-t/devices.yaml (older location).
    Falls back to the current directory so the error message names something sensible.
    """
    from_env = os.environ.get(_DEVICES_ENV_VAR)
    if from_env:
        return Path(from_env)

    candidates = [
        Path.cwd() / _DEVICES_FILENAME,
        Path.home() / ".config" / "nas_t" / _DEVICES_FILENAME,
        Path.home() / ".config" / "nas-t" / _DEVICES_FILENAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_devices(devices_file: Optional[Path] = None) -> dict[str, DeviceProfile]:
    """Parses a devices.yaml file into a dict of DeviceProfile keyed by device name.

    Passing None resolves the file via default_devices_file().
    """
    devices_file = devices_file or default_devices_file()
    if not devices_file.exists():
        raise FileNotFoundError(
            f"Devices file not found: {devices_file}. "
            "Copy devices.example.yaml to devices.yaml and fill in your NAS details."
        )

    with open(devices_file, "r") as f:
        raw = yaml.safe_load(f) or {}

    devices = {}
    for name, fields in (raw.get("devices") or {}).items():
        devices[name] = DeviceProfile(name=name, **fields)
    return devices


def get_device(devices_file: Optional[Path], device_name: str) -> DeviceProfile:
    devices = load_devices(devices_file)
    if device_name not in devices:
        available = ", ".join(devices.keys()) or "(none configured)"
        raise KeyError(f"Unknown device '{device_name}'. Available devices: {available}")
    return devices[device_name]
