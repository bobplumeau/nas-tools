"""Plots for run folders: a two-panel run view (temperatures + CPU above system) that can
refresh live while a test runs, and a comparison of several runs aligned to load start.

Requires matplotlib (``pip install -e .[plot]``).
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from nas_t.runs import event_time, read_events, read_samples, series

MAIN_SENSORS = {"coretemp": "tab:red", "cpu": "tab:orange", "system": "tab:gray"}
CONTEXT_SENSORS = {"disk1": "tab:blue", "disk2": "tab:cyan", "disk3": "tab:green", "disk4": "tab:purple"}


def smooth(values, sigma: float) -> np.ndarray:
    """Gaussian smoothing with edge padding, so the ends don't dip toward zero."""
    values = np.asarray(values, dtype=float)
    half = int(3 * sigma)
    if sigma <= 0 or len(values) <= half:
        return values
    kernel = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    return np.convolve(np.pad(values, half, mode="edge"), kernel, mode="valid")


def _plt():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("matplotlib is required: pip install -e .[plot]") from exc
    return plt


def _mark_phases(ax, events, label_axis: bool) -> None:
    stop_label = "soak - load off" if "soak_reached" in events else "load off"
    for key, text in (("load_start", "load on"), ("load_stop", stop_label)):
        t = event_time(events, key)
        if t is None:
            continue
        ax.axvline(t, color="k", linestyle="--", linewidth=0.8, alpha=0.5)
        if label_axis:
            ax.text(t, 1.01, text, transform=ax.get_xaxis_transform(), fontsize=8, ha="center")


def draw_run(fig, run_dir: Path, sigma: float = 0.0) -> None:
    """Draws (or redraws) a run into fig: temperatures on top, CPU minus system below."""
    import matplotlib.dates as mdates

    fig.clear()
    ax, ax2 = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    events = read_events(run_dir)
    try:
        samples = read_samples(run_dir)
    except FileNotFoundError:
        samples = []
    if not samples:
        ax.set_title(f"{run_dir.name}: waiting for data")
        return

    for sensors, bold in ((CONTEXT_SENSORS, False), (MAIN_SENSORS, True)):
        for name, color in sensors.items():
            pts = series(samples, name)
            if not pts:
                continue
            t, v = zip(*pts)
            if bold and sigma > 0:
                ax.plot(t, v, color=color, linewidth=0.7, alpha=0.25)
                v = smooth(v, sigma)
            ax.plot(t, v, label=name, color=color,
                    linewidth=1.8 if bold else 0.8, alpha=1.0 if bold else 0.35)

    for name in ("coretemp", "cpu"):
        pts = series(samples, name, minus="system")
        if pts:
            t, v = zip(*pts)
            ax2.plot(t, smooth(v, sigma) if sigma > 0 else v, label=f"{name} - system",
                     color=MAIN_SENSORS[name], linewidth=1.6)
    ax2.axhline(0, color="k", linewidth=0.6, alpha=0.4)

    _mark_phases(ax, events, label_axis=True)
    _mark_phases(ax2, events, label_axis=False)

    last_t, last = samples[-1]
    latest = "   ".join(f"{k} {last[k]:.0f}C" for k in MAIN_SENSORS if k in last)
    ax.set_title(f"{events.get('label', run_dir.name)}\nlatest {last_t:%H:%M:%S}:  {latest}", fontsize=10)
    ax.set_ylabel("C")
    ax2.set_ylabel("above system (C)")
    ax.legend(loc="upper left", ncol=4, fontsize=8)
    ax2.legend(loc="upper left", ncol=2, fontsize=8)
    for a in (ax, ax2):
        a.grid(alpha=0.25)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()


def plot_run(run_dir: Path, live: bool = False, refresh_sec: int = 15, sigma: float = 0.0,
             show: bool = True) -> Path:
    """Plots a run and saves run_dir/temps.png. With live=True, re-reads every refresh_sec."""
    plt = _plt()
    fig = plt.figure(figsize=(11, 7))
    fig.canvas.manager.set_window_title(f"nas_t - {run_dir.name}")
    out = run_dir / "temps.png"

    def refresh(_=None):
        draw_run(fig, run_dir, sigma=sigma)
        fig.savefig(out, dpi=120)

    refresh()
    if show and live:
        from matplotlib.animation import FuncAnimation

        _anim = FuncAnimation(fig, refresh, interval=refresh_sec * 1000, cache_frame_data=False)
        plt.show()
    elif show:
        plt.show()
    plt.close(fig)
    return out


def steady_state(samples, events, sensor: str = "coretemp", minus: Optional[str] = "system",
                 last_min: float = 10.0) -> Optional[float]:
    """Mean of sensor (minus reference) over the last `last_min` minutes of load."""
    start, stop = event_time(events, "load_start"), event_time(events, "load_stop")
    if start is None or stop is None:
        return None
    pts = [v for t, v in series(samples, sensor, minus)
           if start <= t <= stop and (stop - t).total_seconds() <= last_min * 60]
    return sum(pts) / len(pts) if pts else None


def compare_runs(run_dirs: list[Path], sensor: str = "coretemp", minus: Optional[str] = "system",
                 sigma: float = 2.0, out: Optional[Path] = None, show: bool = True):
    """Overlays runs on minutes-since-load-start and returns per-run steady-state values."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5))
    results = []
    for run_dir in run_dirs:
        events = read_events(run_dir)
        samples = read_samples(run_dir)
        start = event_time(events, "load_start") or samples[0][0]
        pts = series(samples, sensor, minus)
        if not pts:
            continue
        minutes = [(t - start).total_seconds() / 60 for t, _ in pts]
        values = [v for _, v in pts]
        label = events.get("label", run_dir.name)
        line, = ax.plot(minutes, smooth(values, sigma), label=label, linewidth=1.8)
        ax.plot(minutes, values, color=line.get_color(), linewidth=0.6, alpha=0.25)
        stop = event_time(events, "load_stop")
        if stop is not None:
            ax.axvline((stop - start).total_seconds() / 60, color=line.get_color(),
                       linestyle="--", linewidth=0.8, alpha=0.6)
        results.append((label, run_dir, steady_state(samples, events, sensor, minus)))

    ax.axvline(0, color="k", linestyle="--", linewidth=0.8, alpha=0.5)
    what = f"{sensor} - {minus}" if minus else sensor
    ax.set_title(f"{what}, aligned to load start (dashed: load off)")
    ax.set_xlabel("minutes since load start")
    ax.set_ylabel("C")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9)
    fig.tight_layout()
    out = out or Path(run_dirs[0]).parent / "compare.png"
    fig.savefig(out, dpi=120)
    if show:
        plt.show()
    plt.close(fig)
    return out, results
