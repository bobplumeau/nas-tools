"""Run folders: each test writes smart_log.csv (long format) plus events.csv, a small
key,value file recording the label and phase times, so plots and comparisons can mark
and align the phases without guessing."""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import csv

SMART_LOG = "smart_log.csv"
EVENTS = "events.csv"


def write_events(run_dir: Path, events: dict[str, object]) -> None:
    with open(run_dir / EVENTS, "w", newline="") as f:
        for key, value in events.items():
            f.write(f"{key},{_fmt(value)}\n")


def append_event(run_dir: Path, key: str, value: object) -> None:
    with open(run_dir / EVENTS, "a", newline="") as f:
        f.write(f"{key},{_fmt(value)}\n")


def read_events(run_dir: Path) -> dict[str, str]:
    """Later entries win, so an appended load_stop (e.g. from soak) overrides the plan."""
    path = run_dir / EVENTS
    if not path.exists():
        return {}
    events = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition(",")
        if sep:
            events[key.strip()] = value.strip()
    return events


def event_time(events: dict[str, str], key: str) -> Optional[datetime]:
    return datetime.fromisoformat(events[key]) if key in events else None


def read_samples(run_dir: Path) -> list[tuple[datetime, dict[str, float]]]:
    """Pivots the long-format log into [(timestamp, {sensor: temperature_c})], sorted."""
    by_time: dict[datetime, dict[str, float]] = defaultdict(dict)
    with open(run_dir / SMART_LOG, newline="") as f:
        for row in csv.DictReader(f):
            value = row.get("temperature_c")
            if value in (None, "", "None"):
                continue
            by_time[datetime.fromisoformat(row["timestamp"])][row["sensor"]] = float(value)
    return sorted(by_time.items())


def series(samples, sensor: str, minus: Optional[str] = None) -> list[tuple[datetime, float]]:
    """One sensor over time, optionally as the difference from another (e.g. coretemp - system)."""
    out = []
    for t, readings in samples:
        if sensor in readings and (minus is None or minus in readings):
            out.append((t, readings[sensor] - (readings[minus] if minus else 0.0)))
    return out


def _fmt(value: object) -> str:
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else str(value)
