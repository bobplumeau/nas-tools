# AI-Assisted: Generated with assistance from AI tools.
"""Unit tests for batched multi-drive smartctl parsing, which run without a real NAS."""

import unittest

from unittest import mock

from nas_t import smart_monitor
from nas_t.config import DeviceProfile
from nas_t.ssh_client import SshResult

# Two drives' worth of the delimited output produced by the single batched poll command.
_POLL_OUTPUT = """@@NAS_T_DRIVE@@ /dev/sda
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
194 Temperature_Celsius     0x0022   119   100   000    Old_age   Always       -       34
@@NAS_T_HEALTH@@
SMART overall-health self-assessment test result: PASSED
@@NAS_T_DRIVE@@ /dev/sdb
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
194 Temperature_Celsius     0x0022   112   100   000    Old_age   Always       -       41
@@NAS_T_HEALTH@@
SMART overall-health self-assessment test result: FAILED
"""

# vendor is pinned to a non-qnap value so these exercise the smartctl backend.
_DEVICE = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin", vendor="generic")


class TestParsePollOutput(unittest.TestCase):
    def test_parses_each_drive_temp_and_health(self):
        readings = smart_monitor.parse_poll_output(_POLL_OUTPUT)

        self.assertEqual(len(readings), 2)
        self.assertEqual(readings[0].drive, "/dev/sda")
        self.assertEqual(readings[0].temperature_c, 34.0)
        self.assertTrue(readings[0].healthy)
        self.assertEqual(readings[1].drive, "/dev/sdb")
        self.assertEqual(readings[1].temperature_c, 41.0)
        self.assertFalse(readings[1].healthy)

    def test_health_marker_does_not_leak_into_temperature_section(self):
        # A FAILED health line must not be mistaken for the other drive's attributes.
        readings = smart_monitor.parse_poll_output(_POLL_OUTPUT)
        self.assertNotEqual(readings[0].healthy, readings[1].healthy)

    def test_empty_output_yields_no_readings(self):
        self.assertEqual(smart_monitor.parse_poll_output(""), [])

    def test_raw_value_with_trailing_context_is_parsed(self):
        # Some drives report RAW_VALUE as "31 (Min/Max 20/45)".
        output = (
            "@@NAS_T_DRIVE@@ /dev/sda\n"
            "194 Temperature_Celsius     0x0022   119   100   000    Old_age   "
            "Always       -       31 (Min/Max 20/45)\n"
            "@@NAS_T_HEALTH@@\nPASSED\n"
        )
        self.assertEqual(smart_monitor.parse_poll_output(output)[0].temperature_c, 31.0)

    def test_airflow_temperature_attribute_is_parsed(self):
        output = (
            "@@NAS_T_DRIVE@@ /dev/sda\n"
            "190 Airflow_Temperature_Cel 0x0022   070   050   045    Old_age   "
            "Always       -       30\n"
            "@@NAS_T_HEALTH@@\nPASSED\n"
        )
        self.assertEqual(smart_monitor.parse_poll_output(output)[0].temperature_c, 30.0)

    def test_nvme_flat_temperature_format_is_parsed(self):
        output = (
            "@@NAS_T_DRIVE@@ /dev/nvme0\n"
            "SMART/Health Information (NVMe Log 0x02)\n"
            "Temperature:                        38 Celsius\n"
            "@@NAS_T_HEALTH@@\nPASSED\n"
        )
        self.assertEqual(smart_monitor.parse_poll_output(output)[0].temperature_c, 38.0)

    def test_missing_temperature_attribute_is_none(self):
        output = "@@NAS_T_DRIVE@@ /dev/sda\nno attributes here\n@@NAS_T_HEALTH@@\nPASSED\n"
        readings = smart_monitor.parse_poll_output(output)
        self.assertIsNone(readings[0].temperature_c)
        self.assertTrue(readings[0].healthy)


