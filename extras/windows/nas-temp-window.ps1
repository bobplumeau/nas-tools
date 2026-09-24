param(
    [int]$Interval = 15,
    [Parameter(Mandatory)][string]$NasHost,
    [Parameter(Mandatory)][string]$User,
    [switch]$Topmost,
    [string]$Password = $env:QNAP_NAS_PASSWORD
)

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase

if (-not $Password) { throw "Provide -Password or set QNAP_NAS_PASSWORD" }
$script:sid = $null

function Get-Sid {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($password))
    $xml = [xml](curl.exe -sk "https://$NasHost/cgi-bin/authLogin.cgi?user=$User&pwd=$b64" | Out-String)
    if ($xml.QDocRoot.authPassed.InnerText -ne '1') { throw "auth failed" }
    $xml.QDocRoot.authSid.InnerText
}

function Get-Temps {
    $xml = [xml](curl.exe -sk "https://$NasHost/cgi-bin/management/manaRequest.cgi?subfunc=sysinfo&sid=$($script:sid)" | Out-String)
    $r = $xml.QDocRoot.func.ownContent.root
    if (-not $r) { throw "no data (sid expired?)" }
    @{
        CPU   = [int]$r.cpu_tempc
        SYS   = [int]$r.sys_tempc
        Disk1 = [int]$r.ssd_tempc1
        Disk2 = [int]$r.ssd_tempc2
        Disk3 = [int]$r.ssd_tempc3
        Disk4 = [int]$r.ssd_tempc4
    }
}

# thresholds from the NAS: warn, error (deg C)
$limits = @{
    CPU   = @(80, 92)
    SYS   = @(60, 90)
    Disk1 = @(70, 70)
    Disk2 = @(70, 70)
    Disk3 = @(70, 70)
    Disk4 = @(70, 70)
}

$brushBg     = [Windows.Media.BrushConverter]::new().ConvertFrom('#1e1e1e')
$brushFg     = [Windows.Media.BrushConverter]::new().ConvertFrom('#d4d4d4')
$brushDim    = [Windows.Media.BrushConverter]::new().ConvertFrom('#808080')
$brushGreen  = [Windows.Media.BrushConverter]::new().ConvertFrom('#6a9955')
$brushOrange = [Windows.Media.BrushConverter]::new().ConvertFrom('#d7a13a')
$brushRed    = [Windows.Media.BrushConverter]::new().ConvertFrom('#f44747')

$window = New-Object Windows.Window
$window.Title = 'NAS temps'
$window.Width = 300
$window.SizeToContent = 'Height'
$window.WindowStartupLocation = 'CenterScreen'
$window.Topmost = [bool]$Topmost
$window.Background = $brushBg
$window.Foreground = $brushFg
$window.FontFamily = 'Consolas'
$window.FontSize = 16

$grid = New-Object Windows.Controls.Grid
$grid.Margin = '16'
0..8 | ForEach-Object { $grid.RowDefinitions.Add((New-Object Windows.Controls.RowDefinition)) }
'Auto','*' | ForEach-Object {
    $cd = New-Object Windows.Controls.ColumnDefinition
    $cd.Width = $_
    $grid.ColumnDefinitions.Add($cd)
}

$script:tempBlocks = @{}
$names = 'CPU','SYS','Disk1','Disk2','Disk3','Disk4'
$labels = 'CPU','System','SSD 1','SSD 2','SSD 3','SSD 4'
for ($i = 0; $i -lt $names.Count; $i++) {
    $lbl = New-Object Windows.Controls.TextBlock
    $lbl.Text = $labels[$i]
    $lbl.Margin = '0,3'
    [Windows.Controls.Grid]::SetRow($lbl, $i)
    $grid.Children.Add($lbl) | Out-Null

    $val = New-Object Windows.Controls.TextBlock
    $val.Text = '--'
    $val.HorizontalAlignment = 'Right'
    $val.FontWeight = 'Bold'
    $val.Margin = '0,3'
    [Windows.Controls.Grid]::SetRow($val, $i)
    [Windows.Controls.Grid]::SetColumn($val, 1)
    $grid.Children.Add($val) | Out-Null
    $script:tempBlocks[$names[$i]] = $val
}

$script:status = New-Object Windows.Controls.TextBlock
$script:status.Text = 'connecting...'
$script:status.Foreground = $brushDim
$script:status.FontSize = 11
$script:status.Margin = '0,10,0,0'
[Windows.Controls.Grid]::SetRow($script:status, $names.Count)
[Windows.Controls.Grid]::SetColumnSpan($script:status, 2)
$grid.Children.Add($script:status) | Out-Null

$window.Content = $grid

function Update-Temps {
    try {
        if (-not $script:sid) { $script:sid = Get-Sid }
        $t = Get-Temps
    } catch {
        try { $script:sid = Get-Sid; $t = Get-Temps } catch {
            $script:status.Text = "fetch failed: $($_.Exception.Message)"
            $script:sid = $null
            return
        }
    }
    foreach ($k in $names) {
        $v = $t[$k]
        $b = $script:tempBlocks[$k]
        $b.Text = "{0} °C" -f $v
        $w, $e = $limits[$k]
        $b.Foreground = if ($v -ge $e) { $brushRed } elseif ($v -ge $w) { $brushOrange } else { $brushGreen }
    }
    $script:status.Text = "updated $(Get-Date -Format 'HH:mm:ss')  ·  every ${Interval}s"
}

$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromSeconds($Interval)
$timer.Add_Tick({ Update-Temps })
$timer.Start()

$window.Add_Loaded({ Update-Temps })
$window.ShowDialog() | Out-Null
