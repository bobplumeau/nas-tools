# AI-Assisted: Generated with assistance from AI tools.
"""Unit tests for SSH argument/env construction, which run without a real NAS."""

import unittest

from unittest import mock

from nas_t.config import DeviceProfile
from nas_t.ssh_client import resolve_target_ip, run_remote_command


class TestRunRemoteCommand(unittest.TestCase):
    """Linux behaviour (sshpass + ControlMaster), regardless of the host running the tests."""

    windows = False

    def _run(self, device: DeviceProfile):
        with (
            mock.patch("nas_t.ssh_client.subprocess.run") as mock_run,
            mock.patch("nas_t.ssh_client._use_askpass", return_value=self.windows),
            mock.patch("nas_t.ssh_client._supports_multiplexing", return_value=not self.windows),
        ):
            mock_run.return_value = mock.Mock(returncode=0, stdout="ok\n", stderr="")
            run_remote_command(device, "echo ok")
            return mock_run.call_args

    def test_no_password_uses_plain_ssh(self):
        device = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin")
        args, kwargs = self._run(device)
        cmd = args[0]
        self.assertEqual(cmd[0], "ssh")
        self.assertNotIn("sshpass", cmd)
        self.assertIsNone(kwargs["env"])

    def test_jump_host_adds_dash_j(self):
        device = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin", jump_host="jumphost")
        args, _ = self._run(device)
        cmd = args[0]
        self.assertIn("-J", cmd)
        self.assertIn("jumphost", cmd)

    def test_password_uses_sshpass_with_env_var(self):
        device = DeviceProfile(
            name="test",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            ssh_password_env="TEST_NAS_T_PASSWORD",  # pragma: allowlist secret
        )
        env = {"TEST_NAS_T_PASSWORD": "secret"}  # pragma: allowlist secret
        with mock.patch.dict("os.environ", env):
            args, kwargs = self._run(device)
        cmd = args[0]
        self.assertEqual(cmd[0], "sshpass")
        self.assertEqual(cmd[1], "-e")
        # Password must never appear on the command line itself.
        self.assertNotIn("secret", cmd)
        self.assertEqual(kwargs["env"]["SSHPASS"], "secret")

    def test_batch_mode_set_when_no_password_configured(self):
        # Otherwise ssh prompts interactively, once per command, inside the REPL.
        device = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin")
        args, _ = self._run(device)
        self.assertIn("BatchMode=yes", " ".join(args[0]))

    def test_batch_mode_not_set_when_password_available(self):
        device = DeviceProfile(
            name="test",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            ssh_password_env="TEST_NAS_T_PASSWORD",  # pragma: allowlist secret
        )
        env = {"TEST_NAS_T_PASSWORD": "secret"}  # pragma: allowlist secret
        with mock.patch.dict("os.environ", env):
            args, _ = self._run(device)
        self.assertNotIn("BatchMode=yes", " ".join(args[0]))

    def test_uses_connection_multiplexing(self):
        device = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin")
        args, _ = self._run(device)
        joined = " ".join(args[0])
        self.assertIn("ControlMaster=auto", joined)
        self.assertIn("ControlPath=", joined)
        self.assertIn("ControlPersist=", joined)


