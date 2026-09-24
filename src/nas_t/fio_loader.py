# AI-Assisted: Generated with assistance from AI tools.
"""Synthetic sustained sequential write load generation using fio, for cases
where you want to push beyond real field write rates (worst-case stress
testing) rather than replay a real captured mcap. See replay_copy_loader.py
for the more field-representative loader.
"""

import shutil
import subprocess
import threading

from pathlib import Path
from typing import Optional


def check_fio_installed() -> bool:
    return shutil.which("fio") is not None


def run_fio_load(
    mount_path: Path,
    block_size: str = "1M",
    write_size: str = "3G",
    runtime_sec: int = 3600,
    concurrency: int = 3,
    rate: Optional[str] = None,
    direct_io: bool = False,
    stop_event: Optional[threading.Event] = None,
    poll_interval_sec: float = 1.0,
) -> int:
    """Runs an fio sequential-write job against the given mounted path.

    - block_size: fio block size, e.g. "1M"
    - write_size: total bytes to write per job before stopping (fio "size"), e.g. "3G"
    - runtime_sec: caps the run in time as well (fio "runtime" + "time_based")
    - concurrency: number of parallel writer jobs (fio "numjobs"), simulating multiple VPUs
    - rate: optional per-job throughput cap, e.g. "35M" (fio "rate"), to avoid saturating
      the link and instead match a realistic sustained bitrate
    - direct_io: enables O_DIRECT (fio "direct=1"); many NFS clients don't support this, so
      it defaults to off
    - stop_event: if given, the fio process is polled and terminated early if the event is
      set (e.g. driven by Ctrl+C caught in `nas_t test`'s live view loop)

    Returns the fio process exit code. Raises FileNotFoundError if fio isn't installed.
    """
    if not check_fio_installed():
        raise FileNotFoundError(
            "fio is not installed or not on PATH. Install it (e.g. `apt install fio`)."
        )

    mount_path.mkdir(parents=True, exist_ok=True)

    args = [
        "fio",
        "--name=nas_t_fio_load",
        f"--directory={mount_path}",
        "--rw=write",
        f"--bs={block_size}",
        f"--size={write_size}",
        f"--runtime={runtime_sec}",
        "--time_based",
        f"--numjobs={concurrency}",
        "--group_reporting",
        f"--direct={1 if direct_io else 0}",
    ]
    if rate:
        args.append(f"--rate={rate}")

    if stop_event is None:
        proc = subprocess.run(args)
        return proc.returncode

    proc = subprocess.Popen(args)
    try:
        while proc.poll() is None:
            if stop_event.wait(poll_interval_sec):
                proc.terminate()
                proc.wait()
                break
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        raise
    return proc.returncode
