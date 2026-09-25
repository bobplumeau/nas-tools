# AI-Assisted: Generated with assistance from AI tools.
"""Entry point for the ``nas_t`` CLI: NAS testing tool."""

import builtins
import threading
import time

from pathlib import Path
from typing import Annotated, Optional

import typer

from rich import print
from rich.console import Group
from rich.live import Live
from rich.text import Text
from typer.core import TyperGroup


class _BannerGroup(TyperGroup):
    """Prints the ASCII banner above the top-level help page.

    The help page is the only place the banner belongs: showing it on every command would
    put decoration in front of (and inside piped/CSV-adjacent) real output.
    """

    def format_help(self, ctx, formatter) -> None:
        from nas_t.banner import print_banner

        print_banner()
        super().format_help(ctx, formatter)


app = typer.Typer(add_completion=True, no_args_is_help=False, cls=_BannerGroup)

# Resolved lazily per-invocation (see nas_t.config.default_devices_file) so the CLI can be
# installed globally and still find devices.yaml from any working directory.
_DEFAULT_DEVICES_FILE = None


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """NAS_T: CLI tool for testing NAS units."""
    # Running `nas_t` with no subcommand drops into the interactive shell. The banner is
    # printed by the shell on entry, and by _BannerGroup.format_help on the help page.
    if ctx.invoked_subcommand is None:
        from nas_t.shell import run_shell

        run_shell(app)


@app.command(rich_help_panel="Main Commands")
def shell(
    device: Annotated[Optional[str], typer.Option(help="Device to pre-select on entry")] = None,
) -> None:
    """Start the interactive NAS_T shell (also entered by running `nas_t` with no args)."""
    from nas_t.shell import run_shell

    run_shell(app, device=device)


@app.command(rich_help_panel="Main Commands")
def status(
    device: Annotated[str, typer.Option(help="Device name from devices.yaml")],
    devices_file: Annotated[
        Path, typer.Option(help="Path to devices.yaml")
    ] = _DEFAULT_DEVICES_FILE,
) -> None:
    """One-shot SMART temperature/health snapshot for a device."""
    from nas_t.config import get_device
    from nas_t.live_view import build_status_table, format_summary_line
    from nas_t.smart_monitor import poll_all
    from nas_t.ssh_client import resolve_target_ip_with_errors

    device_profile = get_device(devices_file, device)

    resolved_ip, errors = resolve_target_ip_with_errors(device_profile)
    if resolved_ip is None:
        print(f"[red]Could not reach {device} over SSH.[/red]")
        for error in errors:
            print(f"  [red]{error}[/red]")
        raise typer.Exit(code=1)

    print(f"[green]Connected to {device} at {resolved_ip}[/green]")

    drives, sensors = poll_all(device_profile)
    print(build_status_table(drives, sensors, f"SMART status: {device}"))
    builtins.print(format_summary_line(time.strftime("%Y-%m-%dT%H:%M:%S"), drives, sensors))


