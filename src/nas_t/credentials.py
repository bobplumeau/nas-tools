# AI-Assisted: Generated with assistance from AI tools.
"""Persistent password storage for NAS_T.

Passwords are keyed by the environment variable name a device profile points at
(``ssh_password_env`` / ``sudo_password_env``), so several devices sharing one variable
share one stored secret.

Storage is a JSON file under the user's config directory, created 0600 inside a 0700
directory. This is plaintext on disk: it is obfuscation-free by design, chosen for a lab
bench tool. An environment variable, if set, always wins over the stored value, so CI and
scripted runs are unaffected by whatever a developer saved locally.
"""

import json
import os
import stat

from getpass import getpass
from pathlib import Path
from typing import Optional

from rich import print

CREDENTIALS_PATH = Path.home() / ".config" / "nas_t" / "credentials"

_cache: Optional[dict[str, str]] = None


def _read() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(CREDENTIALS_PATH.read_text())
    except (OSError, ValueError):
        _cache = {}
    return _cache


def _write(data: dict[str, str]) -> None:
    global _cache
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(CREDENTIALS_PATH.parent, stat.S_IRWXU)  # 0700
    # Create with 0600 from the start so the secret is never briefly world-readable.
    fd = os.open(CREDENTIALS_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2)
    _cache = data


def get(env_var: str) -> Optional[str]:
    """Returns the stored password for an env var name, if one was saved."""
    return _read().get(env_var)


def store(env_var: str, password: str) -> None:
    """Saves a password for later sessions and makes it visible to this one."""
    data = dict(_read())
    data[env_var] = password
    _write(data)
    os.environ[env_var] = password


def clear(env_var: Optional[str] = None) -> list[str]:
    """Forgets one stored password, or all of them. Returns what was removed."""
    data = dict(_read())
    removed = [env_var] if env_var and env_var in data else (list(data) if not env_var else [])
    for key in removed:
        data.pop(key, None)
        os.environ.pop(key, None)
    _write(data)
    return removed


def resolve(env_var: Optional[str]) -> Optional[str]:
    """Resolves a password: a live environment variable first, then the saved store."""
    if not env_var:
        return None
    return os.environ.get(env_var) or get(env_var)


def prompt_and_store(env_var: str, device_name: Optional[str] = None) -> Optional[str]:
    """Asks for a password (without echoing) and saves it. None if the user cancels."""
    target = f" for {device_name}" if device_name else ""
    print(f"[bold]Password{target}[/bold] [dim](saved to {CREDENTIALS_PATH}, mode 0600)[/dim]")
    try:
        password = getpass(f"{env_var}: ")
    except (EOFError, KeyboardInterrupt):
        print("\n[yellow]Cancelled.[/yellow]")
        return None
    if not password:
        print("[yellow]No password entered.[/yellow]")
        return None
    store(env_var, password)
    print("[green]Saved.[/green]")
    return password


def ensure_for_device(device, interactive: bool = True) -> bool:
    """Makes sure every password a device profile needs is available, prompting if not.

    Returns True when all required passwords are present.
    """
    env_vars = [v for v in (device.ssh_password_env, device.sudo_password_env) if v]
    for env_var in dict.fromkeys(env_vars):
        if resolve(env_var) is not None:
            continue
        if not interactive:
            return False
        if prompt_and_store(env_var, device.name) is None:
            return False
    return True
