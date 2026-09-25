# AI-Assisted: Generated with assistance from AI tools.
"""Jump-host aware SSH command execution for reaching a NAS behind a VPU on a
10GbE subnet that isn't directly routable from a laptop on the 1GbE network.

Connections are multiplexed (OpenSSH ControlMaster): the first command opens a
master connection that later commands reuse, so a monitoring poll costs one TCP
handshake and one authentication instead of one per command.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

from dataclasses import dataclass
from typing import Optional

from nas_t.config import DeviceProfile

# How long the shared master connection lingers after the last command. Comfortably
# longer than a typical poll interval so a whole run reuses one connection.
_CONTROL_PERSIST = "300"


@dataclass
class SshResult:
    exit_code: int
    stdout: str
    stderr: str


def _control_path(device: DeviceProfile, ip: str) -> str:
    """Returns a short, unique path for the multiplexing socket.

    Unix socket paths are limited to ~104 characters, so this hashes the connection
    details rather than interpolating them, which could overflow that limit.
    """
    key = f"{device.ssh_user}@{ip}::{device.jump_host or ''}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return os.path.join(tempfile.gettempdir(), f"nas_t-{uid}-{digest}")


def _askpass_helper() -> str:
    """Path to a tiny .cmd that prints $NAS_T_ASKPASS_VALUE (contains no secret itself)."""
    path = os.path.join(tempfile.gettempdir(), "nas_t-askpass-helper.cmd")
    script = (
        f'@"{sys.executable}" -c "import os,sys; '
        "sys.stdout.write(os.environ.get('NAS_T_ASKPASS_VALUE', '') + chr(10))\"\r\n"
    )
    try:
        with open(path, newline="") as f:
            current = f.read()
    except OSError:
        current = None
    if current != script:
        with open(path, "w", newline="") as f:
            f.write(script)
    return path


def _use_askpass() -> bool:
    return os.name == "nt" and not shutil.which("sshpass")


def _supports_multiplexing() -> bool:
    # ControlMaster needs unix sockets, which Windows OpenSSH doesn't provide.
    return os.name != "nt"


def _ssh_args(device: DeviceProfile, ip: str) -> list[str]:
    args = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=5",
    ]
    if _supports_multiplexing():
        # Without it (Windows), each command pays its own handshake instead.
        args += [
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={_control_path(device, ip)}",
            "-o",
            f"ControlPersist={_CONTROL_PERSIST}",
        ]
    if device.ssh_password is None:
        # Without a configured password, ssh would sit there prompting - once per command,
        # which is especially confusing inside the interactive shell. Fail fast instead so
        # the caller can report that the password env var isn't set.
        args += ["-o", "BatchMode=yes"]
    if device.jump_host:
        args += ["-J", device.jump_host]
    args.append(f"{device.ssh_user}@{ip}")
    return args


def _run(
    device: DeviceProfile,
    ip: str,
    remote_command: str,
    timeout: int,
    stdin_data: Optional[str] = None,
) -> SshResult:
    args = _ssh_args(device, ip) + [remote_command]
    env = None
    password = device.ssh_password
    if password is not None:
        if _use_askpass():
            # Windows OpenSSH has no sshpass: answer the prompt via SSH_ASKPASS instead.
            # The helper prints the password from this process's env, so it's never
            # written to disk or put on a command line. REQUIRE=force makes ssh use it
            # even when a console is attached.
            env = {
                **os.environ,
                "NAS_T_ASKPASS_VALUE": password,
                "SSH_ASKPASS": _askpass_helper(),
                "SSH_ASKPASS_REQUIRE": "force",
                "DISPLAY": ":0",
            }
        else:
            # sshpass -e reads the password from $SSHPASS, keeping it out of argv where
            # any user on the machine could read it via `ps`.
            args = ["sshpass", "-e"] + args
            env = {**os.environ, "SSHPASS": password}
    try:
        # Bytes, not text=True: text mode on Windows rewrites "\n" as "\r\n" in stdin,
        # which breaks shell scripts piped to the NAS (sh sees "\r" in every line).
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            env=env,
            input=stdin_data.encode() if stdin_data is not None else None,
        )
    except subprocess.TimeoutExpired:
        return SshResult(exit_code=124, stdout="", stderr=f"timed out after {timeout}s")
    except FileNotFoundError as exc:
        missing = exc.filename or args[0]
        hint = " (install it with: sudo apt install sshpass)" if missing == "sshpass" else ""
        return SshResult(exit_code=127, stdout="", stderr=f"{missing} not found{hint}")
    return SshResult(exit_code=proc.returncode, stdout=_text(proc.stdout), stderr=_text(proc.stderr))


def _text(data) -> str:
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    return (data or "").replace("\r\n", "\n")


def resolve_target_ip_with_errors(
    device: DeviceProfile, timeout: int = 10
) -> tuple[Optional[str], list[str]]:
    """Probes the device's candidate IPs, returning the first that answers plus, when
    none do, a per-candidate reason so the caller can report something actionable."""
    if device.active_ip is not None:
        return device.active_ip, []

    errors = []
    for ip in device.candidate_ips:
        result = _run(device, ip, "echo ok", timeout)
        if result.exit_code == 0 and "ok" in result.stdout:
            device.active_ip = ip
            return ip, []
        reason = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
        errors.append(f"{ip}: {reason or f'exit code {result.exit_code}'}")
    return None, errors


def resolve_target_ip(device: DeviceProfile, timeout: int = 10) -> Optional[str]:
    """Probes the device's candidate IPs and remembers the first that answers.

    Returns the working address, or None if none of them respond. The result is cached
    on the profile so a run only pays for this probe once.
    """
    return resolve_target_ip_with_errors(device, timeout)[0]


def run_remote_command(
    device: DeviceProfile,
    remote_command: str,
    timeout: int = 15,
    stdin_data: Optional[str] = None,
) -> SshResult:
    """Runs a single command on the NAS over SSH (optionally hopping through a jump host).

    Uses password auth via ``sshpass`` when the device profile has a password configured;
    some NAS vendors (e.g. QNAP, whose default home directory permissions fail SSH's
    StrictModes check) reject publickey auth outright.

    ``stdin_data`` is piped to the remote command's stdin, which is how secrets (e.g. a
    sudo password) are handed over without appearing in the NAS's process list.
    """
    ip, errors = resolve_target_ip_with_errors(device, timeout=timeout)
    if ip is None:
        detail = "; ".join(errors) or ", ".join(device.candidate_ips)
        return SshResult(exit_code=255, stdout="", stderr=f"no candidate IP responded ({detail})")
    return _run(device, ip, remote_command, timeout, stdin_data=stdin_data)


def check_connectivity(device: DeviceProfile) -> bool:
    """Verifies the NAS is reachable over SSH (through the jump host if configured)."""
    return resolve_target_ip(device) is not None


def close_connection(device: DeviceProfile) -> None:
    """Tears down the shared master connection, if one is open."""
    if device.active_ip is None:
        return
    subprocess.run(
        _ssh_args(device, device.active_ip)[:-1]
        + ["-O", "exit", f"{device.ssh_user}@{device.active_ip}"],
        capture_output=True,
        text=True,
    )
