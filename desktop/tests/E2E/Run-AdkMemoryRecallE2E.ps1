<#
.SYNOPSIS
    Real Windows E2E proof for Phase 1B Slice 5: durable memory recall
    through Google ADK orchestration, surviving a full process restart.

.DESCRIPTION
    Same real-process/UIA technique as Run-TypedAssistantE2E.ps1 (Slice 3)
    and Run-MemoryPersistenceE2E.ps1 (Slice 4), extended to prove the
    Slice 5 path end to end with NOTHING mocked or faked:

        real Python Core (--serve, REVA_ASSISTANT_ORCHESTRATOR=adk,
          isolated data dir, isolated port)
        -> real built Reva.Desktop.exe
        -> real WinUI Memory UI (explicit Remember)
        -> real authenticated POST /v1/memories
        -> durable memory persisted to real SQLite
        -> real process restart (Desktop AND Core killed and relaunched
           against the SAME isolated REVA_DATA_DIR)
        -> real WinUI chat composer (NOT Memory Search)
        -> real authenticated POST /v1/messages
        -> AdkAssistantOrchestrator -> real ADK Runner -> real RevaAgent
        -> real search_memory tool call -> real MemoryRepository query
        -> real local Ollama model (llama3.1:8b) produces the final answer
        -> real Desktop UI renders it

.PARAMETER Configuration
    Build configuration to test. Default: Release.

.NOTES
    Requires a running local Ollama server with `llama3.1:8b` pulled
    (`ollama pull llama3.1:8b`) - see docs/adr/ADR-017-google-adk-orchestration-dependency.md
    for why a local model, not a cloud credential, is this slice's E2E
    dependency. If Ollama is unreachable or the model is missing, this
    script fails fast in its precondition check rather than silently
    downgrading to a weaker gate.

    Exit code 0 = every assertion passed. Exit code 1 = a required
    condition failed, was missing, or timed out - diagnostics are printed
    before exit and the isolated data directory is preserved for
    inspection. On success, the isolated data directory is deleted.

    Never touches the developer's real REVA_DATA_DIR.
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

# Distinct from Slice 3 (18756) and Slice 4 (18757) so all three E2E
# scripts can run concurrently without colliding.
$testPort = 18758
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$ollamaBaseUrl = "http://127.0.0.1:11434"
$adkModel = "ollama_chat/llama3.1:8b"

$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$memoryContent = "My ADK test color is cobalt-$testId."
$recallQuestion = "What ADK test color did I ask you to remember?"
$dataDir = Join-Path $env:TEMP "reva-e2e-adk-$testId"

$coreReadyTimeoutSeconds = 20
$windowReadyTimeoutSeconds = 15
# Real local-model inference (tool call + second turn) has been observed
# up to ~30s warm, longer on a cold Ollama model load - generous but bounded.
$adkResponseTimeoutSeconds = 120

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
            # Transient during startup/inference - keep polling until timeout.
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
    $info.EnvironmentVariables["REVA_ASSISTANT_ORCHESTRATOR"] = "adk"
    $info.EnvironmentVariables["REVA_ADK_MODEL"] = $adkModel
    $info.EnvironmentVariables["REVA_ADK_MODEL_API_BASE"] = $ollamaBaseUrl

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
    # Real local-model inference (tool call + second turn) can exceed the
    # Desktop's 10s default HttpClient timeout (sized for Phase 1A/1B's
    # instant deterministic echo) - raise it for this real-model E2E only.
    $info.EnvironmentVariables["REVA_DESKTOP_REQUEST_TIMEOUT_SECONDS"] = "$adkResponseTimeoutSeconds"
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
            Write-Host "--- $log (last 60 lines) ---"
            Get-Content $log -Tail 60 -ErrorAction SilentlyContinue
        }
    }
    if ($script:lastUiDump) {
        Write-Host "--- Last known UI text dump ---"
        $script:lastUiDump | ForEach-Object { Write-Host $_ }
    }
    Write-Host "Isolated data directory preserved for inspection: $dataDir"
    Write-Host "(Never contains anything from your normal REVA data - this run used"
    Write-Host " an isolated directory and a non-default port, $($testPort).)"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

Write-Host "=== REVA Desktop E2E: ADK memory recall through restart ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host "Core port: $testPort"
Write-Host "ADK model: $adkModel via $ollamaBaseUrl"
Write-Host ""

if (-not (Test-Path $desktopExe)) {
    Write-Host "FAIL: Reva.Desktop.exe not found at $desktopExe" -ForegroundColor Red
    Write-Host "Build first: dotnet build desktop\Reva.Desktop.sln --configuration $Configuration"
    exit 1
}
if (-not (Test-Path $pythonExe)) {
    Write-Host "FAIL: Python venv not found at $pythonExe" -ForegroundColor Red
    exit 1
}

