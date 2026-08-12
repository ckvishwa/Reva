<#
.SYNOPSIS
    Real Windows E2E proof of Slice 6's product goal A: double-clicking
    Reva.Desktop.exe with NO REVA Core process running reaches
    "Core Connected" automatically.

.DESCRIPTION
    Unlike every prior E2E script in this directory, this one does NOT
    start Core itself. It only launches the real Reva.Desktop.exe against
    an isolated REVA_DATA_DIR/REVA_DESKTOP_CORE_URL and proves Desktop's
    own RevaCoreLifecycle starts a real local Core process, waits for
    health, waits for local_auth_token, and reaches Core Connected — with
    no PowerShell-side Core process at all.

.NOTES
    Requires REVA_CORE_REPO_ROOT (or REVA_CORE_PYTHON_EXE) to be
    resolvable by DeveloperModeCoreExecutableLocator — this script sets
    REVA_CORE_REPO_ROOT explicitly to $repoRoot so it never depends on
    Reva.Desktop.exe's own working directory for that resolution.
    Port 18759 — distinct from every other E2E script's port.
#>

[CmdletBinding()]
param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$desktopExe = Join-Path $repoRoot "desktop\src\Reva.Desktop\bin\$Configuration\net10.0-windows10.0.19041.0\Reva.Desktop.exe"

$testPort = 18759
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$dataDir = Join-Path $env:TEMP "reva-e2e-autostartup-$testId"
$windowReadyTimeoutSeconds = 15
$autoStartTimeoutSeconds = 40  # bounded: RevaCoreLifecycle's own 30s health timeout + margin

$script:lastUiDump = $null
$appProcess = $null
$failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([bool]$Condition, [string]$Description)
    if ($Condition) { Write-Host "  [PASS] $Description" -ForegroundColor Green }
    else { Write-Host "  [FAIL] $Description" -ForegroundColor Red; $failures.Add($Description) }
}

function Wait-Until {
    param([scriptblock]$Condition, [int]$TimeoutSeconds, [int]$PollMilliseconds = 250, [string]$Description = "condition")
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try { $result = & $Condition; if ($result) { return $result } } catch {}
        Start-Sleep -Milliseconds $PollMilliseconds
    }
    Write-Host "  TIMEOUT waiting for: $Description (${TimeoutSeconds}s)" -ForegroundColor Yellow
    return $null
}

function Find-ById {
    param([System.Windows.Automation.AutomationElement]$Root, [string]$AutomationId)
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $AutomationId)
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
}

function Stop-Cleanly {
    param([System.Diagnostics.Process]$Process, [int]$TimeoutMs = 5000)
    if ($Process -and -not $Process.HasExited) {
        try { $Process.Kill() } catch {}
        $Process.WaitForExit($TimeoutMs) | Out-Null
    }
}

function Get-ChildPythonProcesses {
    # Best-effort diagnostic only: lists python.exe processes whose
    # command line references reva_core, to confirm Desktop really did
    # launch its own Core rather than the test somehow reusing one.
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains("reva_core") }
}

Write-Host "=== REVA Desktop E2E: automatic Core startup (no pre-started Core) ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host "Core port: $testPort"
Write-Host ""

if (-not (Test-Path $desktopExe)) {
    Write-Host "FAIL: Reva.Desktop.exe not found at $desktopExe" -ForegroundColor Red
    exit 1
}

# Precondition: confirm nothing is already listening on the test port —
# this must be a genuinely cold start for the assertion below to mean anything.
$portBusy = Wait-Until -TimeoutSeconds 1 -Description "port pre-check" -Condition {
    try { Invoke-RestMethod -Uri "${coreBaseUrl}health" -TimeoutSec 1 -ErrorAction Stop; return $true } catch { return $null }
}
if ($portBusy) {
    Write-Host "FAIL: something is already listening on port $testPort — cannot prove a cold auto-start" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

try {
    Write-Host "Launching real Reva.Desktop.exe with NO Core pre-started..."
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $desktopExe
    $info.UseShellExecute = $false
    $info.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $info.EnvironmentVariables["REVA_DESKTOP_CORE_URL"] = $coreBaseUrl
    $info.EnvironmentVariables["REVA_CORE_REPO_ROOT"] = "$repoRoot"
    $appProcess = [System.Diagnostics.Process]::Start($info)
    Assert-True (-not $appProcess.HasExited) "Desktop application launched and is running"

    $root = Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "main window handle" -Condition {
        $appProcess.Refresh()
        if ($appProcess.MainWindowHandle -ne [IntPtr]::Zero) {
            return [System.Windows.Automation.AutomationElement]::FromHandle($appProcess.MainWindowHandle)
        }
        return $null
    }
    Assert-True ($null -ne $root) "Located the real WinUI window via UI Automation"
    if ($null -eq $root) { exit 1 }

    $statusText = Find-ById -Root $root -AutomationId "CoreStatusText"
    Assert-True ($null -ne $statusText) "Found real CoreStatusText control"

    $startingObserved = Wait-Until -TimeoutSeconds 5 -Description "Starting Core status observed" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Starting Core…") { return $true }
        return $null
    }
    # Not a hard failure if missed — the transition can be faster than this
    # poll interval on a fast machine — but log it either way for visibility.
    Write-Host "  [INFO] 'Starting Core…' observed before Connected: $([bool]$startingObserved)"

    $connected = Wait-Until -TimeoutSeconds $autoStartTimeoutSeconds -Description "Core Connected (auto-started)" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Connected") { return $true }
        return $null
    }
    Assert-True ($null -ne $connected) "Desktop automatically started Core and reached 'Core Connected' within ${autoStartTimeoutSeconds}s"

    $tokenPath = Join-Path $dataDir "local_auth_token"
    Assert-True (Test-Path $tokenPath) "Core-created local_auth_token exists in the isolated data directory"

    $healthDirect = $null
    try { $healthDirect = Invoke-RestMethod -Uri "${coreBaseUrl}health" -TimeoutSec 3 -ErrorAction Stop } catch {}
    Assert-True ($null -ne $healthDirect -and $healthDirect.status -eq "healthy") "Independently verified: the auto-started Core answers GET /health directly"

    $childCoreProcesses = @(Get-ChildPythonProcesses)
    Assert-True ($childCoreProcesses.Count -ge 1) "A real python.exe reva_core process is running (Desktop launched it, not this script)"
}
finally {
    if ($appProcess) { Stop-Cleanly -Process $appProcess }
    # Best-effort cleanup of whatever Core process Desktop launched — this
    # script never started it, but must not leak it past this run.
    foreach ($proc in (Get-ChildPythonProcesses)) {
        try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== E2E PASSED: automatic startup reached Core Connected with zero manual steps ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} else {
    Write-Host "=== E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    if ($script:lastUiDump) { $script:lastUiDump | ForEach-Object { Write-Host $_ } }
    Write-Host "Isolated data directory preserved for inspection: $dataDir"
    exit 1
}
