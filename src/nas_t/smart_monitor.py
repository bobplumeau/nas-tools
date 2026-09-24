# AI-Assisted: Generated with assistance from AI tools.
"""SMART temperature/health polling for a NAS over SSH (using the vendor's
built-in smartmontools install, e.g. /usr/sbin/smartctl on QNAP QTS).

All drives are polled in a single SSH invocation: the remote shell loops over the
drives and emits delimited sections, which are parsed here. Polling drive-by-drive
would cost 1 + 2N round trips per sample (9 for a 4-bay unit).
"""

import re

from dataclasses import dataclass
from typing import Optional

from nas_t.config import DeviceProfile
from nas_t.ssh_client import run_remote_command
from rich import print

_SMARTCTL_BIN = "/usr/sbin/smartctl"
# SATA attribute-table names that carry drive temperature.
_TEMP_ATTR_NAMES = (
    "Temperature_Celsius",
    "Airflow_Temperature_Cel",
    "Temperature_Internal",
)
# In the SATA attribute table, RAW_VALUE is the 10th column:
# ID# NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
_RAW_VALUE_INDEX = 9
# NVMe drives don't use the attribute table; they report "Temperature: 34 Celsius".
_NVME_TEMP_RE = re.compile(r"^Temperature:\s+(\d+)\s+Celsius", re.MULTILINE)
_DRIVE_MARKER = "@@NAS_T_DRIVE@@"
_HEALTH_MARKER = "@@NAS_T_HEALTH@@"

# One shell pass over every drive: attributes then health, each behind a marker line.
_POLL_ALL_COMMAND = (
    f"for d in /dev/sd?; do "
    f'echo "{_DRIVE_MARKER} $d"; {_SMARTCTL_BIN} -A "$d" 2>/dev/null; '
    f'echo "{_HEALTH_MARKER}"; {_SMARTCTL_BIN} -H "$d" 2>/dev/null; '
    f"done"
)


_QNAP_GETSYSINFO_BIN = "getsysinfo"
_QNAP_MARKER = "@@NAS_T_QNAP@@"
_SYS_MARKER = "@@NAS_T_SYS@@"
_HWMON_MARKER = "@@NAS_T_HWMON@@"
# getsysinfo reports temperature as e.g. "40 C/104 F".
_QNAP_TEMP_RE = re.compile(r"(\d+)\s*C")

# Reads the sudo password from stdin (so it never lands in the NAS's process list), then
# walks every bay reported by `getsysinfo hdnum` in a single remote shell pass.
_QNAP_POLL_COMMAND = (
    "read -r NAS_T_PW; "
    f'n=$(echo "$NAS_T_PW" | sudo -S {_QNAP_GETSYSINFO_BIN} hdnum 2>/dev/null | tr -dc "0-9"); '
    '[ -z "$n" ] && exit 1; '
    "i=1; "
    'while [ "$i" -le "$n" ]; do '
    f'  t=$(echo "$NAS_T_PW" | sudo -S {_QNAP_GETSYSINFO_BIN} hdtmp "$i" 2>/dev/null); '
    f'  s=$(echo "$NAS_T_PW" | sudo -S {_QNAP_GETSYSINFO_BIN} hdsmart "$i" 2>/dev/null); '
    f'  echo "{_QNAP_MARKER} $i|$t|$s"; '
    "  i=$((i+1)); "
    "done; "
    # Chassis-level sensors, from the same shell pass so they cost no extra round trip.
    f'echo "{_SYS_MARKER} cpu|$(echo "$NAS_T_PW" | sudo -S {_QNAP_GETSYSINFO_BIN} cputmp 2>/dev/null)"; '
    f'echo "{_SYS_MARKER} system|$(echo "$NAS_T_PW" | sudo -S {_QNAP_GETSYSINFO_BIN} systmp 2>/dev/null)"; '
    # hwmon is world-readable, so no sudo needed. Enumerated rather than hardcoding
    # hwmon1/hwmon2, whose numbering isn't stable across boots.
    "for h in /sys/class/hwmon/hwmon*; do "
    '  nm=$(cat "$h/name" 2>/dev/null); t=$(cat "$h/temp1_input" 2>/dev/null); '
    f'  [ -n "$nm" ] && [ -n "$t" ] && echo "{_HWMON_MARKER} $nm|$t"; '
    "done; "
    "true"
)


