# AI-Assisted: Generated with assistance from AI tools.
"""Orchestrates the monitoring loop: polls the SMART and network collectors on an
interval, writes each to its own CSV, and optionally reports each sample to a
callback (used to drive the live dashboard without duplicating SSH polls).
"""

import csv
import threading
import time

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from nas_t.config import DeviceProfile
from nas_t.network_monitor import NetworkSample, NetworkSampler
from nas_t.smart_monitor import DriveReading, SensorReading, poll_all


@dataclass
class MonitorSample:
    timestamp: str
    drive_readings: list[DriveReading]
    network: Optional[NetworkSample]
    sensor_readings: list[SensorReading] = field(default_factory=list)


def monitor_loop(
    device: DeviceProfile,
    smart_csv: Optional[Path] = None,
    network_csv: Optional[Path] = None,
    network_interface: Optional[str] = None,
    interval_sec: int = 30,
    duration_sec: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
    on_sample: Optional[Callable[[MonitorSample], None]] = None,
) -> None:
    """Polls SMART (and network throughput, if network_csv is given) on an interval.

    Runs until duration_sec elapses, until stop_event is set, or indefinitely (until
    interrupted) if neither is provided. Both CSV files are opened for the whole run and
    flushed after every poll, so they always reflect the latest completed reading even on
    an early stop.

    Passing smart_csv=None polls without writing any CSV, which is how the live `monitor`
    view reuses this loop; callers get each sample through on_sample.

    Note that the first network sample of a run is skipped: throughput is derived from
    counter deltas, so it needs two readings before it can report a rate.
    """
    if stop_event is None:
        stop_event = threading.Event()

    smart_header_needed = False
    if smart_csv is not None:
        smart_csv.parent.mkdir(parents=True, exist_ok=True)
        smart_header_needed = not smart_csv.exists()

    sampler = None
    network_header_needed = False
    if network_csv is not None:
        network_csv.parent.mkdir(parents=True, exist_ok=True)
        network_header_needed = not network_csv.exists()
        sampler = NetworkSampler(device, interface=network_interface)

    start = time.monotonic()
    with ExitStack() as stack:
        smart_file = None
        smart_writer = None
        if smart_csv is not None:
            smart_file = stack.enter_context(open(smart_csv, "a", newline=""))
            smart_writer = csv.writer(smart_file)
            if smart_header_needed:
                smart_writer.writerow(["timestamp", "sensor", "temperature_c", "healthy"])
                smart_file.flush()

        network_file = None
        network_writer = None
        if network_csv is not None:
            network_file = stack.enter_context(open(network_csv, "a", newline=""))
            network_writer = csv.writer(network_file)
            if network_header_needed:
                network_writer.writerow(
                    ["timestamp", "interface", "rx_mbps", "tx_mbps", "link_speed_mbps"]
                )
                network_file.flush()

        while not stop_event.is_set():
            if duration_sec is not None and (time.monotonic() - start) >= duration_sec:
                break

            poll_started = time.monotonic()
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

            drive_readings, sensor_readings = poll_all(device)
            if smart_writer is not None:
                for reading in drive_readings:
                    smart_writer.writerow(
                        [timestamp, reading.drive, reading.temperature_c, reading.healthy]
                    )
                for sensor in sensor_readings:
                    # health is drive-only, so it stays blank for chassis sensors.
                    smart_writer.writerow([timestamp, sensor.name, sensor.temperature_c, ""])
                smart_file.flush()

            network_sample = sampler.sample() if sampler is not None else None
            if network_writer is not None and network_sample is not None:
                network_writer.writerow(
                    [
                        timestamp,
                        network_sample.interface,
                        f"{network_sample.rx_mbps:.2f}",
                        f"{network_sample.tx_mbps:.2f}",
                        network_sample.link_speed_mbps,
                    ]
                )
                if network_file is not None:
                    network_file.flush()

            if on_sample is not None:
                on_sample(
                    MonitorSample(
                        timestamp=timestamp,
                        drive_readings=drive_readings,
                        network=network_sample,
                        sensor_readings=sensor_readings,
                    )
                )

            # Subtract the time the poll itself took, so the sampling period is the
            # requested interval rather than interval + poll duration. At the live
            # view's 2s cadence a ~0.5s poll would otherwise be a 25% overshoot, and
            # it keeps logged timestamps evenly spaced.
            stop_event.wait(max(0.0, interval_sec - (time.monotonic() - poll_started)))
