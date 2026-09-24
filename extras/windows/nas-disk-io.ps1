param(
    [int]$SizeMB = 2048,          # file write/read test size
    [Parameter(Mandatory)][string]$NasHost,
    [Parameter(Mandatory)][string]$User,
    [string]$VolPath = "/share/CACHEDEV1_DATA",
    [switch]$SkipWrite,           # skip the file write test
    [switch]$SkipRawRead,         # skip the per-disk raw read test
    [switch]$KeepFile,            # don't delete the test file
    [switch]$Clean,               # just delete the test file and exit
    [string]$Password = $env:QNAP_NAS_PASSWORD
)

$ErrorActionPreference = 'Stop'
if (-not $Password) { throw "Provide -Password or set QNAP_NAS_PASSWORD" }
$askpass = "$env:TEMP\qnap-askpass.cmd"
[IO.File]::WriteAllText($askpass, "@echo $Password`r`n")
$env:SSH_ASKPASS = $askpass
$env:SSH_ASKPASS_REQUIRE = "force"
$env:DISPLAY = ":0"
$pw = $Password
$file = "$VolPath/.iotest.bin"

function Invoke-Nas([string]$RemoteCmd) {
    ssh -o ConnectTimeout=10 -o NumberOfPasswordPrompts=1 "$User@$NasHost" $RemoteCmd 2>&1 |
        Where-Object { $_ -notmatch 'post-quantum|decrypt|upgraded|Password:' }
}

if ($Clean) {
    Invoke-Nas "rm -f $file && echo 'test file removed'"
    return
}

if (-not $SkipWrite) {
    Write-Host "`n== WRITE test: ${SizeMB}MB -> $file (fsync) ==" -ForegroundColor Cyan
    Invoke-Nas "dd if=/dev/zero of=$file bs=1M count=$SizeMB conv=fsync 2>&1 | tail -1"
}

Write-Host "`n== READ test (page cache dropped) ==" -ForegroundColor Cyan
Invoke-Nas "echo '$pw' | sudo -S -p '' sh -c 'echo 3 > /proc/sys/vm/drop_caches' >/dev/null 2>&1; dd if=$file of=/dev/null bs=1M 2>&1 | tail -1"

if (-not $SkipRawRead) {
    Write-Host "`n== RAW READ test: hdparm -t on all 4 disks in parallel ==" -ForegroundColor Cyan
    $cmd = "echo '$pw' | sudo -S -p '' true; " +
           "for d in sda sdb sdc sdd; do " +
           "(sudo -n hdparm -t /dev/`$d > /tmp/io_`$d.log 2>&1) & done; " +
           "wait; for d in sda sdb sdc sdd; do echo `"-- /dev/`$d --`"; cat /tmp/io_`$d.log; done"
    Invoke-Nas $cmd
}

if (-not $KeepFile -and -not $SkipWrite) {
    Invoke-Nas "rm -f $file" | Out-Null
    Write-Host "`ntest file removed" -ForegroundColor DarkGray
}