class TestRunRemoteCommandWindows(unittest.TestCase):
    """Windows OpenSSH: no sshpass and no unix sockets."""

    def _run(self, device: DeviceProfile):
        with (
            mock.patch("nas_t.ssh_client.subprocess.run") as mock_run,
            mock.patch("nas_t.ssh_client._use_askpass", return_value=True),
            mock.patch("nas_t.ssh_client._supports_multiplexing", return_value=False),
        ):
            mock_run.return_value = mock.Mock(returncode=0, stdout="ok\n", stderr="")
            run_remote_command(device, "echo ok")
            return mock_run.call_args

    def _device(self):
        return DeviceProfile(
            name="test",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            ssh_password_env="TEST_NAS_T_PASSWORD",  # pragma: allowlist secret
        )

    def test_password_goes_through_askpass_env_not_disk_or_argv(self):
        with mock.patch.dict("os.environ", {"TEST_NAS_T_PASSWORD": "s3cr3t!&%"}):  # pragma: allowlist secret
            args, kwargs = self._run(self._device())
        cmd = args[0]
        self.assertEqual(cmd[0], "ssh")
        self.assertNotIn("sshpass", cmd)
        self.assertNotIn("s3cr3t!&%", " ".join(cmd))
        env = kwargs["env"]
        self.assertEqual(env["NAS_T_ASKPASS_VALUE"], "s3cr3t!&%")
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
        with open(env["SSH_ASKPASS"]) as f:
            self.assertNotIn("s3cr3t", f.read())

    def test_no_multiplexing(self):
        args, _ = self._run(self._device())
        self.assertNotIn("ControlMaster=auto", " ".join(args[0]))


class TestCandidateIpProbing(unittest.TestCase):
    def _device(self) -> DeviceProfile:
        return DeviceProfile(name="test", nas_ip=["192.0.2.10", "192.0.2.11"], ssh_user="admin")

    def test_falls_through_to_second_candidate_when_first_is_down(self):
        device = self._device()
        results = [
            mock.Mock(returncode=255, stdout="", stderr="No route to host"),
            mock.Mock(returncode=0, stdout="ok\n", stderr=""),
        ]
        with mock.patch("nas_t.ssh_client.subprocess.run", side_effect=results) as mock_run:
            self.assertEqual(resolve_target_ip(device), "192.0.2.11")

        self.assertEqual(mock_run.call_count, 2)
        # Both candidates should have been attempted, in order.
        self.assertIn("admin@192.0.2.10", mock_run.call_args_list[0][0][0])
        self.assertIn("admin@192.0.2.11", mock_run.call_args_list[1][0][0])

    def test_resolved_ip_is_cached_for_later_commands(self):
        device = self._device()
        ok = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        down = mock.Mock(returncode=255, stdout="", stderr="No route to host")

        with mock.patch("nas_t.ssh_client.subprocess.run", side_effect=[down, ok]):
            resolve_target_ip(device)
        self.assertEqual(device.active_ip, "192.0.2.11")

        # A follow-up command must not re-probe the dead address.
        with mock.patch("nas_t.ssh_client.subprocess.run", return_value=ok) as mock_run:
            run_remote_command(device, "echo hi")
        self.assertEqual(mock_run.call_count, 1)
        self.assertIn("admin@192.0.2.11", mock_run.call_args[0][0])

    def test_returns_none_when_no_candidate_responds(self):
        device = self._device()
        down = mock.Mock(returncode=255, stdout="", stderr="No route to host")
        with mock.patch("nas_t.ssh_client.subprocess.run", return_value=down):
            self.assertIsNone(resolve_target_ip(device))
        self.assertIsNone(device.active_ip)

    def test_missing_sshpass_reports_actionable_error(self):
        device = DeviceProfile(
            name="test",
            nas_ip="192.0.2.1",
            ssh_user="admin",
            ssh_password_env="TEST_NAS_T_PASSWORD",  # pragma: allowlist secret
        )
        env = {"TEST_NAS_T_PASSWORD": "secret"}  # pragma: allowlist secret
        with (
            mock.patch.dict("os.environ", env),
            mock.patch(
                "nas_t.ssh_client.subprocess.run",
                side_effect=FileNotFoundError(2, "No such file", "sshpass"),
            ),
        ):
            result = run_remote_command(device, "echo hi")

        # The actionable hint must survive being wrapped by the candidate-probe failure.
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("apt install sshpass", result.stderr)

    def test_single_string_ip_still_works(self):
        device = DeviceProfile(name="test", nas_ip="192.0.2.1", ssh_user="admin")
        self.assertEqual(device.candidate_ips, ["192.0.2.1"])
        self.assertEqual(device.target_ip, "192.0.2.1")


if __name__ == "__main__":
    unittest.main()
