# nas_t

CLI for bench-testing NAS units: live and logged temperature/SMART monitoring, drive
write load, and **CPU thermal-interface tests** (e.g. comparing CPU pad thickness) with
plotting and run-to-run comparison. Works on Windows and Linux.

Originally written by Casey Matalone; CPU test, plotting and Windows support added by
Bob Plumeau.

## Install / update

Windows (PowerShell 7):

```powershell
git clone https://github.com/bobplumeau/nas-tools.git
cd nas-tools
pwsh -File setup.ps1
```

Linux / macOS:

```sh
git clone https://github.com/bobplumeau/nas-tools.git
cd nas-tools
./setup.sh
```

Run the same script again at any time to **refresh**: it pulls the latest code,
reinstalls, runs the tests, and puts `nas_t` on your PATH. Options: `-NoPull` /
`--no-pull` to reinstall local edits, `-Clean` / `--clean` to rebuild the venv.

On Linux, password auth needs `sshpass` (`sudo apt install sshpass`). On Windows the
built-in OpenSSH client is used via `SSH_ASKPASS`, so nothing extra is needed.

## Configure

Setup creates `~/.config/nas_t/devices.yaml` from `devices.example.yaml`. Edit it:

```yaml
devices:
  bench_nas_01:
    nas_ip: [192.0.2.11, 192.0.2.10]   # one address, or candidates tried in order
    jump_host: null                     # or user@host / ~/.ssh/config alias
    ssh_user: admin
    ssh_password_env: NAS_T_SSH_PASSWORD
    vendor: qnap
    network_interface: eth0
```

`devices.yaml` is looked up in `$NAS_T_DEVICES_FILE`, `./devices.yaml`,
`~/.config/nas_t/devices.yaml`, then `~/.config/nas-t/devices.yaml`. It is gitignored:
real addresses never go in the repo.

**Passwords** are never stored in `devices.yaml`. The profile names an environment
variable; if it isn't set, the interactive shell prompts once and saves it to
`~/.config/nas_t/credentials` (plaintext, owner-only; `logout` clears it). An exported
variable always wins. One-shot commands never prompt.

## CPU thermal test (pad / TIM comparison)

Run the same test once per build, from the same starting condition (e.g. a cold NAS,
started a few minutes after boot):

```sh
nas_t cpu-test --device bench_nas_01 --label "1 layer PTM7950" --shutdown-after
# next day, after rebuilding:
nas_t cpu-test --device bench_nas_01 --label "2 layers PTM7950" --shutdown-after
nas_t compare results/cpu_20260924_1552 results/cpu_20260925_0900
```

`cpu-test` logs an idle baseline (5 min), runs a busy loop on every NAS CPU core (60
min), then logs the cooldown (15 min). All durations are options.

- The load runs **on the NAS** as a detached job, so it stops on schedule even if this
  machine sleeps or disconnects. The test also blocks PC sleep while it logs (Windows).
- `--stop-at-soak` ends the load once `coretemp` has levelled off: trend over the last
  `--soak-window` minutes (10) at most `--soak-rise` C (0.5), twice in a row, after
  `--soak-min-load` minutes (20). Use the same rule for every build you compare.
- `--shutdown-after` powers the NAS off when the run completes, ready for a cold start.
- Ctrl+C stops the run and the NAS load. If a window was closed mid-run, `nas_t cpu-stop`
  stops a leftover load.

Plot a run (saves `temps.png` in the run folder; `--live` refreshes while it runs):

```sh
nas_t plot results/cpu_20260924_1552 --live
```

The top panel shows `coretemp` (CPU package, on-die sensor), QNAP's `cpu` value and
`system`; the bottom panel shows each CPU reading **minus `system`**, which is the figure
that reflects the thermal interface. `compare` overlays runs aligned to load start and
prints each run's steady state (mean of the last 10 minutes of load) and the difference.

Each run folder contains `smart_log.csv` and `events.csv` (label, phase times, and an
updated `load_stop` if soak ended the load early).

## Other commands

| Command | Purpose |
|---|---|
| `nas_t` / `nas_t shell` | Interactive shell; auto-selects the first device, so `--device` can be omitted |
| `status` | One-shot table of every drive and chassis sensor, plus a one-line digest |
| `monitor` | Live table refreshed every 2 s, with change since start. Writes nothing |
| `log --output F.csv` | Poll to CSV (default every 30 s); `--network-output` adds throughput |
| `load` | Field-like write load: copies a real capture file onto a mounted share on an interval |
| `fio-load` | Synthetic sequential write load via `fio` (Linux) |
| `test` | `log` + a loader together with a live dashboard (`smart_log.csv`, `network_log.csv`) |

On Windows, `load`/`test --loader replay` accept a UNC path for `--mount-path`, e.g.
`\\nas\Public\nas_t_load` (map it first with `net use`).

`smart_log.csv` is long format, one row per sensor per poll:
`timestamp,sensor,temperature_c,healthy` (`healthy` is drive-only). A 4-bay QNAP emits
`disk1`..`disk4`, `cpu`, `system`, `coretemp`, `eth0`, `eth1`.

## How it reads a QNAP

- `vendor: qnap` uses QTS's `getsysinfo` (many units ship no `smartctl`) plus every
  `/sys/class/hwmon` device (`coretemp` = CPU package, NIC PHYs). `getsysinfo` needs sudo;
  the password goes over the remote shell's stdin, never on a command line. Any other
  vendor uses `smartctl -A`/`-H`.
- One SSH round trip per poll. On Linux, connections are multiplexed with
  `ControlMaster`; Windows OpenSSH has no multiplexing, so each poll reconnects.
- Stock QNAP home directories fail sshd's `StrictModes`, so key auth is rejected: use
  password auth.
- QTS has no `nohup`, `timeout` or `nproc`; the CPU load script works around all three.
- Repeated failed logins trigger QTS's Network Access Protection, which blocks your IP
  on every port (ping still works) for a few minutes.

`extras/windows/` holds standalone PowerShell scripts (QTS web-API temperature window,
CSV monitor, quick disk read/write benchmark) that don't need Python.

## Development

```sh
python -m pytest tests -q
```

See `AGENTS.md` for conventions and the release checklist.