_QNAP_OUTPUT = """@@NAS_T_QNAP@@ 1|40 C/104 F|GOOD
@@NAS_T_QNAP@@ 2|42 C/107 F|GOOD
@@NAS_T_QNAP@@ 3|0 C/32 F|--
@@NAS_T_QNAP@@ 4|41 C/105 F|ABNORMAL
"""


class TestParseQnapOutput(unittest.TestCase):
    def test_parses_bay_temperature_and_health(self):
        readings = smart_monitor.parse_qnap_poll_output(_QNAP_OUTPUT)

        self.assertEqual([r.drive for r in readings], ["disk1", "disk2", "disk3", "disk4"])
        self.assertEqual(readings[0].temperature_c, 40.0)
        self.assertTrue(readings[0].healthy)
        self.assertEqual(readings[1].temperature_c, 42.0)

    def test_unreported_health_is_none_not_false(self):
        # "--" means the unit didn't report, which must not look like a failing drive.
        readings = smart_monitor.parse_qnap_poll_output(_QNAP_OUTPUT)
        self.assertIsNone(readings[2].healthy)

    def test_non_good_health_is_unhealthy(self):
        readings = smart_monitor.parse_qnap_poll_output(_QNAP_OUTPUT)
        self.assertFalse(readings[3].healthy)

    def test_ignores_unrelated_lines(self):
        noisy = "sudo: a password is required\n" + _QNAP_OUTPUT
        self.assertEqual(len(smart_monitor.parse_qnap_poll_output(noisy)), 4)

    def test_qnap_vendor_dispatches_to_getsysinfo(self):
        device = DeviceProfile(
            name="test",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            vendor="qnap",
            ssh_password_env="TEST_PW",  # pragma: allowlist secret
        )
        with (
            mock.patch.dict("os.environ", {"TEST_PW": "secret"}),  # pragma: allowlist secret
            mock.patch.object(
                smart_monitor,
                "run_remote_command",
                return_value=SshResult(exit_code=0, stdout=_QNAP_OUTPUT, stderr=""),
            ) as mock_run,
        ):
            readings = smart_monitor.poll_all_drives(device)

        self.assertEqual(len(readings), 4)
        # The sudo password must be delivered on stdin, never inside the command string.
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs["stdin_data"], "secret\n")
        self.assertNotIn("secret", mock_run.call_args[0][1])


_SENSOR_OUTPUT = """@@NAS_T_SYS@@ cpu|38 C/100 F
@@NAS_T_SYS@@ system|45 C/113 F
@@NAS_T_HWMON@@ coretemp|42000
@@NAS_T_HWMON@@ eth0|79000
@@NAS_T_HWMON@@ eth1|69000
"""


class TestParseSensorOutput(unittest.TestCase):
    def test_getsysinfo_and_hwmon_sensors_are_parsed(self):
        sensors = smart_monitor.parse_sensor_output(_SENSOR_OUTPUT)

        self.assertEqual(
            [(s.name, s.temperature_c) for s in sensors],
            [("cpu", 38.0), ("system", 45.0), ("coretemp", 42.0), ("eth0", 79.0), ("eth1", 69.0)],
        )

    def test_hwmon_millidegrees_are_converted(self):
        sensors = smart_monitor.parse_sensor_output("@@NAS_T_HWMON@@ eth0|79000\n")
        self.assertEqual(sensors[0].temperature_c, 79.0)

    def test_drive_lines_are_not_treated_as_sensors(self):
        self.assertEqual(smart_monitor.parse_sensor_output(_QNAP_OUTPUT), [])

    def test_sensor_lines_are_not_treated_as_drives(self):
        self.assertEqual(smart_monitor.parse_qnap_poll_output(_SENSOR_OUTPUT), [])

    def test_unparseable_values_become_none(self):
        sensors = smart_monitor.parse_sensor_output(
            "@@NAS_T_HWMON@@ eth0|junk\n@@NAS_T_SYS@@ cpu|--\n"
        )
        self.assertEqual([s.temperature_c for s in sensors], [None, None])

    def test_drives_and_sensors_come_from_one_round_trip(self):
        device = DeviceProfile(
            name="test",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            vendor="qnap",
            ssh_password_env="TEST_PW",  # pragma: allowlist secret
        )
        combined = _QNAP_OUTPUT + _SENSOR_OUTPUT
        env = {"TEST_PW": "secret"}  # pragma: allowlist secret
        with (
            mock.patch.dict("os.environ", env),
            mock.patch.object(
                smart_monitor,
                "run_remote_command",
                return_value=SshResult(exit_code=0, stdout=combined, stderr=""),
            ) as run,
        ):
            drives, sensors = smart_monitor.poll_all(device)

        self.assertEqual(run.call_count, 1, "sensors must not cost an extra SSH call")
        self.assertEqual(len(drives), 4)
        self.assertEqual(len(sensors), 5)


