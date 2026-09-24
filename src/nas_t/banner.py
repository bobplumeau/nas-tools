# AI-Assisted: Generated with assistance from AI tools.
"""ASCII art banner shown when the nas_t CLI launches."""

from rich import print

_BANNER = r"""
 _   _   _   ____        _____
| \ | | / \ / ___|      |_   _|
|  \| |/ _ \ \___ \       | |
| |\  / ___ \ ___)  _____ | |
|_| \/_/   \_\____/|_____||_|
"""


_shown = False


def print_banner(force: bool = False) -> None:
    """Prints the banner at most once per process.

    The shell shows it on entry and the help page shows it too; without this guard,
    opening help from inside the shell would repeat it.
    """
    global _shown
    if _shown and not force:
        return
    _shown = True
    print(f"[bold cyan]{_BANNER}[/bold cyan]")
    print("[dim]NAS testing CLI[/dim]\n")