@app.command(rich_help_panel="Main Commands")
def monitor(
    device: Annotated[str, typer.Option(help="Device name from devices.yaml")],
    interval: Annotated[int, typer.Option(help="Polling interval in seconds")] = 2,
    duration: Annotated[
        Optional[int], typer.Option(help="Total run duration in seconds (omit to run until Ctrl+C)")
    ] = None,
    devices_file: Annotated[
        Optional[Path], typer.Option(help="Path to devices.yaml")
    ] = _DEFAULT_DEVICES_FILE,
) -> None:
    """Live-updating SMART temperature/health view, in the same format as `status`.

    Nothing is written to disk; use `log` to record readings to CSV."""
    from nas_t.config import get_device
    from nas_t.live_view import baseline_from, build_status_table, format_summary_line
    from nas_t.monitor import monitor_loop

    device_profile = get_device(devices_file, device)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    header = f"Monitoring {device} every {interval}s - started {started_at} (Ctrl+C to stop)"
    print(f"[bold]{header}[/bold]")

    title = f"SMART status: {device}"
    last_summary = ""
    last_table = None
    # Filled from the first poll, so the delta column reads "change since I started".
    baseline: dict = {}

    # screen=True renders on the alternate screen buffer. Without it, a table taller than
    # the terminal can't be overwritten in place and every refresh stacks another copy.
    with Live(build_status_table([], [], title, baseline), auto_refresh=False, screen=True) as live:

        def render(sample) -> None:
            nonlocal last_summary
            if not baseline:
                baseline.update(baseline_from(sample.drive_readings, sample.sensor_readings))
            nonlocal last_table
            last_summary = format_summary_line(
                sample.timestamp, sample.drive_readings, sample.sensor_readings
            )
            last_table = build_status_table(
                sample.drive_readings, sample.sensor_readings, title, baseline
            )
            live.update(
                Group(Text(header), last_table, Text(last_summary)),
                refresh=True,
            )

        try:
            monitor_loop(
                device_profile,
                interval_sec=interval,
                duration_sec=duration,
                on_sample=render,
            )
        except KeyboardInterrupt:
            pass

    # The alternate screen is torn down on exit, so reprint the last reading to leave it
    # in the scrollback. The summary goes through plain stdout, unwrapped, so it can be
    # copied as a single line (rich hard-wraps inside Live, which pastes as several).
    if last_table is not None:
        print(last_table)
    if last_summary:
        builtins.print(last_summary)


@app.command(rich_help_panel="Main Commands")
def log(
    device: Annotated[str, typer.Option(help="Device name from devices.yaml")],
    output: Annotated[Path, typer.Option(help="CSV file to append SMART readings to")],
    network_output: Annotated[
        Optional[Path],
        typer.Option(help="CSV file to append network throughput readings to (omit to skip)"),
    ] = None,
    interface: Annotated[
        Optional[str],
        typer.Option(
            help="NAS network interface to sample (defaults to the device profile, then auto-detect)"
        ),
    ] = None,
    interval: Annotated[int, typer.Option(help="Polling interval in seconds")] = 30,
    duration: Annotated[
        Optional[int], typer.Option(help="Total run duration in seconds (omit to run until Ctrl+C)")
    ] = None,
    devices_file: Annotated[
        Optional[Path], typer.Option(help="Path to devices.yaml")
    ] = _DEFAULT_DEVICES_FILE,
) -> None:
    """Continuously poll SMART temperature/health (and optionally network throughput),
    logging to CSV files."""
    from nas_t.config import get_device
    from nas_t.monitor import monitor_loop

    device_profile = get_device(devices_file, device)
    print(f"[bold]Logging {device} every {interval}s -> {output}[/bold] (Ctrl+C to stop)")
    if network_output is not None:
        print(f"[bold]Network throughput -> {network_output}[/bold]")
    try:
        monitor_loop(
            device_profile,
            output,
            network_csv=network_output,
            network_interface=interface or device_profile.network_interface,
            interval_sec=interval,
            duration_sec=duration,
        )
    except KeyboardInterrupt:
        print("[yellow]Logging stopped.[/yellow]")


@app.command(rich_help_panel="Main Commands")
def load(
    mount_path: Annotated[Path, typer.Option(help="Local path where the NAS NFS share is mounted")],
    sample_mcap: Annotated[
        Path, typer.Option(help="Path to a real, already-captured sample mcap file")
    ],
    concurrency: Annotated[
        int, typer.Option(help="Number of simulated concurrent VPU writers")
    ] = 3,
    interval: Annotated[float, typer.Option(help="Seconds between writes, per writer")] = 90.0,
    duration: Annotated[
        Optional[float],
        typer.Option(help="Total run duration in seconds (omit to run until Ctrl+C)"),
    ] = None,
) -> None:
    """Generate representative NAS write load by periodically copying a sample mcap."""
    from nas_t.replay_copy_loader import run_replay_copy_load

    print(
        f"[bold]Starting load: {concurrency} writers, every {interval}s, "
        f"into {mount_path}[/bold] (Ctrl+C to stop)"
    )
    run_replay_copy_load(
        sample_file=sample_mcap,
        mount_root=mount_path,
        concurrency=concurrency,
        interval_sec=interval,
        duration_sec=duration,
    )