class TestPollAllDrives(unittest.TestCase):
    def test_uses_a_single_ssh_round_trip(self):
        with mock.patch.object(
            smart_monitor,
            "run_remote_command",
            return_value=SshResult(exit_code=0, stdout=_POLL_OUTPUT, stderr=""),
        ) as mock_run:
            readings = smart_monitor.poll_all_drives(_DEVICE)

        self.assertEqual(mock_run.call_count, 1, "all drives must be polled in one SSH call")
        self.assertEqual(len(readings), 2)

    def test_missing_sudo_password_explains_itself(self):
        # An empty table with no explanation is the worst outcome here.
        device = DeviceProfile(
            name="bench_nas_01",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            vendor="qnap",
            ssh_password_env="UNSET_NAS_T_PW",  # pragma: allowlist secret
        )
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(smart_monitor, "run_remote_command") as run,
            mock.patch("nas_t.smart_monitor.print") as printer,
        ):
            self.assertEqual(smart_monitor.poll_all_drives(device), [])

        run.assert_not_called()
        message = " ".join(str(c) for c in printer.call_args_list)
        self.assertIn("UNSET_NAS_T_PW", message)

    def test_failed_poll_explains_itself(self):
        # A silent empty table gives no clue whether the NAS is down or misconfigured.
        device = DeviceProfile(
            name="bench_nas_01",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            vendor="qnap",
            ssh_password_env="TEST_PW",  # pragma: allowlist secret
        )
        env = {"TEST_PW": "secret"}  # pragma: allowlist secret
        with (
            mock.patch.dict("os.environ", env),
            mock.patch.object(
                smart_monitor,
                "run_remote_command",
                return_value=SshResult(exit_code=255, stdout="", stderr="Connection closed"),
            ),
            mock.patch("nas_t.smart_monitor.print") as printer,
        ):
            self.assertEqual(smart_monitor.poll_all(device), ([], []))

        self.assertIn("Connection closed", " ".join(str(c) for c in printer.call_args_list))

    def test_benign_ssh_warnings_are_not_reported_as_the_failure_reason(self):
        # These warnings appear on successful connections too; reporting one as "the
        # reason" sends you chasing the wrong problem.
        noisy = (
            "Warning: Permanently added '192.0.2.11' (RSA) to the list of known hosts.\n"
            "Connection reset by peer\n"
            "Could not chdir to home directory /share/homes/admin: No such file\n"
        )
        result = SshResult(exit_code=255, stdout="", stderr=noisy)
        self.assertEqual(smart_monitor._failure_reason(result), "Connection reset by peer")

    def test_falls_back_to_exit_code_when_stderr_is_all_noise(self):
        result = SshResult(exit_code=255, stdout="", stderr="Could not chdir to home directory\n")
        self.assertEqual(smart_monitor._failure_reason(result), "exit code 255")

    def test_failed_command_returns_no_readings(self):
        with mock.patch.object(
            smart_monitor,
            "run_remote_command",
            return_value=SshResult(exit_code=255, stdout="", stderr="boom"),
        ):
            self.assertEqual(smart_monitor.poll_all_drives(_DEVICE), [])


if __name__ == "__main__":
    unittest.main()
