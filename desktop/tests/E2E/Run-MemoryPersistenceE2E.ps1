<#
.SYNOPSIS
    Real Windows E2E proof for the Phase 1B Slice 4 explicit-memory and
    persistence flow.

.DESCRIPTION
    Drives the ACTUAL compiled Reva.Desktop.exe (via System.Windows.Automation)
    against a REAL running REVA Core process, in an isolated temporary data
    directory and on a non-default loopback port  -  same technique as
    Run-TypedAssistantE2E.ps1 (Slice 3), extended to prove explicit memory
    creation, recall, and persistence across a full Desktop+Core restart.

    Flow proven:
        real Python Core (--serve, isolated data dir, isolated port)
        -> real built Reva.Desktop.exe
        -> real WinUI controls (MemoryBox, RememberButton, SearchButton)
        -> real authenticated POST /v1/memories
        -> durable memory created (independently verified via GET /v1/memories
           and GET /v1/audit-events on the real Core process)
        -> real Desktop + Core process restart against the SAME isolated
           REVA_DATA_DIR
        -> real recall via GET-backed Search proves the memory survived
        -> a whitespace-only Remember attempt creates zero durable memory
        -> an ordinary typed chat message continues to create zero memory

.PARAMETER Configuration
    Build configuration to test. Default: Release.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File desktop\tests\E2E\Run-MemoryPersistenceE2E.ps1

.NOTES
    Exit code 0 = every assertion passed. Exit code 1 = a required
    condition failed, was missing, or timed out  -  diagnostics are printed
    before exit and the isolated data directory is preserved for inspection.
    On success, the isolated data directory is deleted.

    Never reads, prints, or logs the real local_auth_token value anywhere
    beyond using it as a Bearer header for verification requests this
    script itself makes. Never touches the developer's real REVA_DATA_DIR.
#>

[CmdletBinding()]
param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

# ---------------------------------------------------------------------------
# Fixed paths / isolated identity for this run
# ---------------------------------------------------------------------------

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$desktopExe = Join-Path $repoRoot "desktop\src\Reva.Desktop\bin\$Configuration\net10.0-windows10.0.19041.0\Reva.Desktop.exe"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

# Distinct from Run-TypedAssistantE2E.ps1's port (18756) so both E2E scripts
# can run concurrently without colliding.
$testPort = 18757
$coreBaseUrl = "http://127.0.0.1:$testPort/"

$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$memoryContent = "test-color-$testId = cobalt"
$chatMessage = "e2e memory-slice ordinary chat $testId"
$dataDir = Join-Path $env:TEMP "reva-e2e-memory-$testId"

$coreReadyTimeoutSeconds = 20
$windowReadyTimeoutSeconds = 15
$responseTimeoutSeconds = 15

$coreStdoutLog = Join-Path $dataDir "core-stdout-1.log"
$coreStderrLog = Join-Path $dataDir "core-stderr-1.log"
$coreStdoutLog2 = Join-Path $dataDir "core-stdout-2.log"
$coreStderrLog2 = Join-Path $dataDir "core-stderr-2.log"

