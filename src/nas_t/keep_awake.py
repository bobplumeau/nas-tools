"""Keeps this machine from sleeping while a test logs.

On Windows this uses SetThreadExecutionState, which is held by the calling thread only:
it's released on exit even if the process is killed, and it doesn't touch power settings.
The display may still turn off. Elsewhere it's a no-op (use systemd-inhibit or caffeinate
around the command if needed).
"""

import sys

from contextlib import contextmanager

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def _set_state(flags: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    return ctypes.windll.kernel32.SetThreadExecutionState(flags) != 0


@contextmanager
def keep_awake():
    """Blocks system sleep for the duration of the with-block. Yields True if active."""
    active = _set_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    try:
        yield active
    finally:
        if active:
            _set_state(_ES_CONTINUOUS)
