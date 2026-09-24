import tempfile
import unittest

from pathlib import Path
from unittest import mock

from nas_t import cpu_load
from nas_t.config import DeviceProfile
from nas_t.cpu_test import CpuTestPlan, run_cpu_test
from nas_t.runs import read_events
from nas_t.ssh_client import SshResult


def ok(stdout=""):
    return SshResult(exit_code=0, stdout=stdout, stderr="")


def device():
    return DeviceProfile(name="t", nas_ip="192.0.2.1", ssh_user="admin",
                         ssh_password_env="TEST_NAS_T_PASSWORD")  # pragma: allowlist secret


class TestCpuLoad(unittest.TestCase):
    def test_burn_script_avoids_missing_qts_tools(self):
        for missing in ("nohup", "timeout", "nproc", "pkill"):
            self.assertNotIn(missing, cpu_load._BURN_SCRIPT)
        self.assertIn("trap '' HUP", cpu_load._BURN_SCRIPT)

    def test_start_uploads_then_launches_detached_with_empty_stdin(self):
        with mock.patch("nas_t.cpu_load.run_remote_command", side_effect=[ok(), ok(), ok("1\n")]) as run:
            result = cpu_load.start_cpu_load(device(), 300, 3600, 4)
        self.assertTrue(result.ok)
        upload, launch, _ = run.call_args_list
        self.assertIn("cat >", upload.args[1])
        self.assertEqual(upload.kwargs["stdin_data"], cpu_load._BURN_SCRIPT)
        self.assertIn("300 3600 4", launch.args[1])
        self.assertTrue(launch.args[1].rstrip().endswith("&"))
        self.assertEqual(launch.kwargs["stdin_data"], "")

    def test_start_reports_when_script_not_running(self):
        with mock.patch("nas_t.cpu_load.run_remote_command", side_effect=[ok(), ok(), ok("0\n")]):
            self.assertFalse(cpu_load.start_cpu_load(device(), 1, 1, 1).ok)

    def test_stop_confirms_nothing_left(self):
        with mock.patch("nas_t.cpu_load.run_remote_command", return_value=ok("0 0\n")):
            self.assertTrue(cpu_load.stop_cpu_load(device()).ok)
        with mock.patch("nas_t.cpu_load.run_remote_command", return_value=ok("0 2\n")):
            self.assertFalse(cpu_load.stop_cpu_load(device()).ok)

    def test_poweroff_sends_password_on_stdin_only(self):
        with (
            mock.patch.dict("os.environ", {"TEST_NAS_T_PASSWORD": "pw!"}),  # pragma: allowlist secret
            mock.patch("nas_t.cpu_load.run_remote_command", return_value=ok()) as run,
        ):
            self.assertTrue(cpu_load.poweroff(device()).ok)
        self.assertNotIn("pw!", run.call_args.args[1])
        self.assertEqual(run.call_args.kwargs["stdin_data"], "pw!\n")

    def test_cpu_count(self):
        with mock.patch("nas_t.cpu_load.run_remote_command", return_value=ok("4\n")):
            self.assertEqual(cpu_load.cpu_count(device()), 4)


class TestCpuTest(unittest.TestCase):
    def test_short_run_writes_events_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("nas_t.cpu_test.cpu_load.cpu_count", return_value=4), \
                mock.patch("nas_t.cpu_test.cpu_load.start_cpu_load", return_value=cpu_load.LoadResult(True)), \
                mock.patch("nas_t.cpu_test.cpu_load.poweroff", return_value=cpu_load.LoadResult(True)) as off, \
                mock.patch("nas_t.cpu_test.monitor_loop") as loop:
            run_dir = Path(tmp) / "run"
            plan = CpuTestPlan(label="test build", idle_sec=0, load_sec=1, cooldown_sec=1, interval_sec=1,
                               shutdown_after=True)
            self.assertTrue(run_cpu_test(device(), run_dir, plan, report=lambda m: None))
            events = read_events(run_dir)
            self.assertEqual(events["label"], "test build")
            self.assertEqual(events["workers"], "4")
            loop.assert_called_once()
            off.assert_called_once()

    def test_does_not_log_if_load_fails_to_start(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("nas_t.cpu_test.cpu_load.cpu_count", return_value=4), \
                mock.patch("nas_t.cpu_test.cpu_load.start_cpu_load",
                           return_value=cpu_load.LoadResult(False, "nope")), \
                mock.patch("nas_t.cpu_test.monitor_loop") as loop:
            plan = CpuTestPlan(label="x", idle_sec=0, load_sec=1, cooldown_sec=0)
            self.assertFalse(run_cpu_test(device(), Path(tmp) / "run", plan, report=lambda m: None))
            loop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