@dataclass
class DriveReading:
    drive: str
    temperature_c: Optional[float]
    healthy: Optional[bool]


@dataclass
class SensorReading:
    """A non-drive temperature sensor: CPU, chassis, NIC PHY, etc."""

    name: str
    temperature_c: Optional[float]


def _parse_temperature(attributes_text: str) -> Optional[float]:
    """Extracts drive temperature in Celsius from `smartctl -A` output.

    Handles the SATA attribute table (taking RAW_VALUE, which may carry trailing
    context such as "31 (Min/Max 20/45)") and the flat NVMe format.
    """
    for line in attributes_text.splitlines():
        fields = line.split()
        if len(fields) <= _RAW_VALUE_INDEX or fields[1] not in _TEMP_ATTR_NAMES:
            continue
        try:
            return float(fields[_RAW_VALUE_INDEX])
        except ValueError:
            continue

    match = _NVME_TEMP_RE.search(attributes_text)
    return float(match.group(1)) if match else None


def _parse_health(health_text: str) -> Optional[bool]:
    if "PASSED" in health_text:
        return True
    if "FAILED" in health_text:
        return False
    return None


def parse_poll_output(stdout: str) -> list[DriveReading]:
    """Parses the delimited multi-drive smartctl output into per-drive readings."""
    readings = []
    # Each chunk after the drive marker is "<path>\n<attributes><health marker><health>".
    for chunk in stdout.split(_DRIVE_MARKER)[1:]:
        header, _, body = chunk.partition("\n")
        drive = header.strip()
        if not drive:
            continue
        attributes_text, _, health_text = body.partition(_HEALTH_MARKER)
        readings.append(
            DriveReading(
                drive=drive,
                temperature_c=_parse_temperature(attributes_text),
                healthy=_parse_health(health_text),
            )
        )
    return readings


def poll_all_drives(device: DeviceProfile) -> list[DriveReading]:
    """Reads temperature and health for every drive on the NAS in one SSH round trip.

    Dispatches on the device's vendor: QNAP units that ship no smartctl are read via
    their built-in getsysinfo, everything else via smartctl.
    """
    if device.vendor == "qnap":
        return poll_all_drives_qnap(device)

    result = run_remote_command(device, _POLL_ALL_COMMAND, timeout=60)
    if result.exit_code != 0:
        return []
    return parse_poll_output(result.stdout)


def poll_all(device: DeviceProfile) -> tuple[list[DriveReading], list[SensorReading]]:
    """Reads drives and chassis sensors together.

    On QNAP both come from a single SSH round trip; the smartctl backend has no
    equivalent chassis sensors, so it returns drives only.
    """
    if device.vendor != "qnap":
        return poll_all_drives(device), []

    stdout = _qnap_poll_stdout(device)
    if stdout is None:
        return [], []
    return parse_qnap_poll_output(stdout), parse_sensor_output(stdout)


def _failure_reason(result) -> str:
    """Picks the most useful line of stderr to report as a poll failure reason.

    These NASes emit warnings on every successful connection too (an unreadable home
    directory, host-key notices). Reporting one of those as "the reason" sends you
    chasing the wrong problem, so they're filtered out first.
    """
    noise = ("could not chdir", "permanently added", "known hosts", "pseudo-terminal")
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    meaningful = [line for line in lines if not any(n in line.lower() for n in noise)]
    if meaningful:
        return meaningful[-1]
    return f"exit code {result.exit_code}"


def _qnap_poll_stdout(device: DeviceProfile) -> Optional[str]:
    """Runs the batched QNAP poll, returning raw stdout (None if it couldn't run)."""
    password = device.sudo_password
    if password is None:
        # Returning nothing here would render as an empty table with no hint as to why,
        # so say what is missing.
        env_var = device.sudo_password_env or device.ssh_password_env
        detail = f"set ${env_var}" if env_var else "set ssh_password_env in devices.yaml"
        print(
            f"[red]No sudo password available for '{device.name}': getsysinfo needs sudo. "
            f"Please {detail}.[/red]"
        )
        return None

    result = run_remote_command(device, _QNAP_POLL_COMMAND, timeout=60, stdin_data=f"{password}\n")
    if result.exit_code != 0:
        # Failing silently here shows an empty table with no clue why, so surface the
        # reason. stderr routinely carries benign SSH noise, so report its last line.
        reason = _failure_reason(result)
        print(f"[red]Poll of '{device.name}' failed: {reason}[/red]")
        return None
    return result.stdout


