"""CPU thermal test: idle baseline, all-core load on the NAS, cooldown, with logging.

Built for comparing CPU thermal-interface builds (e.g. pad thickness): run the same
command per build and compare coretemp minus system with `nas_t compare`.
"""

import threading
import time

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from nas_t import cpu_load
from nas_t.config import DeviceProfile
from nas_t.keep_awake import keep_awake
from nas_t.monitor import MonitorSample, monitor_loop
from nas_t.runs import SMART_LOG, append_event, write_events
from nas_t.soak import SoakDetector


@dataclass
class CpuTestPlan:
    label: str
    idle_sec: int = 300
    load_sec: int = 3600
    cooldown_sec: int = 900
    interval_sec: int = 15
    workers: Optional[int] = None
    stop_at_soak: bool = False
    soak_max_rise: float = 0.5
    soak_window_min: float = 10.0
    soak_min_load_min: float = 20.0
    shutdown_after: bool = False


def run_cpu_test(device: DeviceProfile, run_dir: Path, plan: CpuTestPlan,
                 report: Callable[[str], None] = print) -> bool:
    """Runs the test and returns True if it completed (False if it couldn't start)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    workers = plan.workers or cpu_load.cpu_count(device)

    t0 = datetime.now().replace(microsecond=0)
    load_start = t0 + timedelta(seconds=plan.idle_sec)
    load_stop = load_start + timedelta(seconds=plan.load_sec)
    write_events(run_dir, {
        "label": plan.label,
        "log_start": t0,
        "load_start": load_start,
        "load_stop": load_stop,
        "workers": workers,
    })

    started = cpu_load.start_cpu_load(device, plan.idle_sec, plan.load_sec, workers)
    if not started.ok:
        report(f"[red]Could not start CPU load: {started.detail}[/red]")
        return False

    report(f"[bold]{plan.label}[/bold]: idle until {load_start:%H:%M:%S}, {workers}-core load "
           f"until {load_stop:%H:%M:%S}, then {plan.cooldown_sec // 60} min cooldown")
    report(f"Logging every {plan.interval_sec}s -> {run_dir / SMART_LOG}")

    stop_event = threading.Event()
    lock = threading.Lock()
    coretemp: list[tuple[datetime, float]] = []
    latest: dict[str, float] = {}

    def on_sample(sample: MonitorSample) -> None:
        with lock:
            latest.clear()
            for s in sample.sensor_readings:
                if s.temperature_c is not None:
                    latest[s.name] = s.temperature_c
            if "coretemp" in latest:
                coretemp.append((datetime.fromisoformat(sample.timestamp), latest["coretemp"]))

    logger = threading.Thread(
        target=monitor_loop,
        args=(device, run_dir / SMART_LOG),
        kwargs={"interval_sec": plan.interval_sec, "stop_event": stop_event, "on_sample": on_sample},
        daemon=True,
    )

    detector = SoakDetector(load_start, plan.soak_max_rise, plan.soak_window_min,
                            plan.soak_min_load_min) if plan.stop_at_soak else None
    end = load_stop + timedelta(seconds=plan.cooldown_sec)
    load_running = True
    next_status = next_soak_check = time.monotonic()

    with keep_awake() as awake:
        if awake:
            report("[dim]PC sleep blocked until the run finishes (display may still turn off)[/dim]")
        logger.start()
        try:
            while datetime.now() < end:
                now = datetime.now()
                if load_running and now >= load_stop:
                    load_running = False
                if time.monotonic() >= next_status:
                    next_status += 60
                    with lock:
                        reading = "  ".join(f"{k} {latest[k]:.0f}C" for k in ("coretemp", "cpu", "system")
                                            if k in latest)
                    phase = "idle" if now < load_start else "load" if load_running else "cooldown"
                    report(f"[{now:%H:%M:%S}] {phase:8} {reading}")
                if detector and load_running and now >= load_start and time.monotonic() >= next_soak_check:
                    next_soak_check += 60
                    with lock:
                        points = list(coretemp)
                    if detector.check(points, now):
                        stopped = cpu_load.stop_cpu_load(device)
                        load_running = False
                        append_event(run_dir, "soak_reached", now.replace(microsecond=0))
                        append_event(run_dir, "load_stop", now.replace(microsecond=0))
                        end = now + timedelta(seconds=plan.cooldown_sec)
                        report(f"[green]Soak reached (trend {detector.last_rise:+.2f}C/"
                               f"{plan.soak_window_min:g} min); load stopped ({stopped.detail}); "
                               f"cooldown until {end:%H:%M:%S}[/green]")
                    elif detector.last_rise is not None:
                        report(f"[dim]  soak check: trend {detector.last_rise:+.2f}C/"
                               f"{plan.soak_window_min:g} min [{detector.hits}/{detector.confirm}][/dim]")
                time.sleep(1)
        except KeyboardInterrupt:
            report("[yellow]Stopping early...[/yellow]")
            if load_running or datetime.now() < load_start:
                report(f"CPU load: {cpu_load.stop_cpu_load(device).detail}")
                append_event(run_dir, "load_stop", datetime.now().replace(microsecond=0))
            append_event(run_dir, "aborted", datetime.now().replace(microsecond=0))
            plan.shutdown_after = False
        finally:
            stop_event.set()
            logger.join(timeout=plan.interval_sec + 30)

    report(f"[green]Run complete: {run_dir}[/green]")
    if plan.shutdown_after:
        report("Powering off the NAS...")
        result = cpu_load.poweroff(device)
        report("Poweroff sent." if result.ok else f"[red]Poweroff failed: {result.detail}[/red]")
    return True
