"""CPU load on the NAS itself, for thermal-interface (CPU pad / TIM) testing.

The load runs as a detached shell script on the NAS so it keeps going, and stops on
schedule, even if this machine sleeps or the SSH session drops. Two QTS quirks shape it:

- QTS ships no ``nohup``, so the script ignores SIGHUP itself (``trap '' HUP``).
- The launching SSH session must not hold stdin open, or ssh waits on the backgrounded
  job; an empty stdin is passed for that reason.
"""

from dataclasses import dataclass

from nas_t.config import DeviceProfile
from nas_t.ssh_client import run_remote_command

REMOTE_SCRIPT = "/tmp/nas_t_cpuburn.sh"
REMOTE_PIDS = "/tmp/nas_t_cpuburn.pids"

# $1 idle seconds, $2 load seconds, $3 worker count. Sleeps run in the background with
# `wait` so a TERM is handled immediately (sh defers traps until a foreground command
# ends); the trap then kills the workers and the pending sleep.
_BURN_SCRIPT = f"""#!/bin/sh
trap '' HUP
p=
s=
cleanup() {{ kill $p $s 2>/dev/null; rm -f {REMOTE_PIDS}; exit 0; }}
trap cleanup TERM INT
echo $$ >{REMOTE_PIDS}
sleep "$1" & s=$!; wait $s
i=0
while [ "$i" -lt "$3" ]; do
    yes >/dev/null &
    p="$p $!"
    i=$((i + 1))
done
sleep "$2" & s=$!; wait $s
cleanup
"""

# Reports "<scripts still running> <pid file still present>"; the script's TERM trap kills
# its own workers and removes the pid file. Only counts this tool's processes, so other
# load on the NAS doesn't confuse it. The bracketed pattern keeps grep from matching itself.
_STOP_COMMAND = (
    f"[ -f {REMOTE_PIDS} ] && kill $(cat {REMOTE_PIDS}) 2>/dev/null; sleep 1; "
    f"echo $(ps | grep -c '[n]as_t_cpuburn.sh') $([ -f {REMOTE_PIDS} ] && echo 1 || echo 0)"
)

_POWEROFF_COMMAND = 'read -r NAS_T_PW; echo "$NAS_T_PW" | sudo -S -p "" /sbin/poweroff'


@dataclass
class LoadResult:
    ok: bool
    detail: str = ""


def cpu_count(device: DeviceProfile) -> int:
    """Number of CPUs on the NAS (QTS has no nproc, so this reads /proc/cpuinfo)."""
    result = run_remote_command(device, "grep -c ^processor /proc/cpuinfo", stdin_data="")
    try:
        return max(1, int(result.stdout.strip()))
    except ValueError:
        return 1


def start_cpu_load(device: DeviceProfile, idle_sec: int, load_sec: int, workers: int) -> LoadResult:
    """Uploads the burn script and starts it detached: idle, then ``workers`` busy loops
    for ``load_sec``, then stop. Returns once the job is scheduled, not when it ends."""
    upload = run_remote_command(device, f"cat > {REMOTE_SCRIPT}", stdin_data=_BURN_SCRIPT)
    if upload.exit_code != 0:
        return LoadResult(False, f"upload failed: {upload.stderr.strip()}")
    launch = run_remote_command(
        device,
        f"sh {REMOTE_SCRIPT} {idle_sec} {load_sec} {workers} </dev/null >/dev/null 2>&1 &",
        stdin_data="",
    )
    if launch.exit_code != 0:
        return LoadResult(False, f"launch failed: {launch.stderr.strip()}")
    check = run_remote_command(device, "ps | grep -c '[n]as_t_cpuburn.sh'", stdin_data="")
    if check.stdout.strip() in ("", "0"):
        return LoadResult(False, "burn script is not running on the NAS")
    return LoadResult(True)


def stop_cpu_load(device: DeviceProfile) -> LoadResult:
    """Stops the load (and the pending schedule) immediately."""
    result = run_remote_command(device, _STOP_COMMAND, stdin_data="")
    counts = result.stdout.strip().splitlines()[-1].split() if result.stdout.strip() else []
    if len(counts) != 2:
        return LoadResult(False, f"could not confirm stop: {result.stderr.strip()}")
    return LoadResult(counts == ["0", "0"], f"scripts left: {counts[0]}, pid file left: {counts[1]}")


def poweroff(device: DeviceProfile) -> LoadResult:
    """Shuts the NAS down cleanly. The sudo password goes over stdin, never argv."""
    password = device.sudo_password
    if password is None:
        return LoadResult(False, "no sudo password available")
    result = run_remote_command(device, _POWEROFF_COMMAND, stdin_data=password + "\n")
    # The connection may drop as the NAS goes down, so a non-zero exit isn't a failure.
    return LoadResult(True, result.stderr.strip())
