param(
    [int]$Interval = 30,
    [Parameter(Mandatory)][string]$NasHost,
    [Parameter(Mandatory)][string]$User,
    [string]$LogCsv = "$PSScriptRoot\nas-temps.csv",
    [string]$Password = $env:QNAP_NAS_PASSWORD
)

$ErrorActionPreference = 'Stop'
if (-not $Password) { throw "Provide -Password or set QNAP_NAS_PASSWORD" }
$sid = $null

function Get-Sid {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($password))
    $xml = [xml](curl.exe -sk "https://$NasHost/cgi-bin/authLogin.cgi?user=$User&pwd=$b64" | Out-String)
    if ($xml.QDocRoot.authPassed.InnerText -ne '1') { throw "auth failed" }
    $xml.QDocRoot.authSid.InnerText
}

function Get-Temps {
    $xml = [xml](curl.exe -sk "https://$NasHost/cgi-bin/management/manaRequest.cgi?subfunc=sysinfo&sid=$sid" | Out-String)
    $r = $xml.QDocRoot.func.ownContent.root
    if (-not $r) { throw "no data (sid expired?)" }
    [pscustomobject]@{
        Time    = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        CpuC    = [int]$r.cpu_tempc
        SysC    = [int]$r.sys_tempc
        Disk1C  = [int]$r.ssd_tempc1
        Disk2C  = [int]$r.ssd_tempc2
        Disk3C  = [int]$r.ssd_tempc3
        Disk4C  = [int]$r.ssd_tempc4
    }
}

$script:sid = Get-Sid
if (-not (Test-Path $LogCsv)) { "Time,CpuC,SysC,Disk1C,Disk2C,Disk3C,Disk4C" | Out-File $LogCsv -Encoding utf8 }

Write-Host ("{0,-19} {1,5} {2,5} {3,6} {4,6} {5,6} {6,6}" -f 'Time','CPU','SYS','DSK1','DSK2','DSK3','DSK4')
while ($true) {
    try {
        $t = Get-Temps
    } catch {
        $script:sid = Get-Sid
        $t = Get-Temps
    }
    $line = "{0,-19} {1,4}C {2,4}C {3,5}C {4,5}C {5,5}C {6,5}C" -f $t.Time,$t.CpuC,$t.SysC,$t.Disk1C,$t.Disk2C,$t.Disk3C,$t.Disk4C
    Write-Host $line
    "$($t.Time),$($t.CpuC),$($t.SysC),$($t.Disk1C),$($t.Disk2C),$($t.Disk3C),$($t.Disk4C)" | Out-File $LogCsv -Append -Encoding utf8
    Start-Sleep -Seconds $Interval
}
