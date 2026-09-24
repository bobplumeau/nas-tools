# AI-Assisted: Generated with assistance from AI tools.
"""Unit tests for the interactive shell's parsing, device context and error handling."""

import unittest

from unittest import mock

import main

from nas_t.shell import NasTShell


class ShellTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = NasTShell(main.app)
        # Avoid touching the real devices.yaml in these tests.
        patcher = mock.patch.object(
            NasTShell, "_available_devices", return_value=["bench_nas_01", "bench_nas_02"]
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # Credential prompting is covered in test_credentials.py; never block on input here.
        creds = mock.patch.object(NasTShell, "_ensure_credentials", return_value=True)
        creds.start()
        self.addCleanup(creds.stop)


class TestExitAndParsing(ShellTestCase):
    def test_exit_words_stop_the_loop(self):
        for word in ("exit", "quit", "q"):
            self.assertFalse(self.shell.run_line(word), word)

    def test_blank_line_is_a_no_op(self):
        with mock.patch.object(self.shell, "_dispatch") as dispatch:
            self.assertTrue(self.shell.run_line("   "))
        dispatch.assert_not_called()

    def test_unbalanced_quotes_do_not_crash_the_shell(self):
        with mock.patch.object(self.shell, "_dispatch") as dispatch:
            self.assertTrue(self.shell.run_line('status --device "unterminated'))
        dispatch.assert_not_called()


class TestDeviceContext(ShellTestCase):
    def test_use_selects_a_known_device(self):
        self.shell.run_line("use bench_nas_01")
        self.assertEqual(self.shell.device, "bench_nas_01")

    def test_use_rejects_an_unknown_device(self):
        self.shell.run_line("use nope")
        self.assertIsNone(self.shell.device)

    def test_use_can_change_the_selected_device(self):
        self.shell.run_line("use bench_nas_01")
        self.shell.run_line("use bench_nas_02")
        self.assertEqual(self.shell.device, "bench_nas_02")

    def test_selected_device_is_injected_into_commands(self):
        self.shell.run_line("use bench_nas_01")
        with mock.patch.object(self.shell, "_dispatch") as dispatch:
            self.shell.run_line("status")
        dispatch.assert_called_once_with(["status", "--device", "bench_nas_01"])

    def test_explicit_device_wins_over_the_selected_one(self):
        self.shell.run_line("use bench_nas_01")
        with mock.patch.object(self.shell, "_dispatch") as dispatch:
            self.shell.run_line("status --device bench_nas_02")
        dispatch.assert_called_once_with(["status", "--device", "bench_nas_02"])

    def test_no_device_injected_for_commands_that_lack_the_option(self):
        # `load` drives a local NFS mount and takes no --device.
        self.shell.run_line("use bench_nas_01")
        with mock.patch.object(self.shell, "_dispatch") as dispatch:
            self.shell.run_line("load --mount-path /mnt/x --sample-mcap s.mcap")
        self.assertNotIn("--device", dispatch.call_args[0][0])

    def test_nothing_injected_when_no_device_selected(self):
        with mock.patch.object(self.shell, "_dispatch") as dispatch:
            self.shell.run_line("status")
        dispatch.assert_called_once_with(["status"])


class TestDispatchResilience(ShellTestCase):
    def test_system_exit_from_usage_errors_is_swallowed(self):
        with mock.patch.object(self.shell.command, "__call__", side_effect=SystemExit(2)):
            self.shell._dispatch(["status"])  # must not raise

    def test_config_errors_are_reported_without_a_traceback(self):
        error = KeyError("Unknown device 'x'. Available devices: bench_nas_01")
        with (
            mock.patch.object(self.shell.command, "__call__", side_effect=error),
            mock.patch("nas_t.shell.traceback.print_exc") as print_exc,
        ):
            self.shell._dispatch(["status", "--device", "x"])
        print_exc.assert_not_called()

    def test_keyboard_interrupt_returns_to_the_prompt(self):
        with mock.patch.object(self.shell.command, "__call__", side_effect=KeyboardInterrupt):
            self.shell._dispatch(["monitor"])  # must not propagate


class TestCompletion(ShellTestCase):
    def test_completes_command_names(self):
        with mock.patch("nas_t.shell.readline.get_line_buffer", return_value="mon"):
            self.assertEqual(self.shell._complete("mon", 0), "monitor")

    def test_completes_device_names_after_use(self):
        with mock.patch("nas_t.shell.readline.get_line_buffer", return_value="use bench"):
            self.assertEqual(self.shell._complete("bench", 0), "bench_nas_01")

    def test_returns_none_when_exhausted(self):
        with mock.patch("nas_t.shell.readline.get_line_buffer", return_value="mon"):
            self.assertIsNone(self.shell._complete("mon", 99))


if __name__ == "__main__":
    unittest.main()
