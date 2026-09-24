# Agent notes for nas-tools

Shared by Bob Plumeau and Casey Matalone. When asked to "refresh", "update" or "change"
the test app, follow the skill at `.devin/skills/nas-t/SKILL.md`.

## Layout

- `src/main.py` - Typer CLI; every command lives here and imports its module lazily.
- `src/nas_t/` - implementation. `ssh_client.py` (all SSH, Windows + Linux auth),
  `smart_monitor.py` (QNAP/smartctl polling), `monitor.py` (poll loop -> CSV),
  `cpu_load.py` + `cpu_test.py` (CPU thermal test), `soak.py`, `runs.py` (run folders,
  events.csv), `plotting.py`, `keep_awake.py`.
- `tests/` - pytest, no network access: SSH is mocked.
- `extras/windows/` - standalone PowerShell tools, not part of the Python package.

## Rules

- **This repo is public.** Never commit passwords, real IPs/hostnames, `devices.yaml`,
  run results, or internal company paths/links. Use `192.0.2.x` addresses and generic
  names (`bench_nas_01`, `admin`) in examples and tests. Run the secret check in the
  release checklist before every push.
- Passwords reach the NAS only via stdin (`stdin_data=`), never in argv or remote command
  strings.
- Anything run on the NAS must work on QTS BusyBox: no `nohup`, `timeout`, `nproc`,
  `pkill`, `od`; `ps` has no `-o`. Detached jobs need `trap '' HUP` and an empty stdin.
- Keep Linux behaviour intact when changing Windows code paths (and vice versa); branch on
  `os.name` / `sys.platform`.
- New commands: add the option to `main.py`, logic in a module, a test in `tests/`, and a
  README section.

## Verify

```sh
python -m pytest tests -q        # must pass
nas_t --help                     # CLI still loads
nas_t status --device <name>     # if a NAS is reachable
```

## Release checklist

1. Tests pass.
2. Secret check comes back empty:
   `git grep -nIE "172\.16\.|10\.[0-9]+\.[0-9]+\.[0-9]+|password\s*=\s*['\"][^'\"]+" -- . ':!AGENTS.md'`
3. Bump `version` in `pyproject.toml` for user-visible changes.
4. Commit, push to `main`, then tell the users to run `setup.ps1` / `setup.sh` to update.
