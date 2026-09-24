---
name: nas-t
description: Run, refresh, or modify the nas_t NAS test app - read NAS temperatures and SMART health, log them, run write-load or CPU thermal (pad/TIM) tests, plot and compare runs, and update/release the app itself. Use whenever asked to test or monitor a NAS, run or compare a CPU pad test, or "refresh"/update/change the test app.
---

# nas_t

Source: this repo (`bobplumeau/nas-tools`). Prose docs: `README.md`; conventions and the
release checklist: `AGENTS.md`.

## Running tests for the user

- Check reachability first: `nas_t status --device <name>`. If SSH is refused right
  after power-on, the NAS is still booting: poll port 22 for up to ~3 min.
- CPU pad/TIM test: `nas_t cpu-test --device <name> --label "<build>"`. Add
  `--shutdown-after` when the next run should start cold, `--stop-at-soak` only if the
  user wants it (use the same soak rule across compared runs). Launch it in its own
  terminal (Windows: `wt new-tab pwsh -NoExit -Command nas_t cpu-test ...`) so it
  survives the agent session, then watch the run folder's `smart_log.csv`.
- Live view: `nas_t plot <run_dir> --live`. Compare builds: `nas_t compare <dirA> <dirB>`
  and report the steady-state `coretemp - system` difference, noting run length and
  start condition differences.
- `coretemp` is the CPU package (on-die DTS) and the right sensor for thermal-interface
  work; QNAP's `cpu` reads lower under load. Disk load barely heats the CPU.
- Never guess passwords: failed logins get this PC's IP blocked by QTS for minutes.

## Refreshing / changing the app

1. `git pull`, then make the change following `AGENTS.md` (logic in `src/nas_t/`, option
   in `src/main.py`, test in `tests/`, README section).
2. Reinstall and test: `pwsh -File setup.ps1 -NoPull` (Windows) or `./setup.sh --no-pull`.
3. Run the release checklist in `AGENTS.md` (tests + secret check), bump the version for
   user-visible changes, commit, and push only if the user asked.
4. Tell the user what changed and that the other user should run `setup.ps1`/`setup.sh`.

## Gotchas

| Symptom | Cause / fix |
|---|---|
| `Connection closed by UNKNOWN port 65535` on Windows | A `jump_host` the PC can't resolve, or a ControlMaster option; the Windows path disables multiplexing |
| Remote job never starts | QTS has no `nohup`; use `trap '' HUP` and pass `stdin_data=""` |
| SSH call hangs launching a background job | stdin left open: pass `stdin_data=""` |
| All ports closed but ping works | QTS Network Access Protection after failed logins; wait it out |
| Path like `\nas\share` writes to C:\ | A UNC path lost a backslash in shell quoting: write scripts with a file tool, not heredocs |