@app.command(name="fio-load", rich_help_panel="Main Commands")
def fio_load(
    mount_path: Annotated[Path, typer.Option(help="Local path where the NAS NFS share is mounted")],
    block_size: Annotated[str, typer.Option(help="fio block size, e.g. 1M")] = "1M",
    write_size: Annotated[
        str, typer.Option(help="Total bytes written per job before stopping, e.g. 3G")
    ] = "3G",
    runtime: Annotated[int, typer.Option(help="Time-based run cap in seconds")] = 3600,
    concurrency: Annotated[
        int, typer.Option(help="Number of parallel fio writer jobs (simulated VPUs)")
    ] = 3,
    rate: Annotated[
        Optional[str],
        typer.Option(
            help="Optional per-job throughput cap, e.g. 35M, to avoid saturating the link"
        ),
    ] = None,
    direct_io: Annotated[
        bool, typer.Option(help="Enable O_DIRECT (many NFS clients don't support this)")
    ] = False,
) -> None:
    """Generate synthetic sustained sequential write load using fio (worst-case stress mode,
    as opposed to the field-representative `load`/replay-copy command)."""
    from nas_t.fio_loader import run_fio_load

    print(
        f"[bold]Starting fio load: {concurrency} jobs, {block_size} blocks, "
        f"into {mount_path}[/bold]"
    )
    exit_code = run_fio_load(
        mount_path=mount_path,
        block_size=block_size,
        write_size=write_size,
        runtime_sec=runtime,
        concurrency=concurrency,
        rate=rate,
        direct_io=direct_io,
    )
    if exit_code != 0:
        print(f"[red]fio exited with code {exit_code}[/red]")
        raise typer.Exit(code=exit_code)


