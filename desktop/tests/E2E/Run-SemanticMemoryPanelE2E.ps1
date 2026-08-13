<#
.SYNOPSIS
    Real Windows E2E proof that the Desktop Memory Panel's Search action
    transparently benefits from hybrid Core retrieval (Slice 6, spec
    section 12) — no keyword overlap required between what was
    Remembered and what was Searched — and that an unrelated negative
    query clears stale positive results.

.DESCRIPTION
    Same technique as Run-MemoryPersistenceE2E.ps1: real Process.Start of
    Python Core (isolated data dir, isolated port), real Reva.Desktop.exe,
    real UI Automation. Proves three cases from the work order verbatim:
        Stored "I have a pet cat." / Search "animal" -> found
        Stored "My main career target is SDET." / Search "What kind of testing job am I targeting?" -> found
        Stored "I use an iPhone 12 as my main phone." / Search "daily handset" -> found
        Stored phone rows / Search "What is my favorite dinosaur?" -> no matches

.PARAMETER Configuration
    Build configuration to test. Default: Release.

.NOTES
    Requires a real local Ollama with nomic-embed-text pulled — this
    script is not part of CI. Never touches the developer's real
    REVA_DATA_DIR; uses an isolated %TEMP% directory and port 18761
    (distinct from the 3 existing E2E scripts' 18756/18757/18758 and
    Task 5/6's 18759/18760).
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
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

# Distinct from Run-TypedAssistantE2E.ps1 (18756), Run-MemoryPersistenceE2E.ps1
# (18757), and Run-AdkMemoryRecallE2E.ps1 (18758). Task 5/6 reserve 18759/18760.
$testPort = 18761
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$dataDir = Join-Path $env:TEMP "reva-e2e-semantic-panel-18761-$testId"
$coreReadyTimeoutSeconds = 20
$windowReadyTimeoutSeconds = 15
$searchTimeoutSeconds = 20  # generous: real embedding call, not instant echo

$coreStdoutLog = Join-Path $dataDir "core-stdout.log"
$coreStderrLog = Join-Path $dataDir "core-stderr.log"
$script:lastUiDump = $null
$coreProcess = $null
$appProcess = $null
$coreWriters = @()
$failures = New-Object System.Collections.Generic.List[string]

# --- Helper functions copied verbatim (only variable scope adapted) from ---
# --- Run-MemoryPersistenceE2E.ps1 lines 85-218 ---

function Assert-True {
    param([bool]$Condition, [string]$Description)
    if ($Condition) {
        Write-Host "  [PASS] $Description" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $Description" -ForegroundColor Red
        $failures.Add($Description)
    }
}

function Wait-Until {
    param(
        [scriptblock]$Condition,
        [int]$TimeoutSeconds,
        [int]$PollMilliseconds = 250,
        [string]$Description = "condition"
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $result = & $Condition
            if ($result) { return $result }
        } catch {
            # Transient during startup (process not ready, window not yet
            # created, etc.)  -  keep polling until the timeout.
        }
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

function Start-RealCore {
    param([string]$StdoutLog, [string]$StderrLog)
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $pythonExe
    $info.Arguments = "-m reva_core --serve"
    $info.WorkingDirectory = $repoRoot
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $info.EnvironmentVariables["REVA_API_PORT"] = "$testPort"

    $process = [System.Diagnostics.Process]::Start($info)
    $stdoutWriter = [System.IO.StreamWriter]::new($StdoutLog)
    $stderrWriter = [System.IO.StreamWriter]::new($StderrLog)
    Register-ObjectEvent -InputObject $process -EventName OutputDataReceived -Action {
        if ($EventArgs.Data) { $Event.MessageData.WriteLine($EventArgs.Data) }
    } -MessageData $stdoutWriter | Out-Null
    Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived -Action {
        if ($EventArgs.Data) { $Event.MessageData.WriteLine($EventArgs.Data) }
    } -MessageData $stderrWriter | Out-Null
    $process.BeginOutputReadLine()
    $process.BeginErrorReadLine()

    $script:coreWriters += $stdoutWriter
    $script:coreWriters += $stderrWriter

    return $process
}

function Wait-ForCoreHealthy {
    return Wait-Until -TimeoutSeconds $coreReadyTimeoutSeconds -Description "GET /health healthy" -Condition {
        try {
            $response = Invoke-RestMethod -Uri "${coreBaseUrl}health" -TimeoutSec 2 -ErrorAction Stop
            return ($response.status -eq "healthy")
        } catch { return $false }
    }
}

function Start-RealDesktop {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $desktopExe
    $info.UseShellExecute = $false
    $info.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $info.EnvironmentVariables["REVA_DESKTOP_CORE_URL"] = $coreBaseUrl
    return [System.Diagnostics.Process]::Start($info)
}

function Wait-ForMainWindow {
    param([System.Diagnostics.Process]$Process)
    return Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "main window handle" -Condition {
        $Process.Refresh()
        if ($Process.MainWindowHandle -ne [IntPtr]::Zero) {
            return [System.Windows.Automation.AutomationElement]::FromHandle($Process.MainWindowHandle)
        }
        return $null
    }
}

function Wait-ForCoreConnected {
    param([System.Windows.Automation.AutomationElement]$Root)
    $statusText = Find-ById -Root $Root -AutomationId "CoreStatusText"
    if ($null -eq $statusText) { return $null }
    return Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "Core Connected status" -Condition {
        if ($statusText.Current.Name -eq "Core Connected") { return $true }
        return $null
    }
}

function Stop-Cleanly {
    param([System.Diagnostics.Process]$Process, [int]$TimeoutMs = 5000)
    if ($Process -and -not $Process.HasExited) {
        try { $Process.Kill() } catch {}
        $Process.WaitForExit($TimeoutMs) | Out-Null
    }
}

function Write-Diagnostics {
    param([string]$Reason)
    Write-Host ""
    Write-Host "=== E2E FAILURE DIAGNOSTICS ($Reason) ===" -ForegroundColor Red
    foreach ($log in @($coreStdoutLog, $coreStderrLog)) {
        if (Test-Path $log) {
            Write-Host "--- $log (last 40 lines) ---"
            Get-Content $log -Tail 40 -ErrorAction SilentlyContinue
        }
    }
    if ($script:lastUiDump) {
        Write-Host "--- Last known UI text dump ---"
        $script:lastUiDump | ForEach-Object { Write-Host $_ }
    }
    Write-Host "Isolated data directory preserved for inspection: $dataDir"
    Write-Host "(Never contains anything from your normal REVA data  -  this run used"
    Write-Host " an isolated directory and a non-default port, $($testPort).)"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

Write-Host "=== REVA Desktop E2E: hybrid semantic Memory Panel search ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host "Core port: $testPort"
Write-Host ""

if (-not (Test-Path $desktopExe)) {
    Write-Host "FAIL: Reva.Desktop.exe not found at $desktopExe" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $pythonExe)) {
    Write-Host "FAIL: Python venv not found at $pythonExe" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

$cases = @(
    @{ Remember = "I have a pet cat."; Search = "animal"; ExpectContains = "cat" }
    @{ Remember = "My main career target is SDET."; Search = "What kind of testing job am I targeting?"; ExpectContains = "SDET" }
    @{ Remember = "I use an iPhone 12 as my main phone."; Search = "daily handset"; ExpectContains = "iPhone" }
    @{ Remember = "What phone do I use?"; Search = "Do I have an iPhone 12?"; ExpectContains = "iPhone" }
)

try {
    Write-Host "Starting real REVA Core (isolated, port $testPort)..."
    $coreProcess = Start-RealCore -StdoutLog $coreStdoutLog -StderrLog $coreStderrLog
    $healthy = Wait-ForCoreHealthy
    Assert-True ($null -ne $healthy) "Real Core became healthy within ${coreReadyTimeoutSeconds}s"
    if ($null -eq $healthy) { Write-Diagnostics "Core never became healthy"; exit 1 }

    Write-Host "Launching real Reva.Desktop.exe..."
    $appProcess = Start-RealDesktop
    $root = Wait-ForMainWindow -Process $appProcess
    Assert-True ($null -ne $root) "Located the real WinUI window via UI Automation"
    if ($null -eq $root) { Write-Diagnostics "Main window never appeared"; exit 1 }

    $connected = Wait-ForCoreConnected -Root $root
    Assert-True ($null -ne $connected) "Desktop app shows real 'Core Connected' status"

    $memoryBox = Find-ById -Root $root -AutomationId "MemoryBox"
    $rememberButton = Find-ById -Root $root -AutomationId "RememberButton"
    $searchButton = Find-ById -Root $root -AutomationId "SearchButton"
    $memoryStatusText = Find-ById -Root $root -AutomationId "MemoryStatusText"
    $memorySearchResultText = Find-ById -Root $root -AutomationId "MemorySearchResultText"
    $memoryValuePattern = $memoryBox.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)

    foreach ($case in $cases) {
        Write-Host ""
        Write-Host "Case: Remember '$($case.Remember)' / Search '$($case.Search)'..."

        $memoryValuePattern.SetValue($case.Remember)
        Wait-Until -TimeoutSeconds 5 -Description "memory box content set" -Condition {
            $memoryValuePattern.Current.Value -eq $case.Remember
        } | Out-Null
        $rememberButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        $remembered = Wait-Until -TimeoutSeconds 15 -Description "Remembered. status" -Condition {
            if ($memoryStatusText.Current.Name -eq "Remembered.") { return $true }
            return $null
        }
        Assert-True ($null -ne $remembered) "Stored: '$($case.Remember)'"

        $memoryValuePattern.SetValue($case.Search)
        Wait-Until -TimeoutSeconds 5 -Description "search box content set" -Condition {
            $memoryValuePattern.Current.Value -eq $case.Search
        } | Out-Null
        $searchButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

        $found = Wait-Until -TimeoutSeconds $searchTimeoutSeconds -Description "search result contains expected content" -Condition {
            $value = $memorySearchResultText.Current.Name
            $script:lastUiDump = @("MemorySearchResultText: [$value]")
            if ($value -and $value.Contains($case.ExpectContains)) { return $value }
            return $null
        }
        Assert-True ($null -ne $found) "Search '$($case.Search)' found memory containing '$($case.ExpectContains)' with no required keyword overlap"
    }

    Write-Host ""
    Write-Host "Negative case: Search 'What is my favorite dinosaur?' after prior phone hit..."
    $negativeQuery = "What is my favorite dinosaur?"
    $memoryValuePattern.SetValue($negativeQuery)
    Wait-Until -TimeoutSeconds 5 -Description "negative search box content set" -Condition {
        $memoryValuePattern.Current.Value -eq $negativeQuery
    } | Out-Null
    $searchButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    $noMatch = Wait-Until -TimeoutSeconds $searchTimeoutSeconds -Description "negative search shows no matches and clears stale results" -Condition {
        $value = $memorySearchResultText.Current.Name
        $script:lastUiDump = @("MemorySearchResultText: [$value]")
        if ($value -eq "No matching memories found.") { return $value }
        return $null
    }
    Assert-True ($null -ne $noMatch) "Search '$negativeQuery' shows 'No matching memories found.'"
    Assert-True (-not $memorySearchResultText.Current.Name.Contains("iPhone")) "Negative search cleared stale phone result"
}
finally {
    if ($appProcess) { Stop-Cleanly -Process $appProcess }
    if ($coreProcess) { Stop-Cleanly -Process $coreProcess }
    Get-EventSubscriber -ErrorAction SilentlyContinue | Where-Object { $_.SourceObject -eq $coreProcess } | Unregister-Event -ErrorAction SilentlyContinue
    foreach ($writer in $coreWriters) { try { $writer.Dispose() } catch {} }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== E2E PASSED ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} else {
    Write-Diagnostics "one or more assertions failed"
    Write-Host "=== E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
