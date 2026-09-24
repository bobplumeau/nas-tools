# AI-Assisted: Generated with assistance from AI tools.
"""Unit tests for the combined status table and the one-line summary digest."""

import unittest

from nas_t.live_view import (
    baseline_from,
    build_status_table,
    format_delta,
    format_summary_line,
)
from nas_t.smart_monitor import DriveReading, SensorReading

_DRIVES = [
    DriveReading(drive="disk1", temperature_c=45.0, healthy=True),
    DriveReading(drive="disk2", temperature_c=46.0, healthy=True),
]
_SENSORS = [
    SensorReading(name="cpu", temperature_c=41.0),
    SensorReading(name="system", temperature_c=47.0),
    SensorReading(name="eth0", temperature_c=80.0),
]


class TestCombinedTable(unittest.TestCase):
    def test_drives_and_sensors_share_one_table(self):
        table = build_status_table(_DRIVES, _SENSORS, "title")

        self.assertEqual(len(table.columns), 3)
        self.assertEqual(table.row_count, len(_DRIVES) + len(_SENSORS))

    def test_placeholder_row_when_there_is_nothing_yet(self):
        self.assertEqual(build_status_table([], [], "title").row_count, 1)


class TestDeltaColumn(unittest.TestCase):
    def test_column_only_appears_when_a_baseline_is_given(self):
        # `status` is one-shot, so it has nothing to compare against.
        self.assertEqual(len(build_status_table(_DRIVES, _SENSORS, "t").columns), 3)
        self.assertEqual(len(build_status_table(_DRIVES, _SENSORS, "t", {}).columns), 4)

    def test_rise_fall_and_no_change_are_distinguished(self):
        self.assertIn("+3.0", format_delta(48.0, 45.0))
        self.assertIn("-2.0", format_delta(43.0, 45.0))
        self.assertIn("0.0", format_delta(45.0, 45.0))

    def test_rising_is_highlighted_since_that_is_the_concern(self):
        self.assertIn("red", format_delta(48.0, 45.0))
        self.assertIn("green", format_delta(43.0, 45.0))

    def test_missing_readings_have_no_delta(self):
        self.assertEqual(format_delta(None, 45.0), "-")
        self.assertEqual(format_delta(45.0, None), "-")

    def test_baseline_covers_drives_and_sensors(self):
        baseline = baseline_from(_DRIVES, _SENSORS)

        self.assertEqual(baseline["disk1"], 45.0)
        self.assertEqual(baseline["cpu"], 41.0)
        self.assertEqual(baseline["eth0"], 80.0)

    def test_baseline_skips_unreadable_sensors(self):
        # A sensor that failed to read must not be recorded as a 0 C baseline.
        drives = [DriveReading(drive="disk1", temperature_c=None, healthy=None)]
        self.assertEqual(baseline_from(drives, []), {})

    def test_sensor_absent_from_baseline_shows_no_delta(self):
        table = build_status_table(_DRIVES, _SENSORS, "t", {"disk1": 45.0})
        self.assertEqual(table.row_count, len(_DRIVES) + len(_SENSORS))


class TestSummaryLine(unittest.TestCase):
    def test_matches_the_expected_shape(self):
        line = format_summary_line("2026-07-31T15:00:00", _DRIVES, _SENSORS)

        self.assertEqual(
            line,
            "[2026-07-31T15:00:00] CPU: 41 C/105 F | System: 47 C/116 F | "
            "Disk1: 45 C/113 F | Disk2: 46 C/114 F | eth0: 80C",
        )

    def test_is_a_single_line_so_it_can_be_pasted(self):
        line = format_summary_line("2026-07-31T15:00:00", _DRIVES, _SENSORS)
        self.assertNotIn("\n", line)

    def test_cpu_and_system_lead_regardless_of_sensor_order(self):
        shuffled = list(reversed(_SENSORS))
        line = format_summary_line("ts", _DRIVES, shuffled)
        self.assertTrue(line.startswith("[ts] CPU: 41 C/105 F | System: 47 C/116 F | Disk1:"))

    def test_missing_readings_render_as_a_dash(self):
        drives = [DriveReading(drive="disk1", temperature_c=None, healthy=None)]
        sensors = [SensorReading(name="eth0", temperature_c=None)]
        line = format_summary_line("ts", drives, sensors)
        self.assertIn("Disk1: -", line)
        self.assertIn("eth0: -", line)

    def test_works_with_no_chassis_sensors(self):
        line = format_summary_line("ts", _DRIVES, [])
        self.assertEqual(line, "[ts] Disk1: 45 C/113 F | Disk2: 46 C/114 F")

    def test_fahrenheit_conversion_is_truncated_like_getsysinfo(self):
        # 41C -> 105.8F, which getsysinfo reports as 105.
        line = format_summary_line("ts", [], [SensorReading(name="cpu", temperature_c=41.0)])
        self.assertIn("CPU: 41 C/105 F", line)


if __name__ == "__main__":
    unittest.main()
