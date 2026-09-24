# AI-Assisted: Generated with assistance from AI tools.
"""Generates representative NAS write load by periodically copying a real,
already-captured sample mcap onto the mounted NFS share, mirroring the
production write-then-rename pattern (write to a temp name, then rename), so readers
never see a partially written file.
"""

import shutil
import threading
import time

from pathlib import Path
from typing import Optional


def _writer_loop(
    sample_file: Path,
    dest_dir: Path,
    interval_sec: float,
    duration_sec: Optional[float],
    stop_event: threading.Event,
) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()

    while not stop_event.is_set():
        if duration_sec is not None and (time.monotonic() - start) >= duration_sec:
            break

        timestamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1e6) % 1_000_000:06d}"
        tmp_path = dest_dir / f".tmp_{timestamp}.mcap"
        final_path = dest_dir / f"recording_{timestamp}.mcap"

        shutil.copyfile(sample_file, tmp_path)
        tmp_path.rename(final_path)

        stop_event.wait(interval_sec)


def run_replay_copy_load(
    sample_file: Path,
    mount_root: Path,
    concurrency: int = 3,
    interval_sec: float = 90.0,
    duration_sec: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Runs `concurrency` parallel writer loops (one per simulated VPU), each copying
    `sample_file` into its own subdirectory under `mount_root` on the given interval.

    Blocks until duration_sec elapses, until stop_event is set, or until interrupted (Ctrl+C)
    if neither is provided. Pass an external stop_event when running this from a background
    thread (e.g. driven by a live display in the main thread) so Ctrl+C caught elsewhere can
    still stop this loader cleanly.
    """
    if not sample_file.exists():
        raise FileNotFoundError(f"Sample mcap not found: {sample_file}")

    owns_stop_event = stop_event is None
    if stop_event is None:
        stop_event = threading.Event()
    threads = []
    for vpu_index in range(concurrency):
        dest_dir = mount_root / f"vpu{vpu_index}"
        thread = threading.Thread(
            target=_writer_loop,
            args=(sample_file, dest_dir, interval_sec, duration_sec, stop_event),
            daemon=True,
        )
        threads.append(thread)
        thread.start()

    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        # Only swallow Ctrl+C here when we created the stop_event ourselves (i.e. this is
        # being run standalone via `nas_t load`). When an external stop_event is passed in
        # (e.g. from `nas_t test`'s live view loop), let the caller handle the interrupt and
        # signal the stop itself.
        if owns_stop_event:
            stop_event.set()
            for thread in threads:
                thread.join()
        else:
            raise
