# AI-Assisted: Generated with assistance from AI tools.
"""Unit tests for the polling loop, in particular running with and without CSV output."""

import tempfile
import threading
import unittest

from pathlib import Path
from typing import Callable, Optional
from unittest import mock

from nas_t import monitor
from nas_t.config import DeviceProfile
from nas_t.smart_monitor import DriveReading, SensorReading

_DEVICE = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin")
_READINGS = [DriveReading(drive="disk1", temperature_c=40.0, healthy=True)]
_SENSORS = [SensorReading(name="cpu", temperature_c=38.0)]


class MonitorLoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name)

        poll = mock.patch.object(monitor, "poll_all", return_value=(_READINGS, _SENSORS))
        poll.start()
        self.addCleanup(poll.stop)

    def _run_one_poll(self, smart_csv: Optional[Path], inspect: Optional[Callable] = None) -> list:
        """Runs exactly one poll, stopping the loop from the sample callback."""
        stop_event = threading.Event()
        samples = []

        def on_sample(sample):
            samples.append(sample)
            if inspect is not None:
                inspect(sample)
            stop_event.set()

        monitor.monitor_loop(
            _DEVICE,
            smart_csv=smart_csv,
            interval_sec=0,
            stop_event=stop_event,
            on_sample=on_sample,
        )
        return samples


class TestWithoutCsv(MonitorLoopTestCase):
    def test_live_monitor_polls_without_writing_any_file(self):
        samples = self._run_one_poll(smart_csv=None)

        self.assertEqual(len(samples), 1, "the loop should still poll")
        self.assertEqual(list(self.tmp.iterdir()), [], "no files should be created")

    def test_samples_are_delivered_to_the_callback(self):
        samples = self._run_one_poll(smart_csv=None)

        self.assertEqual(samples[0].drive_readings, _READINGS)
        self.assertEqual(samples[0].sensor_readings, _SENSORS)
        self.assertIsNone(samples[0].network, "no network sampling without a network CSV")


class TestWithCsv(MonitorLoopTestCase):
    def test_log_writes_header_and_rows(self):
        csv_path = self.tmp / "nested" / "smart.csv"

        self._run_one_poll(smart_csv=csv_path)

        lines = csv_path.read_text().strip().splitlines()
        self.assertEqual(lines[0], "timestamp,sensor,temperature_c,healthy")
        self.assertIn("disk1,40.0,True", lines[1])
        # Chassis sensors share the file, with the drive-only health column blank.
        self.assertIn("cpu,38.0,", lines[2])

    def test_rows_are_flushed_before_the_loop_ends(self):
        # An interrupted run must not lose a poll that already completed.
        csv_path = self.tmp / "smart.csv"

        def assert_already_written(_sample):
            self.assertIn("disk1", csv_path.read_text())

        self._run_one_poll(smart_csv=csv_path, inspect=assert_already_written)


if __name__ == "__main__":
    unittest.main()