@app.command(rich_help_panel="Main Commands")
def test(
    device: Annotated[str, typer.Option(help="Device name from devices.yaml")],
    mount_path: Annotated[Path, typer.Option(help="Local path where the NAS NFS share is mounted")],
    output_dir: Annotated[Path, typer.Option(help="Directory to write monitor CSV + results into")],
    loader: Annotated[
        str,
        typer.Option(
            help="Which write-load generator to use: 'replay' (field-representative) or 'fio' (synthetic stress)"
        ),
    ] = "replay",
    sample_mcap: Annotated[
        Optional[Path],
        typer.Option(
            help="Path to a real, already-captured sample mcap file (required for --loader replay)"
        ),
    ] = None,
    concurrency: Annotated[
        int, typer.Option(help="Number of simulated concurrent VPU writers")
    ] = 3,
    write_interval: Annotated[
        float, typer.Option(help="Seconds between writes, per writer (--loader replay only)")
    ] = 90.0,
    block_size: Annotated[
        str, typer.Option(help="fio block size, e.g. 1M (--loader fio only)")
    ] = "1M",
    write_size: Annotated[
        str, typer.Option(help="Total bytes written per fio job, e.g. 3G (--loader fio only)")
    ] = "3G",
    rate: Annotated[
        Optional[str],
        typer.Option(help="Optional per-job fio throughput cap, e.g. 35M (--loader fio only)"),
    ] = None,
    monitor_interval: Annotated[
        int, typer.Option(help="SMART/network polling interval in seconds")
    ] = 30,
    interface: Annotated[
        Optional[str],
        typer.Option(
            help="NAS network interface to sample (defaults to the device profile, then auto-detect)"
        ),
    ] = None,
    duration: Annotated[float, typer.Option(help="Total test duration in seconds")] = 3600.0,
    devices_file: Annotated[
        Path, typer.Option(help="Path to devices.yaml")
    ] = _DEFAULT_DEVICES_FILE,
) -> None:
    """Run SMART monitoring and write load generation together for a full thermal test,
    with a live-updating dashboard in the terminal. Press Ctrl+C at any point to stop early -
    the CSV log is flushed after every poll, so no data from completed polls is lost."""
    from nas_t.config import get_device
    from nas_t.live_view import build_dashboard
    from nas_t.monitor import monitor_loop

    if loader not in ("replay", "fio"):
        print(f"[red]Unknown loader '{loader}'. Expected 'replay' or 'fio'.[/red]")
        raise typer.Exit(code=1)
    if loader == "replay" and sample_mcap is None:
        print("[red]--sample-mcap is required when --loader replay is used.[/red]")
        raise typer.Exit(code=1)

    device_profile = get_device(devices_file, device)
    output_dir.mkdir(parents=True, exist_ok=True)
    smart_csv = output_dir / "smart_log.csv"
    network_csv = output_dir / "network_log.csv"

    stop_event = threading.Event()
    state_lock = threading.Lock()
    shared_state: dict = {"sample": None, "peak_rx_mbps": None, "min_rx_mbps": None}

    def on_sample(sample) -> None:
        with state_lock:
            shared_state["sample"] = sample
            if sample.network is not None:
                rx = sample.network.rx_mbps
                peak = shared_state["peak_rx_mbps"]
                low = shared_state["min_rx_mbps"]
                shared_state["peak_rx_mbps"] = rx if peak is None else max(peak, rx)
                shared_state["min_rx_mbps"] = rx if low is None else min(low, rx)

    monitor_thread = threading.Thread(
        target=monitor_loop,
        args=(device_profile, smart_csv),
        kwargs={
            "network_csv": network_csv,
            "network_interface": interface or device_profile.network_interface,
            "interval_sec": monitor_interval,
            "duration_sec": duration,
            "stop_event": stop_event,
            "on_sample": on_sample,
        },
        daemon=True,
    )
    monitor_thread.start()

    if loader == "replay":
        from nas_t.replay_copy_loader import run_replay_copy_load

        loader_thread = threading.Thread(
            target=run_replay_copy_load,
            kwargs={
                "sample_file": sample_mcap,
                "mount_root": mount_path,
                "concurrency": concurrency,
                "interval_sec": write_interval,
                "duration_sec": duration,
                "stop_event": stop_event,
            },
            daemon=True,
        )
    else:
        from nas_t.fio_loader import run_fio_load

        loader_thread = threading.Thread(
            target=run_fio_load,
            kwargs={
                "mount_path": mount_path,
                "block_size": block_size,
                "write_size": write_size,
                "runtime_sec": int(duration),
                "concurrency": concurrency,
                "rate": rate,
                "stop_event": stop_event,
            },
            daemon=True,
        )
    loader_thread.start()

    start = time.monotonic()
    try:
        with Live(refresh_per_second=2, transient=False) as live:
            while not stop_event.is_set() and (time.monotonic() - start) < duration:
                with state_lock:
                    sample = shared_state["sample"]
                    peak_rx = shared_state["peak_rx_mbps"]
                    min_rx = shared_state["min_rx_mbps"]
                elapsed = time.monotonic() - start
                live.update(build_dashboard(elapsed, duration, loader, sample, peak_rx, min_rx))
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[yellow]Stopping test early, writing out remaining CSV data...[/yellow]")
    finally:
        stop_event.set()
        monitor_thread.join(timeout=monitor_interval + 10)
        loader_thread.join(timeout=10)

    print(f"[green]Test complete. SMART log: {smart_csv}  Network log: {network_csv}[/green]")