$script:lastUiDump = $null
$coreProcess = $null
$appProcess = $null
$coreWriters = @()
$failures = New-Object System.Collections.Generic.List[string]

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
    foreach ($log in @($coreStdoutLog, $coreStderrLog, $coreStdoutLog2, $coreStderrLog2)) {
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

Write-Host "=== REVA Desktop E2E: explicit memory + persistence flow ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host "Core port: $testPort"
Write-Host ""

if (-not (Test-Path $desktopExe)) {
    Write-Host "FAIL: Reva.Desktop.exe not found at $desktopExe" -ForegroundColor Red
    Write-Host "Build first: dotnet build desktop\Reva.Desktop.sln --configuration $Configuration"
    exit 1
}
if (-not (Test-Path $pythonExe)) {
    Write-Host "FAIL: Python venv not found at $pythonExe" -ForegroundColor Red
    Write-Host "Set up REVA Core's venv first  -  see docs/development/setup.md."
    exit 1
}

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

try {
    # -----------------------------------------------------------------------
    # Round 1: start real Core + real Desktop
    # -----------------------------------------------------------------------

    Write-Host "Starting real REVA Core (isolated, port $testPort)..."
    $coreProcess = Start-RealCore -StdoutLog $coreStdoutLog -StderrLog $coreStderrLog

    Write-Host "Waiting for Core readiness (timeout ${coreReadyTimeoutSeconds}s)..."
    $healthy = Wait-ForCoreHealthy
    Assert-True ($null -ne $healthy) "Real Core became healthy within ${coreReadyTimeoutSeconds}s"
    if ($null -eq $healthy) { Write-Diagnostics "Core never became healthy"; exit 1 }

    $tokenPath = Join-Path $dataDir "local_auth_token"
    $tokenReady = Wait-Until -TimeoutSeconds 5 -Description "local_auth_token written" -Condition {
        if (Test-Path $tokenPath) { return (Get-Content $tokenPath -Raw).Trim() } else { return $null }
    }
    Assert-True ($null -ne $tokenReady -and $tokenReady.Length -gt 0) "Local auth token file provisioned by Core"
    $token = $tokenReady
    $authHeaders = @{ Authorization = "Bearer $token" }

    Write-Host "Launching real Reva.Desktop.exe..."
    $appProcess = Start-RealDesktop
    Assert-True (-not $appProcess.HasExited) "Desktop application launched and is running"

    Write-Host "Waiting for the real WinUI window (timeout ${windowReadyTimeoutSeconds}s)..."
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
    Assert-True ($null -ne $memoryBox) "Found real MemoryBox control"
    Assert-True ($null -ne $rememberButton) "Found real RememberButton control"
    Assert-True ($null -ne $searchButton) "Found real SearchButton control"
    Assert-True ($null -ne $memoryStatusText) "Found real MemoryStatusText control"
    Assert-True ($null -ne $memorySearchResultText) "Found real MemorySearchResultText control"

    # -----------------------------------------------------------------------
    # Negative case FIRST (while the memory store is still empty of this
    # test's content): whitespace-only Remember must create zero memories.
    # -----------------------------------------------------------------------

    Write-Host "Negative case: whitespace-only Remember must create no memory..."
    $memoryValuePattern = $memoryBox.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $memoryValuePattern.SetValue("   ")
    $whitespaceSet = Wait-Until -TimeoutSeconds 5 -Description "memory box whitespace set" -Condition {
        $memoryValuePattern.Current.Value -eq "   "
    }
    Assert-True ($null -ne $whitespaceSet) "Real MemoryBox accepted whitespace-only input"

    $rememberButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    $rejected = Wait-Until -TimeoutSeconds 5 -Description "whitespace rejected feedback" -Condition {
        $value = $memoryStatusText.Current.Name
        if ($value -and $value.Length -gt 0) { return $value }
        return $null
    }
    Assert-True ($null -ne $rejected) "Desktop showed feedback for the whitespace-only Remember attempt"

    Start-Sleep -Milliseconds 300
    $preAudit = Invoke-RestMethod -Uri "${coreBaseUrl}v1/audit-events?limit=50" -Headers $authHeaders -TimeoutSec 5
    $preMemoryEvents = @($preAudit.events | Where-Object {
        $_.action -eq "memory_created" -or $_.action -eq "memory_create_requested"
    })
    Assert-True ($preMemoryEvents.Count -eq 0) "Whitespace-only Remember attempt created zero memory audit events"

    # -----------------------------------------------------------------------
    # Ordinary chat continues to create zero memory (Slice 4 must not
    # regress ADR-006 while adding the explicit memory path).
    # -----------------------------------------------------------------------

    Write-Host "Verifying ordinary chat still creates zero memory..."
    $composer = Find-ById -Root $root -AutomationId "ComposerBox"
    $sendButton = Find-ById -Root $root -AutomationId "SendButton"
    $messageList = Find-ById -Root $root -AutomationId "MessageList"
    $composerValuePattern = $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $composerValuePattern.SetValue($chatMessage)
    Wait-Until -TimeoutSeconds 5 -Description "composer text set" -Condition {
        $composerValuePattern.Current.Value -eq $chatMessage
    } | Out-Null
    $sendButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    $itemCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem)
    $chatRendered = Wait-Until -TimeoutSeconds $responseTimeoutSeconds -Description "chat response rendered" -Condition {
        $items = $messageList.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCond)
        if ($items.Count -ge 2) { return $items }
        return $null
    }
    Assert-True ($null -ne $chatRendered) "Ordinary chat message got a real Core response"

    Start-Sleep -Milliseconds 300
    $chatMemoryQuery = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString($chatMessage))" `
        -Headers $authHeaders -TimeoutSec 5
    Assert-True ($chatMemoryQuery.results.Count -eq 0) "Ordinary chat message created no matching durable memory"

    # -----------------------------------------------------------------------
    # Explicit Remember: the real proof.
    # -----------------------------------------------------------------------

    Write-Host "Explicit Remember of unique test content..."
    $memoryValuePattern.SetValue($memoryContent)
    $memorySet = Wait-Until -TimeoutSeconds 5 -Description "memory box content set" -Condition {
        $memoryValuePattern.Current.Value -eq $memoryContent
    }
    Assert-True ($null -ne $memorySet) "Real MemoryBox accepted the unique test content"

    $rememberButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    $remembered = Wait-Until -TimeoutSeconds $responseTimeoutSeconds -Description "Remembered. status" -Condition {
        $value = $memoryStatusText.Current.Name
        $script:lastUiDump = @("MemoryStatusText: [$value]")
        if ($value -eq "Remembered.") { return $true }
        return $null
    }
    Assert-True ($null -ne $remembered) "Desktop shows success feedback ('Remembered.') after explicit Remember"

    $memoryBoxCleared = $memoryValuePattern.Current.Value
    Assert-True ($memoryBoxCleared -eq "") "MemoryBox cleared after successful Remember"

    # -----------------------------------------------------------------------
    # Independent Core-side verification: query + audit trail.
    # -----------------------------------------------------------------------

    Write-Host "Verifying against Core's real, authenticated state..."
    Start-Sleep -Milliseconds 300
    $memoryQuery = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString($memoryContent))" `
        -Headers $authHeaders -TimeoutSec 5
    Assert-True ($memoryQuery.results.Count -eq 1) "Exactly one memory exists matching the unique test content (no duplicates)"
    if ($memoryQuery.results.Count -ge 1) {
        Assert-True ($memoryQuery.results[0].content -eq $memoryContent) `
            "Stored memory content exactly matches what was Remembered"
    }

    $auditResponse = Invoke-RestMethod -Uri "${coreBaseUrl}v1/audit-events?limit=50" -Headers $authHeaders -TimeoutSec 5
    $requestedEvents = @($auditResponse.events | Where-Object { $_.action -eq "memory_create_requested" })
    $createdEvents = @($auditResponse.events | Where-Object { $_.action -eq "memory_created" })
    Assert-True ($requestedEvents.Count -eq 1) "Exactly one memory_create_requested audit event recorded"
    Assert-True ($createdEvents.Count -eq 1) "Exactly one memory_created audit event recorded"
    if ($requestedEvents.Count -ge 1) {
        Assert-True ($requestedEvents[0].outcome -eq "success") "memory_create_requested audit event outcome is success"
        Assert-True ($requestedEvents[0].metadata.content_length -eq $memoryContent.Length) `
            "memory_create_requested audit content_length matches the Remembered content length"
    }
    if ($createdEvents.Count -ge 1) {
        Assert-True ($createdEvents[0].outcome -eq "success") "memory_created audit event outcome is success"
        Assert-True ($createdEvents[0].metadata.memory_id -eq $memoryQuery.results[0].id) `
            "memory_created audit event references the same memory id Core returned on query"
    }
}
finally {
    if ($appProcess) { Stop-Cleanly -Process $appProcess }
    if ($coreProcess) { Stop-Cleanly -Process $coreProcess }
    Get-EventSubscriber -ErrorAction SilentlyContinue | Where-Object {
        $_.SourceObject -eq $coreProcess
    } | Unregister-Event -ErrorAction SilentlyContinue
    foreach ($writer in $coreWriters) { try { $writer.Dispose() } catch {} }
    $coreWriters = @()
}

# ---------------------------------------------------------------------------
# Round 2: full restart of Desktop + Core against the SAME isolated
# REVA_DATA_DIR, proving persistence is real (SQLite-backed), not
# process-local in-memory state.
# ---------------------------------------------------------------------------

if ($failures.Count -eq 0) {
    try {
        Write-Host ""
        Write-Host "Restarting Core + Desktop against the SAME isolated data directory..."
        $coreProcess = Start-RealCore -StdoutLog $coreStdoutLog2 -StderrLog $coreStderrLog2

        $healthy2 = Wait-ForCoreHealthy
        Assert-True ($null -ne $healthy2) "Restarted Core became healthy within ${coreReadyTimeoutSeconds}s"
        if ($null -eq $healthy2) { Write-Diagnostics "Restarted Core never became healthy" }

        if ($null -ne $healthy2) {
            $tokenReady2 = Wait-Until -TimeoutSeconds 5 -Description "local_auth_token re-read" -Condition {
                if (Test-Path $tokenPath) { return (Get-Content $tokenPath -Raw).Trim() } else { return $null }
            }
            Assert-True ($null -ne $tokenReady2 -and $tokenReady2.Length -gt 0) "Local auth token file present after restart"
            $authHeaders2 = @{ Authorization = "Bearer $tokenReady2" }

            $appProcess = Start-RealDesktop
            Assert-True (-not $appProcess.HasExited) "Desktop application relaunched and is running"

            $root2 = Wait-ForMainWindow -Process $appProcess
            Assert-True ($null -ne $root2) "Located the restarted WinUI window via UI Automation"

            if ($null -ne $root2) {
                $connected2 = Wait-ForCoreConnected -Root $root2
                Assert-True ($null -ne $connected2) "Restarted desktop app shows real 'Core Connected' status"

                # ---------------------------------------------------------------
                # Recall through Core-side query directly (independent proof) ...
                # ---------------------------------------------------------------
                $persistedQuery = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString($memoryContent))" `
                    -Headers $authHeaders2 -TimeoutSec 5
                Assert-True ($persistedQuery.results.Count -eq 1) "Memory still exists via Core query after full restart"
                if ($persistedQuery.results.Count -ge 1) {
                    Assert-True ($persistedQuery.results[0].content -eq $memoryContent) `
                        "Persisted memory content is byte-for-byte the original value after restart"
                }

                # ---------------------------------------------------------------
                # ... AND through the real WinUI Search control.
                # ---------------------------------------------------------------
                $memoryBox2 = Find-ById -Root $root2 -AutomationId "MemoryBox"
                $searchButton2 = Find-ById -Root $root2 -AutomationId "SearchButton"
                $memorySearchResultText2 = Find-ById -Root $root2 -AutomationId "MemorySearchResultText"
                Assert-True ($null -ne $memoryBox2) "Found real MemoryBox control after restart"
                Assert-True ($null -ne $searchButton2) "Found real SearchButton control after restart"

                if ($memoryBox2 -and $searchButton2 -and $memorySearchResultText2) {
                    $searchValuePattern = $memoryBox2.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                    $searchValuePattern.SetValue("test-color-$testId")
                    Wait-Until -TimeoutSeconds 5 -Description "search box text set" -Condition {
                        $searchValuePattern.Current.Value -eq "test-color-$testId"
                    } | Out-Null

                    $searchButton2.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

                    $recalled = Wait-Until -TimeoutSeconds $responseTimeoutSeconds -Description "search result rendered" -Condition {
                        $value = $memorySearchResultText2.Current.Name
                        $script:lastUiDump = @("MemorySearchResultText: [$value]")
                        if ($value -and $value.Contains("cobalt")) { return $value }
                        return $null
                    }
                    Assert-True ($null -ne $recalled) "Real Search control recalled the persisted memory after restart, containing 'cobalt'"
                }
            }
        }
    } finally {
        if ($appProcess) { Stop-Cleanly -Process $appProcess }
        if ($coreProcess) { Stop-Cleanly -Process $coreProcess }
        Get-EventSubscriber -ErrorAction SilentlyContinue | Where-Object {
            $_.SourceObject -eq $coreProcess
        } | Unregister-Event -ErrorAction SilentlyContinue
        foreach ($writer in $coreWriters) { try { $writer.Dispose() } catch {} }
    }
} else {
    Write-Host ""
    Write-Host "Skipping restart round: round 1 already has failures." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Report result; preserve diagnostics on failure, clean up on success.
# ---------------------------------------------------------------------------

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== E2E PASSED: all assertions succeeded ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} else {
    Write-Diagnostics "one or more assertions failed"
    Write-Host ""
    Write-Host "=== E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