Write-Host "Checking real local Ollama server is reachable with the required model..."
$ollamaReachable = $false
$modelPresent = $false
try {
    $tags = Invoke-RestMethod -Uri "$ollamaBaseUrl/api/tags" -TimeoutSec 5 -ErrorAction Stop
    $ollamaReachable = $true
    $modelPresent = [bool]($tags.models | Where-Object { $_.name -eq "llama3.1:8b" })
} catch {
    $ollamaReachable = $false
}
if (-not $ollamaReachable) {
    Write-Host "FAIL (BLOCKER): Ollama is not reachable at $ollamaBaseUrl." -ForegroundColor Red
    Write-Host "This E2E requires a real local model - it will not silently fall back to a fake." -ForegroundColor Red
    Write-Host "Start Ollama and run: ollama pull llama3.1:8b" -ForegroundColor Red
    exit 1
}
if (-not $modelPresent) {
    Write-Host "FAIL (BLOCKER): Ollama is reachable but 'llama3.1:8b' is not pulled." -ForegroundColor Red
    Write-Host "Run: ollama pull llama3.1:8b" -ForegroundColor Red
    exit 1
}
Write-Host "  [PASS] Ollama reachable with llama3.1:8b present" -ForegroundColor Green

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

try {
    # -----------------------------------------------------------------------
    # Round 1: start real ADK-enabled Core + real Desktop
    # -----------------------------------------------------------------------

    Write-Host "Starting real REVA Core with REVA_ASSISTANT_ORCHESTRATOR=adk (isolated, port $testPort)..."
    $coreProcess = Start-RealCore -StdoutLog $coreStdoutLog -StderrLog $coreStderrLog

    $healthy = Wait-ForCoreHealthy
    Assert-True ($null -ne $healthy) "Real Core (ADK-enabled) became healthy within ${coreReadyTimeoutSeconds}s"
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

    $root = Wait-ForMainWindow -Process $appProcess
    Assert-True ($null -ne $root) "Located the real WinUI window via UI Automation"
    if ($null -eq $root) { Write-Diagnostics "Main window never appeared"; exit 1 }

    $connected = Wait-ForCoreConnected -Root $root
    Assert-True ($null -ne $connected) "Desktop app shows real 'Core Connected' status"

    # -----------------------------------------------------------------------
    # Explicit Remember through the Slice 4 Memory UI (unchanged by ADK).
    # -----------------------------------------------------------------------

    Write-Host "Explicit Remember of unique test content via the Memory UI..."
    $memoryBox = Find-ById -Root $root -AutomationId "MemoryBox"
    $rememberButton = Find-ById -Root $root -AutomationId "RememberButton"
    $memoryStatusText = Find-ById -Root $root -AutomationId "MemoryStatusText"
    Assert-True ($null -ne $memoryBox) "Found real MemoryBox control"
    Assert-True ($null -ne $rememberButton) "Found real RememberButton control"

    $memoryValuePattern = $memoryBox.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $memoryValuePattern.SetValue($memoryContent)
    Wait-Until -TimeoutSeconds 5 -Description "memory box content set" -Condition {
        $memoryValuePattern.Current.Value -eq $memoryContent
    } | Out-Null

    $rememberButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    $remembered = Wait-Until -TimeoutSeconds 15 -Description "Remembered. status" -Condition {
        if ($memoryStatusText.Current.Name -eq "Remembered.") { return $true }
        return $null
    }
    Assert-True ($null -ne $remembered) "Desktop shows success feedback ('Remembered.') after explicit Remember"

    # -----------------------------------------------------------------------
    # Independent Core-side verification: exactly one memory, correct audit.
    # -----------------------------------------------------------------------

    Start-Sleep -Milliseconds 300
    $memoryQuery = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString("cobalt-$testId"))" `
        -Headers $authHeaders -TimeoutSec 5
    Assert-True ($memoryQuery.results.Count -eq 1) "Exactly one durable memory exists after explicit Remember"
    if ($memoryQuery.results.Count -ge 1) {
        Assert-True ($memoryQuery.results[0].content -eq $memoryContent) "Stored memory content matches exactly"
    }

    $auditAfterRemember = Invoke-RestMethod -Uri "${coreBaseUrl}v1/audit-events?limit=100" -Headers $authHeaders -TimeoutSec 5
    $createRequested = @($auditAfterRemember.events | Where-Object { $_.action -eq "memory_create_requested" })
    $created = @($auditAfterRemember.events | Where-Object { $_.action -eq "memory_created" })
    Assert-True ($createRequested.Count -eq 1) "Exactly one memory_create_requested audit event recorded"
    Assert-True ($created.Count -eq 1) "Exactly one memory_created audit event recorded"
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
# Round 2: full restart of Core + Desktop against the SAME isolated
# REVA_DATA_DIR, then recall the memory through ORDINARY CHAT (not Memory
# Search) - proving the real Desktop -> Core -> ADK Runner -> RevaAgent ->
# search_memory -> MemoryRepository -> ADK answer -> Desktop UI path.
# ---------------------------------------------------------------------------

