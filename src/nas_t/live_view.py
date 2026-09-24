# AI-Assisted: Generated with assistance from AI tools.
"""Builds the live-updating dashboard shown by `nas_t test` while a thermal
test is running."""

from typing import Optional

from nas_t.monitor import MonitorSample
from rich.console import Group
from rich.panel import Panel
from rich.table import Table


def format_health(healthy: Optional[bool]) -> str:
    if healthy is None:
        return "-"
    return "[green]PASSED[/green]" if healthy else "[red]FAILED[/red]"


def _celsius_fahrenheit(celsius: Optional[float]) -> str:
    """Formats a temperature the way QNAP's getsysinfo does, e.g. "45 C/113 F"."""
    if celsius is None:
        return "-"
    return f"{int(celsius)} C/{int(celsius * 9 / 5 + 32)} F"


def format_delta(current: Optional[float], baseline: Optional[float]) -> str:
    """Renders a temperature change since the run started, e.g. "+3.0" or "-1.5".

    Rising is the interesting direction in a thermal test, so it's highlighted.
    """
    if current is None or baseline is None:
        return "-"
    delta = current - baseline
    if delta > 0:
        return f"[red]+{delta:.1f}[/red]"
    if delta < 0:
        return f"[green]{delta:.1f}[/green]"
    return "[dim]0.0[/dim]"


def baseline_from(drives, sensors) -> dict:
    """Snapshots the current temperatures, keyed by sensor name, as a delta reference."""
    baseline = {r.drive: r.temperature_c for r in drives if r.temperature_c is not None}
    baseline.update({s.name: s.temperature_c for s in sensors if s.temperature_c is not None})
    return baseline


def build_status_table(drives, sensors, title: str, baseline: Optional[dict] = None) -> Table:
    """Renders drives and chassis sensors in a single table.

    Health is drive-only, so chassis sensor rows show "-" in that column. Passing a
    baseline adds a column showing each sensor's change since then.
    """
    table = Table(title=title)
    table.add_column("Sensor")
    table.add_column("Temp (C)")
    if baseline is not None:
        table.add_column("Δ (C)")
    table.add_column("Health")

    def row(name: str, temperature: Optional[float], health: str) -> None:
        cells = [name, "-" if temperature is None else str(temperature)]
        if baseline is not None:
            cells.append(format_delta(temperature, baseline.get(name)))
        cells.append(health)
        table.add_row(*cells)

    if not drives and not sensors:
        row("(no readings yet)", None, "-")
    for reading in drives:
        row(reading.drive, reading.temperature_c, format_health(reading.healthy))
    for sensor in sensors:
        row(sensor.name, sensor.temperature_c, "-")
    return table


def format_summary_line(timestamp: str, drives, sensors) -> str:
    """One-line digest of a poll, for pasting into notes or a ticket.

    Mirrors the shape of the original nas_thermal_stream.sh output:
    ``[ts] CPU: 41 C/105 F | System: 47 C/117 F | Disk1: ... | eth0: 80C``
    """
    by_name = {sensor.name: sensor.temperature_c for sensor in sensors}
    parts = []

    for name, label in (("cpu", "CPU"), ("system", "System")):
        if name in by_name:
            parts.append(f"{label}: {_celsius_fahrenheit(by_name.pop(name))}")

    for reading in drives:
        # "disk1" -> "Disk1", matching the original script's labels.
        parts.append(f"{reading.drive.capitalize()}: {_celsius_fahrenheit(reading.temperature_c)}")

    # Remaining sensors (NICs, coretemp) use the script's terser "80C" form.
    for name, celsius in by_name.items():
        parts.append(f"{name}: {'-' if celsius is None else f'{int(celsius)}C'}")

    return f"[{timestamp}] " + " | ".join(parts)


def build_dashboard(
    elapsed_sec: float,
    duration_sec: Optional[float],
    loader_name: str,
    sample: Optional[MonitorSample],
    peak_rx_mbps: Optional[float] = None,
    min_rx_mbps: Optional[float] = None,
) -> Group:
    """Renders the current SMART + network readings and test progress as a rich renderable,
    suitable for passing to a `rich.live.Live` object's `update()`.
    """
    duration_str = "unbounded" if duration_sec is None else f"{duration_sec:.0f}s"
    elapsed_str = f"{elapsed_sec:.0f}s"

    timestamp = sample.timestamp if sample is not None else None

    header = Panel(
        f"[bold]Loader:[/bold] {loader_name}    "
        f"[bold]Elapsed:[/bold] {elapsed_str} / {duration_str}    "
        f"[bold]Last poll:[/bold] {timestamp or 'waiting for first poll...'}\n"
        "[dim]Press Ctrl+C to stop early and write out the CSVs[/dim]",
        title="NAS_T live test",
        border_style="cyan",
    )

    readings = sample.drive_readings if sample is not None else []
    sensors = sample.sensor_readings if sample is not None else []
    smart_table = build_status_table(readings, sensors, "SMART status")

    network_table = Table(title="Network throughput (NAS NIC)")
    network_table.add_column("Interface")
    network_table.add_column("RX (Mb/s)")
    network_table.add_column("TX (Mb/s)")
    network_table.add_column("Link (Mb/s)")
    network_table.add_column("RX peak / min")

    network = sample.network if sample is not None else None
    if network is None:
        network_table.add_row("(awaiting second poll)", "-", "-", "-", "-")
    else:
        peak_str = f"{peak_rx_mbps:.1f}" if peak_rx_mbps is not None else "-"
        min_str = f"{min_rx_mbps:.1f}" if min_rx_mbps is not None else "-"
        network_table.add_row(
            network.interface,
            f"{network.rx_mbps:.1f}",
            f"{network.tx_mbps:.1f}",
            str(network.link_speed_mbps) if network.link_speed_mbps is not None else "unknown",
            f"{peak_str} / {min_str}",
        )

    return Group(header, smart_table, network_table)
