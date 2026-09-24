# AI-Assisted: Generated with assistance from AI tools.
"""Unit tests for persistent password storage, using a temp file rather than the real one."""

import os
import stat
import tempfile
import unittest

from pathlib import Path
from unittest import mock

from nas_t import credentials
from nas_t.config import DeviceProfile

_ENV = "TEST_NAS_T_STORE_PW"  # pragma: allowlist secret


class CredentialsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        path = Path(self.tmpdir.name) / "nas_t" / "credentials"

        patcher = mock.patch.object(credentials, "CREDENTIALS_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)

        # The module caches file contents; start each test from a clean slate.
        credentials._cache = None
        self.addCleanup(setattr, credentials, "_cache", None)

        env = mock.patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

        self.path = path


class TestStoreAndResolve(CredentialsTestCase):
    def test_stored_password_survives_a_cache_reset(self):
        credentials.store(_ENV, "hunter2")
        credentials._cache = None  # simulate a fresh process
        os.environ.pop(_ENV, None)
        self.assertEqual(credentials.resolve(_ENV), "hunter2")

    def test_environment_variable_wins_over_stored_value(self):
        credentials.store(_ENV, "from-disk")
        os.environ[_ENV] = "from-env"
        self.assertEqual(credentials.resolve(_ENV), "from-env")

    def test_resolve_returns_none_when_unknown(self):
        self.assertIsNone(credentials.resolve(_ENV))
        self.assertIsNone(credentials.resolve(None))

    @unittest.skipIf(os.name == "nt", "POSIX modes don't apply; the user-profile ACL restricts it on Windows")
    def test_file_is_not_readable_by_other_users(self):
        credentials.store(_ENV, "hunter2")
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode, 0o600, f"expected 0600, got {oct(mode)}")
        dir_mode = stat.S_IMODE(self.path.parent.stat().st_mode)
        self.assertEqual(dir_mode, 0o700, f"expected 0700, got {oct(dir_mode)}")

    def test_clear_forgets_the_password(self):
        credentials.store(_ENV, "hunter2")
        self.assertEqual(credentials.clear(_ENV), [_ENV])
        credentials._cache = None
        self.assertIsNone(credentials.resolve(_ENV))


class TestEnsureForDevice(CredentialsTestCase):
    def _device(self) -> DeviceProfile:
        return DeviceProfile(
            name="bench", nas_ip="192.0.2.1", ssh_user="admin", ssh_password_env=_ENV
        )

    def test_no_prompt_when_password_already_available(self):
        credentials.store(_ENV, "hunter2")
        with mock.patch.object(credentials, "getpass") as getpass:
            self.assertTrue(credentials.ensure_for_device(self._device()))
        getpass.assert_not_called()

    def test_prompts_and_stores_when_missing(self):
        with mock.patch.object(credentials, "getpass", return_value="typed-in"):
            self.assertTrue(credentials.ensure_for_device(self._device()))
        self.assertEqual(credentials.resolve(_ENV), "typed-in")

    def test_non_interactive_does_not_prompt(self):
        with mock.patch.object(credentials, "getpass") as getpass:
            self.assertFalse(credentials.ensure_for_device(self._device(), interactive=False))
        getpass.assert_not_called()

    def test_cancelled_prompt_reports_failure(self):
        with mock.patch.object(credentials, "getpass", side_effect=KeyboardInterrupt):
            self.assertFalse(credentials.ensure_for_device(self._device()))

    def test_device_profile_reads_the_stored_password(self):
        credentials.store(_ENV, "hunter2")
        device = self._device()
        self.assertEqual(device.ssh_password, "hunter2")
        # sudo falls back to the SSH password when no separate var is configured.
        self.assertEqual(device.sudo_password, "hunter2")
        self.assertEqual(device.missing_password_env_vars, [])


if __name__ == "__main__":
    unittest.main()