def poll_all_drives_qnap(device: DeviceProfile) -> list[DriveReading]:
    """Reads every bay via QNAP's getsysinfo, in one SSH round trip.

    getsysinfo only reports real values under sudo, and this unit's sudo does not cache
    credentials between calls, so the password is piped to each one. It arrives on the
    remote shell's stdin rather than in the command, keeping it out of the NAS's `ps`.
    """
    password = device.sudo_password
    if password is None:
        # Returning an empty list here would render as an empty table with no hint as to
        # why, so say what is missing.
        env_var = device.sudo_password_env or device.ssh_password_env
        detail = f"set ${env_var}" if env_var else "set ssh_password_env in devices.yaml"
        print(
            f"[red]No sudo password available for '{device.name}': getsysinfo needs sudo. "
            f"Please {detail}.[/red]"
        )
        return []

    result = run_remote_command(device, _QNAP_POLL_COMMAND, timeout=60, stdin_data=f"{password}\n")
    if result.exit_code != 0:
        return []
    return parse_qnap_poll_output(result.stdout)


def parse_qnap_poll_output(stdout: str) -> list[DriveReading]:
    """Parses the delimited getsysinfo output into per-bay readings."""
    readings = []
    for line in stdout.splitlines():
        if not line.startswith(_QNAP_MARKER):
            continue
        payload = line[len(_QNAP_MARKER) :].strip()
        fields = payload.split("|")
        if len(fields) < 3:
            continue
        bay, temperature_text, health_text = fields[0], fields[1], fields[2]
        readings.append(
            DriveReading(
                drive=f"disk{bay.strip()}",
                temperature_c=_parse_qnap_temperature(temperature_text),
                healthy=_parse_qnap_health(health_text),
            )
        )
    return readings


def parse_sensor_output(stdout: str) -> list[SensorReading]:
    """Parses the chassis/CPU/NIC sensor lines emitted alongside the drive readings."""
    readings = []
    for line in stdout.splitlines():
        if line.startswith(_SYS_MARKER):
            name, _, value = line[len(_SYS_MARKER) :].strip().partition("|")
            temperature = _parse_qnap_temperature(value)
        elif line.startswith(_HWMON_MARKER):
            name, _, value = line[len(_HWMON_MARKER) :].strip().partition("|")
            # hwmon reports millidegrees.
            try:
                temperature = int(value.strip()) / 1000.0
            except ValueError:
                temperature = None
        else:
            continue

        name = name.strip()
        if name:
            readings.append(SensorReading(name=name, temperature_c=temperature))
    return readings


def _parse_qnap_temperature(text: str) -> Optional[float]:
    """Parses getsysinfo's "40 C/104 F" temperature format."""
    match = _QNAP_TEMP_RE.search(text)
    return float(match.group(1)) if match else None


def _parse_qnap_health(text: str) -> Optional[bool]:
    """Maps a getsysinfo SMART summary to a health flag ("--" means not reported)."""
    value = text.strip().upper()
    if not value or value == "--":
        return None
    return value == "GOOD"


def list_drives(device: DeviceProfile) -> list[str]:
    """Lists candidate drive device paths on the NAS (e.g. /dev/sda, /dev/sdb, ...)."""
    result = run_remote_command(device, "ls -d /dev/sd? 2>/dev/null")
    if result.exit_code != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def read_drive_smart(device: DeviceProfile, drive_path: str) -> DriveReading:
    """Reads temperature and health for a single drive."""
    temp_result = run_remote_command(device, f"{_SMARTCTL_BIN} -A {drive_path}")
    health_result = run_remote_command(device, f"{_SMARTCTL_BIN} -H {drive_path}")
    return DriveReading(
        drive=drive_path,
        temperature_c=_parse_temperature(temp_result.stdout),
        healthy=_parse_health(health_result.stdout),
    )