@app.command(name="cpu-test", rich_help_panel="CPU Thermal Tests")
def cpu_test(
    device: Annotated[str, typer.Option(help="Device name from devices.yaml")],
    label: Annotated[str, typer.Option(help="Build under test, e.g. '1 layer PTM7950'")],
    output_dir: Annotated[
        Optional[Path],
        typer.Option(help="Run folder (default: results/cpu_<date>_<time>)"),
    ] = None,
    idle: Annotated[int, typer.Option(help="Idle baseline before load, seconds")] = 300,
    load: Annotated[int, typer.Option(help="All-core load duration, seconds")] = 3600,
    cooldown: Annotated[int, typer.Option(help="Logging after load stops, seconds")] = 900,
    interval: Annotated[int, typer.Option(help="Polling interval, seconds")] = 15,
    workers: Annotated[
        Optional[int], typer.Option(help="Busy loops to run (default: one per NAS CPU)")
    ] = None,
    stop_at_soak: Annotated[
        bool, typer.Option(help="End the load early once coretemp reaches steady state")
    ] = False,
    soak_rise: Annotated[
        float, typer.Option(help="Soak threshold: max coretemp rise per soak window, C")
    ] = 0.5,
    soak_window: Annotated[float, typer.Option(help="Soak trend window, minutes")] = 10.0,
    soak_min_load: Annotated[float, typer.Option(help="Minimum load before soak can trigger, minutes")] = 20.0,
    shutdown_after: Annotated[
        bool, typer.Option(help="Power the NAS off when the run completes (for a cold start next time)")
    ] = False,
    devices_file: Annotated[
        Optional[Path], typer.Option(help="Path to devices.yaml")
    ] = _DEFAULT_DEVICES_FILE,
) -> None:
    """Idle baseline, all-core CPU load on the NAS, then cooldown, logging temperatures
    throughout. The load runs on the NAS and stops on schedule even if this PC sleeps
    (which the test also blocks while logging). Compare builds with `nas_t compare`."""
    from datetime import datetime

    from nas_t.config import get_device
    from nas_t.cpu_test import CpuTestPlan, run_cpu_test
    from nas_t.ssh_client import resolve_target_ip_with_errors

    device_profile = get_device(devices_file, device)
    ip, errors = resolve_target_ip_with_errors(device_profile)
    if ip is None:
        print(f"[red]Could not reach {device} over SSH.[/red]")
        for error in errors:
            print(f"  {error}")
        raise typer.Exit(code=1)
    print(f"Connected to {device} at {ip}")

    run_dir = output_dir or Path("results") / f"cpu_{datetime.now():%Y%m%d_%H%M}"
    plan = CpuTestPlan(
        label=label, idle_sec=idle, load_sec=load, cooldown_sec=cooldown, interval_sec=interval,
        workers=workers, stop_at_soak=stop_at_soak, soak_max_rise=soak_rise,
        soak_window_min=soak_window, soak_min_load_min=soak_min_load, shutdown_after=shutdown_after,
    )
    if not run_cpu_test(device_profile, run_dir, plan, report=print):
        raise typer.Exit(code=1)


@app.command(name="cpu-stop", rich_help_panel="CPU Thermal Tests")
def cpu_stop(
    device: Annotated[str, typer.Option(help="Device name from devices.yaml")],
    devices_file: Annotated[
        Optional[Path], typer.Option(help="Path to devices.yaml")
    ] = _DEFAULT_DEVICES_FILE,
) -> None:
    """Stop a CPU load left running on the NAS (e.g. after closing a test window)."""
    from nas_t.config import get_device
    from nas_t.cpu_load import stop_cpu_load

    result = stop_cpu_load(get_device(devices_file, device))
    print(("[green]Stopped.[/green] " if result.ok else "[red]Not confirmed.[/red] ") + result.detail)


