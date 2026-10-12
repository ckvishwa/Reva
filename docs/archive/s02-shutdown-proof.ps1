param(
  [string]$Exe = 'D:\Projects\Reva-s02-proof\desktop\src\Reva.Desktop\bin\Debug\net10.0-windows10.0.19041.0\Reva.Desktop.exe',
  [string]$Repo = 'D:\Projects\Reva',
  [int]$Port = 18756,
  [int]$Cycles = 10,
  [string]$Out = 'D:\Projects\reva-s02-evidence.txt'
)
$ErrorActionPreference = 'Stop'
$data = Join-Path $env:TEMP ("reva-s02-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $data | Out-Null
$env:REVA_DATA_DIR = $data
$env:REVA_DESKTOP_CORE_URL = "http://127.0.0.1:$Port/"
$env:REVA_CORE_REPO_ROOT = $Repo
$env:REVA_ASSISTANT_ORCHESTRATOR = 'deterministic'
$log = New-Object System.Collections.Generic.List[string]
function L($m) { $log.Add($m); Write-Host $m }
function CorePids { @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'reva_core' } | ForEach-Object { $_.ProcessId }) }
function ListenerPid { $c = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { $c.OwningProcess } else { $null } }
function WaitFor($sb, $sec) { $end = (Get-Date).AddSeconds($sec); while ((Get-Date) -lt $end) { $v = & $sb; if ($v) { return $v }; Start-Sleep -Milliseconds 300 }; return $null }

L "S02 proof $(Get-Date -Format o)  exe=$Exe  port=$Port  data=$data"
L "pre-existing reva_core processes: $((CorePids) -join ',')"
if ((CorePids).Count -gt 0) { throw 'pre-existing Core process; aborting' }

$results = @()
for ($i = 1; $i -le $Cycles; $i++) {
  $p = Start-Process -FilePath $Exe -PassThru
  $corePid = WaitFor { ListenerPid } 60
  $win = WaitFor { $p.Refresh(); if ($p.MainWindowHandle -ne 0) { $true } } 30
  Start-Sleep -Seconds 2
  $before = CorePids
  $t0 = Get-Date
  $closed = $p.CloseMainWindow()
  $exited = $p.WaitForExit(20000)
  $dt = [int]((Get-Date) - $t0).TotalMilliseconds
  Start-Sleep -Milliseconds 800
  $after = CorePids
  $listener = ListenerPid
  $row = [pscustomobject]@{ Cycle=$i; DesktopPid=$p.Id; CorePidListener=$corePid; CoreProcsBefore=($before -join ','); CloseSent=$closed; DesktopExited=$exited; ExitMs=$dt; CoreProcsAfter=($after -join ','); PortStillListening=[bool]$listener }
  $results += $row
  L ($row | ConvertTo-Json -Compress)
  if (-not $exited) { Stop-Process -Id $p.Id -Force }
  foreach ($x in $after) { Stop-Process -Id $x -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 1
}
$orphans = ($results | Where-Object { $_.CoreProcsAfter -or $_.PortStillListening -or -not $_.DesktopExited }).Count
L "OWNED CYCLES: $Cycles, cycles with survivor/hang: $orphans"

# External Core must survive Desktop shutdown
L "--- external Core test"
$py = Join-Path $Repo '.venv\Scripts\python.exe'
$env:REVA_API_PORT = "$Port"
$core = Start-Process -FilePath $py -ArgumentList '-m','reva_core','--serve' -WorkingDirectory $Repo -PassThru -WindowStyle Hidden
$lp = WaitFor { ListenerPid } 60
$extPids = CorePids
L "external Core launched pid=$($core.Id) listener=$lp reva_core procs=$($extPids -join ',')"
$p = Start-Process -FilePath $Exe -PassThru
$null = WaitFor { $p.Refresh(); if ($p.MainWindowHandle -ne 0) { $true } } 30
Start-Sleep -Seconds 3
$during = CorePids
$null = $p.CloseMainWindow()
$exited = $p.WaitForExit(20000)
Start-Sleep -Seconds 1
$survivors = CorePids
$stillListening = [bool](ListenerPid)
L "desktop exited=$exited; Core procs during=$($during -join ',') after=$($survivors -join ','); port listening=$stillListening"
$extOk = $exited -and ($survivors -contains $core.Id -or $survivors -contains $lp) -and $stillListening
L "EXTERNAL CORE SURVIVED: $extOk"
foreach ($x in (CorePids)) { Stop-Process -Id $x -Force -ErrorAction SilentlyContinue }
if (-not $exited) { Stop-Process -Id $p.Id -Force }
L "cleanup: remaining reva_core procs=$((CorePids) -join ',')"
$log | Set-Content $Out