if ($failures.Count -eq 0) {
    try {
        Write-Host ""
        Write-Host "Restarting Core (ADK-enabled) + Desktop against the SAME isolated data directory..."
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

                # -------------------------------------------------------
                # Ordinary chat composer - NOT Memory Search - asks the
                # recall question. This is the real ADK path.
                # -------------------------------------------------------
                $composer = Find-ById -Root $root2 -AutomationId "ComposerBox"
                $sendButton = Find-ById -Root $root2 -AutomationId "SendButton"
                $messageList = Find-ById -Root $root2 -AutomationId "MessageList"
                Assert-True ($null -ne $composer) "Found real ComposerBox control after restart"
                Assert-True ($null -ne $sendButton) "Found real SendButton control after restart"

                if ($composer -and $sendButton -and $messageList) {
                    $composerValuePattern = $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                    $composerValuePattern.SetValue($recallQuestion)
                    Wait-Until -TimeoutSeconds 5 -Description "composer text set" -Condition {
                        $composerValuePattern.Current.Value -eq $recallQuestion
                    } | Out-Null

                    Write-Host "Asking through ordinary chat: '$recallQuestion'"
                    Write-Host "(waiting up to ${adkResponseTimeoutSeconds}s for real local-model inference + tool call...)"
                    $sendButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

                    $itemCond = New-Object System.Windows.Automation.PropertyCondition(
                        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                        [System.Windows.Automation.ControlType]::ListItem)
                    $answered = Wait-Until -TimeoutSeconds $adkResponseTimeoutSeconds -Description "ADK answer rendered" -Condition {
                        $items = $messageList.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCond)
                        $script:lastUiDump = @($items | ForEach-Object { "ITEM: [$($_.Current.Name)]" })
                        $assistantItems = $items | Where-Object { $_.Current.Name -like "*Role = Assistant*" }
                        if ($assistantItems) { return $assistantItems }
                        return $null
                    }
                    Assert-True ($null -ne $answered) "Real Desktop rendered an assistant response to the recall question"

                    if ($answered) {
                        $replyTexts = @($answered | ForEach-Object { $_.Current.Name })
                        $containsColor = $replyTexts | Where-Object { $_ -like "*cobalt-$testId*" }
                        Assert-True ($null -ne $containsColor) `
                            "Assistant response contains the exact remembered value 'cobalt-$testId' (real ADK recall proof)"
                    }
                }

                # -------------------------------------------------------
                # Independent Core-side verification of the ADK path.
                # -------------------------------------------------------
                Start-Sleep -Milliseconds 300
                $auditFinal = Invoke-RestMethod -Uri "${coreBaseUrl}v1/audit-events?limit=200" -Headers $authHeaders2 -TimeoutSec 5
                $orchestrationStarted = @($auditFinal.events | Where-Object { $_.action -eq "adk_orchestration_started" })
                $orchestrationCompleted = @($auditFinal.events | Where-Object { $_.action -eq "adk_orchestration_completed" })
                $toolInvoked = @($auditFinal.events | Where-Object {
                    $_.action -eq "tool_invoked" -and $_.metadata.tool_name -eq "search_memory"
                })
                $memoryQueryCompleted = @($auditFinal.events | Where-Object { $_.action -eq "memory_query_completed" })

                Assert-True ($orchestrationStarted.Count -ge 1) "adk_orchestration_started audit event recorded (ADK orchestration was exercised)"
                Assert-True ($orchestrationCompleted.Count -ge 1) "adk_orchestration_completed audit event recorded"
                Assert-True ($toolInvoked.Count -ge 1) "tool_invoked audit event recorded for search_memory (tool call proven independently of the UI)"
                Assert-True ($memoryQueryCompleted.Count -ge 1 -and $memoryQueryCompleted[0].metadata.result_count -ge 1) `
                    "memory_query_completed audit event shows at least one result (correct owner's memory was retrieved)"

                # Memory count still exactly 1 - ordinary chat recall wrote nothing.
                $finalMemoryQuery = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString("cobalt-$testId"))" `
                    -Headers $authHeaders2 -TimeoutSec 5
                Assert-True ($finalMemoryQuery.results.Count -eq 1) "Memory count is still exactly 1 after ordinary-chat recall (no duplicate, no implicit write)"

                $createRequestedFinal = @($auditFinal.events | Where-Object { $_.action -eq "memory_create_requested" })
                $createdFinal = @($auditFinal.events | Where-Object { $_.action -eq "memory_created" })
                Assert-True ($createRequestedFinal.Count -eq 1) "Still exactly one memory_create_requested total (zero new writes from ordinary chat)"
                Assert-True ($createdFinal.Count -eq 1) "Still exactly one memory_created total (zero new writes from ordinary chat)"
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