@app.command(rich_help_panel="Main Commands")
def wake(
    device: Annotated[str, typer.Option(help="Device name from devices.yaml (needs a `mac:` entry)")],
    wait: Annotated[int, typer.Option(help="Seconds to wait for SSH to come up (0 = don't wait)")] = 300,
    devices_file: Annotated[
        Optional[Path], typer.Option(help="Path to devices.yaml")
    ] = _DEFAULT_DEVICES_FILE,
) -> None:
    """Power the NAS on with Wake-on-LAN, then wait until it accepts SSH."""
    import socket

    from nas_t.config import get_device
    from nas_t.wol import broadcast_targets, send_magic_packet

    profile = get_device(devices_file, device)
    if not profile.mac:
        print(f"[red]No `mac:` for {device} in devices.yaml.[/red] Find it on the NAS label or in "
              "QTS Control Panel > Network & Virtual Switch.")
        raise typer.Exit(code=1)
    sent = send_magic_packet(profile.mac, broadcast_targets(profile.candidate_ips))
    print(f"Magic packet sent to {profile.mac} ({sent} broadcasts)")
    if wait <= 0:
        return
    print(f"Waiting up to {wait}s for SSH (boot takes a minute or two)...")
    start = time.monotonic()
    while time.monotonic() - start < wait:
        for ip in profile.candidate_ips:
            try:
                with socket.create_connection((ip, 22), timeout=2):
                    print(f"[green]{device} is up at {ip} after {time.monotonic() - start:.0f}s[/green]")
                    return
            except OSError:
                pass
        time.sleep(5)
    print(f"[red]{device} didn't answer on SSH within {wait}s[/red] - check WoL is enabled and "
          "that this machine is on the NAS's local network.")
    raise typer.Exit(code=1)


@app.command(rich_help_panel="CPU Thermal Tests")
def plot(
    run_dir: Annotated[Path, typer.Argument(help="Run folder containing smart_log.csv")],
    live: Annotated[bool, typer.Option(help="Keep refreshing while the run is in progress")] = False,
    refresh: Annotated[int, typer.Option(help="Live refresh interval, seconds")] = 15,
    smooth: Annotated[float, typer.Option(help="Gaussian smoothing, in samples (0 = raw)")] = 0.0,
    no_window: Annotated[bool, typer.Option(help="Only save temps.png, don't open a window")] = False,
) -> None:
    """Plot a run: temperatures, and CPU/package temperature above system, with the load
    phases marked. Saves temps.png in the run folder."""
    from nas_t.plotting import plot_run

    out = plot_run(run_dir, live=live, refresh_sec=refresh, sigma=smooth, show=not no_window)
    print(f"Saved {out}")


@app.command(rich_help_panel="CPU Thermal Tests")
def compare(
    run_dirs: Annotated[list[Path], typer.Argument(help="Two or more run folders")],
    sensor: Annotated[str, typer.Option(help="Sensor to compare")] = "coretemp",
    minus: Annotated[
        Optional[str], typer.Option(help="Reference sensor to subtract ('' for absolute)")
    ] = "system",
    smooth: Annotated[float, typer.Option(help="Gaussian smoothing, in samples")] = 2.0,
    output: Annotated[Optional[Path], typer.Option(help="Where to save the PNG")] = None,
    no_window: Annotated[bool, typer.Option(help="Only save the PNG, don't open a window")] = False,
) -> None:
    """Overlay runs aligned to load start and report each run's steady state (mean over
    the last 10 minutes of load) - e.g. 1 vs 2 layers of CPU pad."""
    from nas_t.plotting import compare_runs

    out, results = compare_runs(run_dirs, sensor=sensor, minus=minus or None, sigma=smooth,
                                out=output, show=not no_window)
    what = f"{sensor} - {minus}" if minus else sensor
    print(f"Steady state ({what}, last 10 min of load):")
    baseline = results[0][2] if results else None
    for label, _, value in results:
        if value is None:
            print(f"  {label}: n/a (no load phase in events.csv)")
            continue
        delta = f"  ({value - baseline:+.1f} vs {results[0][0]})" if baseline is not None and label != results[0][0] else ""
        print(f"  {label}: {value:.1f} C{delta}")
    print(f"Saved {out}")


if __name__ == "__main__":
    app()
