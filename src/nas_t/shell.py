# AI-Assisted: Generated with assistance from AI tools.
"""Interactive shell (REPL) for NAS_T.

Commands are dispatched into the same Typer app used non-interactively, so there is
exactly one definition of every command. Staying in one process across commands also
keeps the multiplexed SSH master connection warm between polls.

click-repl is deliberately not used: typer 0.27 vendors click privately as
``typer._click``, so tooling that expects real ``click.Group`` objects can't drive it.
"""

import atexit
import readline
import shlex
import traceback

from pathlib import Path
from typing import Optional

from rich import print

_PROMPT_NAME = "nas_t"
_HISTORY_PATH = Path.home() / ".config" / "nas_t" / "history"
_HISTORY_LENGTH = 1000
_EXIT_WORDS = ("exit", "quit", "q")


class NasTShell:
    """Stateful REPL wrapper around the Typer app."""

    def __init__(self, app) -> None:
        from typer.main import get_command

        self.command = get_command(app)
        self.device: Optional[str] = None

    # -- device context ---------------------------------------------------------

    def _available_devices(self) -> list[str]:
        from nas_t.config import load_devices

        try:
            return sorted(load_devices())
        except Exception:
            return []

    def _set_device(self, name: str) -> None:
        available = self._available_devices()
        if available and name not in available:
            print(f"[red]Unknown device '{name}'. Available: {', '.join(available)}[/red]")
            return
        self.device = name
        print(f"[green]Using device: {name}[/green]")
        self._warn_about_missing_passwords(name)

    def _autoselect_device(self) -> None:
        """Selects a device on entry so a session is usable without typing `use` first."""
        available = self._available_devices()
        if not available:
            print(
                "[yellow]No devices found. Copy devices.example.yaml to devices.yaml "
                "and fill in your NAS details.[/yellow]"
            )
            return

        self._set_device(available[0])
        if len(available) > 1:
            others = ", ".join(available[1:])
            print(f"[dim]Other devices: {others}. Switch with 'use <device>'.[/dim]")

    def _warn_about_missing_passwords(self, name: str) -> None:
        """Prompts for any password this device needs, rather than failing later."""
        self._ensure_credentials(name)

    def _ensure_credentials(self, name: str) -> bool:
        """Makes sure the device's passwords are available, prompting once if needed."""
        from nas_t.config import get_device
        from nas_t.credentials import ensure_for_device

        try:
            device = get_device(None, name)
        except Exception:
            return True  # Let the command itself report the config problem.
        return ensure_for_device(device, interactive=True)

    def _supports_device_option(self, command_name: str) -> bool:
        """True if the subcommand takes --device, so it can inherit the sticky device."""
        subcommand = getattr(self.command, "commands", {}).get(command_name)
        if subcommand is None:
            return False
        return any(param.name == "device" for param in subcommand.params)

    # -- built-ins --------------------------------------------------------------

    def _print_help(self) -> None:
        print(
            "\n[bold]Shell commands[/bold]\n"
            "  [cyan]use <device>[/cyan]    select the device used by later commands\n"
            "  [cyan]device[/cyan]          show the currently selected device\n"
            "  [cyan]devices[/cyan]         list devices from devices.yaml\n"
            # The square brackets must be escaped or rich parses them as a markup tag.
            "  [cyan]login \\[device][/cyan]  set or replace the saved password\n"
            "  [cyan]logout[/cyan]          forget all saved passwords\n"
            "  [cyan]help[/cyan]            show this help, plus the NAS_T commands below\n"
            "  [cyan]exit[/cyan] / Ctrl+D   leave the shell\n"
            "\n[dim]Any NAS_T command also works here, e.g. "
            "'status', 'monitor' (live view) or 'log --output run.csv'.\n"
            "With a device selected you can omit --device. Ctrl+C stops a running "
            "command and returns to the prompt.[/dim]\n"
        )
        self._dispatch(["--help"])

    def _handle_builtin(self, parts: list[str]) -> bool:
        """Runs shell-only commands. Returns True if the input was handled here."""
        verb, args = parts[0], parts[1:]

        if verb in ("use", "device") and args:
            self._set_device(args[0])
            return True
        if verb == "use":
            print("[yellow]Usage: use <device>. Run 'devices' to list them.[/yellow]")
            return True
        if verb == "shell":
            print("[yellow]Already in the NAS_T shell.[/yellow]")
            return True
        if verb == "login":
            self._login(args[0] if args else self.device)
            return True
        if verb == "logout":
            self._logout()
            return True
        if verb == "device":
            print(self.device or "[yellow]No device selected. Use 'use <name>'.[/yellow]")
            return True
        if verb == "devices":
            available = self._available_devices()
            if not available:
                print("[yellow]No devices found. Check devices.yaml.[/yellow]")
            for name in available:
                marker = " [green](selected)[/green]" if name == self.device else ""
                print(f"  {name}{marker}")
            return True
        if verb in ("help", "?"):
            self._print_help()
            return True
        return False

    def _login(self, name: Optional[str]) -> None:
        """Sets or replaces the stored password for a device (e.g. after a typo)."""
        from nas_t.config import get_device
        from nas_t.credentials import prompt_and_store

        if not name:
            print("[yellow]Select a device first with 'use <device>', or: login <device>[/yellow]")
            return
        try:
            device = get_device(None, name)
        except Exception as exc:
            print(f"[red]{exc.args[0] if exc.args else exc}[/red]")
            return

        env_var = device.ssh_password_env
        if not env_var:
            print(f"[yellow]{name} has no ssh_password_env set in devices.yaml.[/yellow]")
            return
        prompt_and_store(env_var, name)

    def _logout(self) -> None:
        """Forgets every stored password."""
        from nas_t.credentials import clear

        removed = clear()
        if removed:
            print(f"[green]Forgot stored password(s): {', '.join(removed)}[/green]")
        else:
            print("[yellow]No stored passwords.[/yellow]")

    # -- dispatch ---------------------------------------------------------------

    def _dispatch(self, argv: list[str]) -> None:
        try:
            self.command(argv, prog_name=_PROMPT_NAME)
        except SystemExit:
            # Typer/click exits after --help and usage errors; it already printed output.
            pass
        except KeyboardInterrupt:
            print("\n[yellow]Interrupted.[/yellow]")
        except (FileNotFoundError, KeyError) as exc:
            # Config problems (missing devices.yaml, unknown device) shouldn't end the shell.
            print(f"[red]{exc.args[0] if exc.args else exc}[/red]")
        except Exception:
            traceback.print_exc()

    def run_line(self, line: str) -> bool:
        """Handles one input line. Returns False when the shell should exit."""
        line = line.strip()
        if not line:
            return True
        if line in _EXIT_WORDS:
            return False

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(f"[red]Could not parse input: {exc}[/red]")
            return True

        if self._handle_builtin(parts):
            return True

        # Let a selected device stand in for an explicit --device.
        if self.device and "--device" not in parts and self._supports_device_option(parts[0]):
            parts += ["--device", self.device]

        # Prompt for any missing password before the command runs. Doing it here (rather
        # than deep in the SSH layer) keeps prompts on the main thread, where commands
        # like `test` spawn background monitoring threads that must not block on input.
        if "--device" in parts:
            target = parts[parts.index("--device") + 1]
            if not self._ensure_credentials(target):
                return True

        self._dispatch(parts)
        return True

    # -- readline ---------------------------------------------------------------

    def _completions(self) -> list[str]:
        names = list(getattr(self.command, "commands", {}))
        builtins = ["use", "device", "devices", "login", "logout", "help", "exit", "quit"]
        return sorted(names + builtins)

    def _complete(self, text: str, state: int) -> Optional[str]:
        buffer = readline.get_line_buffer().lstrip()
        # After "use ", complete device names instead of command names.
        pool = self._available_devices() if buffer.startswith("use ") else self._completions()
        matches = [c for c in pool if c.startswith(text)]
        return matches[state] if state < len(matches) else None

    def _setup_readline(self) -> None:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            readline.read_history_file(_HISTORY_PATH)
        except OSError:
            pass
        readline.set_history_length(_HISTORY_LENGTH)
        atexit.register(self._save_history)

        readline.set_completer(self._complete)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")

    def _save_history(self) -> None:
        try:
            readline.write_history_file(_HISTORY_PATH)
        except OSError:
            pass

    # -- main loop --------------------------------------------------------------

    def _prompt(self) -> str:
        return f"{_PROMPT_NAME} [{self.device}]> " if self.device else f"{_PROMPT_NAME}> "

    def run(self, device: Optional[str] = None) -> None:
        from nas_t.banner import print_banner

        print_banner()
        self._setup_readline()

        # Device first, so "Using device: ..." sits directly under the banner rather than
        # being pushed off-screen by the help below it.
        if device:
            self._set_device(device)
        else:
            self._autoselect_device()

        self._print_help()
        print("[dim]Type 'help' to see this again, 'exit' to quit.[/dim]\n")

        while True:
            try:
                line = input(self._prompt())
            except KeyboardInterrupt:
                # Ctrl+C at the prompt clears the line rather than leaving the shell.
                print()
                continue
            except EOFError:
                print()
                break

            if not self.run_line(line):
                break

        self._shutdown()

    def _shutdown(self) -> None:
        """Closes any multiplexed SSH master connection opened during the session."""
        from nas_t.config import get_device
        from nas_t.ssh_client import close_connection

        if self.device is not None:
            try:
                close_connection(get_device(None, self.device))
            except Exception:
                pass
        print("[dim]Goodbye.[/dim]")


def run_shell(app, device: Optional[str] = None) -> None:
    NasTShell(app).run(device=device)
