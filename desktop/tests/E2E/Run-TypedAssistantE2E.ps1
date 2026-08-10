<#
.SYNOPSIS
    Real Windows E2E proof for the Phase 1B typed-assistant flow.

.DESCRIPTION
    Drives the ACTUAL compiled Reva.Desktop.exe (via System.Windows.Automation)
    against a REAL running REVA Core process, in an isolated temporary data
    directory and on a non-default loopback port. This is not a unit test,
    not a mocked-HTTP test, not a ViewModel test, and not a manually-clicked
    check  -  every control is located and driven through the real Windows UI
    Automation tree, and every claim is corroborated against REVA Core's own
    real, authenticated /v1/audit-events log.

    Flow proven:
        real Python Core (--serve, isolated data dir, isolated port)
        -> real built Reva.Desktop.exe
        -> real WinUI controls (ComposerBox, SendButton, MessageList)
        -> real POST /v1/messages (Bearer-token authenticated)
        -> real Core response (FakeLLMProvider's deterministic echo)
        -> rendered in the real WinUI ListView

.PARAMETER Configuration
    Build configuration to test. Default: Release.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File desktop\tests\E2E\Run-TypedAssistantE2E.ps1

.NOTES
    Exit code 0 = every assertion passed. Exit code 1 = a required
    condition failed, was missing, or timed out  -  diagnostics are printed
    before exit and the isolated data directory is preserved for inspection.
    On success, the isolated data directory is deleted.

    Never reads, prints, or logs the real local_auth_token value anywhere
    beyond using it as a Bearer header for verification requests this
    script itself makes.
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

# Non-default port: avoids colliding with a developer's own manually-running
# `python -m reva_core --serve` on the default 8756, and makes it obvious in
# any log/process list that this is the E2E instance, not a real one.
$testPort = 18756
$coreBaseUrl = "http://127.0.0.1:$testPort/"

$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$testMessage = "e2e typed assistant proof $testId"
$dataDir = Join-Path $env:TEMP "reva-e2e-$testId"

$coreReadyTimeoutSeconds = 20
$windowReadyTimeoutSeconds = 15
$responseTimeoutSeconds = 15

$coreStdoutLog = Join-Path $dataDir "core-stdout.log"
$coreStderrLog = Join-Path $dataDir "core-stderr.log"

$script:lastUiDump = $null
$coreProcess = $null
$appProcess = $null
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

function Get-UiTextDump {
    param([System.Windows.Automation.AutomationElement]$Root)
    if ($null -eq $Root) { return @("(no window)") }
    try {
        $cond = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Text)
        $elements = $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
        $lines = @()
        foreach ($el in $elements) { $lines += "TEXT: [$($el.Current.Name)]" }
        return $lines
    } catch {
        return @("(failed to read UI tree: $($_.Exception.Message))")
    }
}

function Find-ById {
    param([System.Windows.Automation.AutomationElement]$Root, [string]$AutomationId)
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $AutomationId)
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
}

function Write-Diagnostics {
    param([string]$Reason)
    Write-Host ""
    Write-Host "=== E2E FAILURE DIAGNOSTICS ($Reason) ===" -ForegroundColor Red
    if (Test-Path $coreStdoutLog) {
        Write-Host "--- Core stdout (last 40 lines) ---"
        Get-Content $coreStdoutLog -Tail 40 -ErrorAction SilentlyContinue
    }
    if (Test-Path $coreStderrLog) {
        Write-Host "--- Core stderr (last 40 lines) ---"
        Get-Content $coreStderrLog -Tail 40 -ErrorAction SilentlyContinue
    }
    if ($appProcess) {
        # $script:appWasAliveBeforeCleanup reflects state at the moment the
        # try block finished, BEFORE this script's own cleanup killed it -
        # querying $appProcess.HasExited here (after cleanup already ran)
        # would misreport a normal cleanup kill as an app crash.
        if ($script:appWasAliveBeforeCleanup -eq $true) {
            Write-Host "--- Desktop process was still running at failure time, PID $($appProcess.Id) (terminated by this script's cleanup) ---"
        } elseif ($script:appWasAliveBeforeCleanup -eq $false) {
            Write-Host "--- Desktop process had already exited on its own before cleanup, code $($appProcess.ExitCode) ---"
        } else {
            Write-Host "--- Desktop process state at failure time: unknown (failed before launch completed) ---"
        }
    } else {
        Write-Host "--- Desktop process was never started ---"
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

Write-Host "=== REVA Desktop E2E: typed assistant flow ===" -ForegroundColor Cyan
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

# Static invariant, cheap to assert here alongside the dynamic proof: no
# SQLite reference anywhere in the C# desktop source.
$sqliteHits = Get-ChildItem (Join-Path $repoRoot "desktop\src"), (Join-Path $repoRoot "desktop\tests") `
    -Recurse -Include *.cs, *.csproj -ErrorAction SilentlyContinue |
    Select-String -Pattern "sqlite" -SimpleMatch -CaseSensitive:$false
Assert-True ($null -eq $sqliteHits) "No SQLite reference anywhere in desktop/ (static check)"

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

try {
    # -----------------------------------------------------------------------
    # 1-3: isolated data dir (done above) + start real Core
    # -----------------------------------------------------------------------

    Write-Host "Starting real REVA Core (isolated, port $testPort)..."
    $coreProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
    $coreProcessInfo.FileName = $pythonExe
    $coreProcessInfo.Arguments = "-m reva_core --serve"
    $coreProcessInfo.WorkingDirectory = $repoRoot
    $coreProcessInfo.UseShellExecute = $false
    $coreProcessInfo.RedirectStandardOutput = $true
    $coreProcessInfo.RedirectStandardError = $true
    $coreProcessInfo.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $coreProcessInfo.EnvironmentVariables["REVA_API_PORT"] = "$testPort"

    $coreProcess = [System.Diagnostics.Process]::Start($coreProcessInfo)
    $coreStdoutWriter = [System.IO.StreamWriter]::new($coreStdoutLog)
    $coreStderrWriter = [System.IO.StreamWriter]::new($coreStderrLog)
    Register-ObjectEvent -InputObject $coreProcess -EventName OutputDataReceived -Action {
        if ($EventArgs.Data) { $Event.MessageData.WriteLine($EventArgs.Data) }
    } -MessageData $coreStdoutWriter | Out-Null
    Register-ObjectEvent -InputObject $coreProcess -EventName ErrorDataReceived -Action {
        if ($EventArgs.Data) { $Event.MessageData.WriteLine($EventArgs.Data) }
    } -MessageData $coreStderrWriter | Out-Null
    $coreProcess.BeginOutputReadLine()
    $coreProcess.BeginErrorReadLine()

    # -----------------------------------------------------------------------
    # 4: wait for /health readiness, bounded
    # -----------------------------------------------------------------------

    Write-Host "Waiting for Core readiness (timeout ${coreReadyTimeoutSeconds}s)..."
    $healthy = Wait-Until -TimeoutSeconds $coreReadyTimeoutSeconds -Description "GET /health healthy" -Condition {
        try {
            $response = Invoke-RestMethod -Uri "${coreBaseUrl}health" -TimeoutSec 2 -ErrorAction Stop
            return ($response.status -eq "healthy")
        } catch { return $false }
    }
    Assert-True ($null -ne $healthy) "Real Core became healthy within ${coreReadyTimeoutSeconds}s"
    if ($null -eq $healthy) { Write-Diagnostics "Core never became healthy"; exit 1 }

    $tokenPath = Join-Path $dataDir "local_auth_token"
    $tokenReady = Wait-Until -TimeoutSeconds 5 -Description "local_auth_token written" -Condition {
        if (Test-Path $tokenPath) { return (Get-Content $tokenPath -Raw).Trim() } else { return $null }
    }
    Assert-True ($null -ne $tokenReady -and $tokenReady.Length -gt 0) "Local auth token file provisioned by Core"
    $token = $tokenReady
    $authHeaders = @{ Authorization = "Bearer $token" }

    # -----------------------------------------------------------------------
    # 5: launch the real built desktop exe, pointed at the isolated Core
    # -----------------------------------------------------------------------

    Write-Host "Launching real Reva.Desktop.exe..."
    $appProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
    $appProcessInfo.FileName = $desktopExe
    $appProcessInfo.UseShellExecute = $false
    $appProcessInfo.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $appProcessInfo.EnvironmentVariables["REVA_DESKTOP_CORE_URL"] = $coreBaseUrl
    $appProcess = [System.Diagnostics.Process]::Start($appProcessInfo)
    Assert-True (-not $appProcess.HasExited) "Desktop application launched and is running"

    # -----------------------------------------------------------------------
    # 6: locate the real WinUI window
    # -----------------------------------------------------------------------

    Write-Host "Waiting for the real WinUI window (timeout ${windowReadyTimeoutSeconds}s)..."
    $root = Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "main window handle" -Condition {
        $appProcess.Refresh()
        if ($appProcess.MainWindowHandle -ne [IntPtr]::Zero) {
            return [System.Windows.Automation.AutomationElement]::FromHandle($appProcess.MainWindowHandle)
        }
        return $null
    }
    Assert-True ($null -ne $root) "Located the real WinUI window via UI Automation"
    if ($null -eq $root) { Write-Diagnostics "Main window never appeared"; exit 1 }

    $composer = Find-ById -Root $root -AutomationId "ComposerBox"
    $sendButton = Find-ById -Root $root -AutomationId "SendButton"
    $messageList = Find-ById -Root $root -AutomationId "MessageList"
    $statusText = Find-ById -Root $root -AutomationId "CoreStatusText"
    Assert-True ($null -ne $composer) "Found real ComposerBox control"
    Assert-True ($null -ne $sendButton) "Found real SendButton control"
    Assert-True ($null -ne $messageList) "Found real MessageList control"
    Assert-True ($null -ne $statusText) "Found real CoreStatusText control"

    # -----------------------------------------------------------------------
    # 7: verify "Core Connected"
    # -----------------------------------------------------------------------

    Write-Host "Waiting for real 'Core Connected' status..."
    $connected = Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "Core Connected status" -Condition {
        $value = $statusText.Current.Name
        $script:lastUiDump = Get-UiTextDump -Root $root
        if ($value -eq "Core Connected") { return $true }
        return $null
    }
    Assert-True ($null -ne $connected) "Desktop app shows real 'Core Connected' status"

    # -----------------------------------------------------------------------
    # 8-10: type unique test message, invoke real Send
    # -----------------------------------------------------------------------

    Write-Host "Typing test message and invoking real Send..."
    $valuePattern = $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $valuePattern.SetValue($testMessage)

    $composerHasText = Wait-Until -TimeoutSeconds 5 -Description "composer text set" -Condition {
        $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value -eq $testMessage
    }
    Assert-True ($null -ne $composerHasText) "Real ComposerBox accepted the unique test message"

    # No settle delay needed here: MainWindow.xaml.cs reads ComposerBox.Text
    # directly before acting on Send (SyncComposerTextFromTextBox), instead
    # of trusting x:Bind's TwoWay commit timing. That fix landed specifically
    # because InvokePattern.Invoke() (unlike a real mouse click) doesn't
    # reliably shift keyboard focus first, and x:Bind's TwoWay binding for
    # TextBox.Text only commits on LostFocus - confirmed by reproduction
    # while building this harness, and it affected the real Enter-to-send
    # path too (Enter never blurs the box), not just UI Automation.
    $sendButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    # -----------------------------------------------------------------------
    # 11-12: verify user message and assistant response appear
    # -----------------------------------------------------------------------

    Write-Host "Waiting for real Core response to render (timeout ${responseTimeoutSeconds}s)..."
    $itemCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem)

    $rendered = Wait-Until -TimeoutSeconds $responseTimeoutSeconds -Description "user + assistant messages rendered" -Condition {
        $items = $messageList.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCond)
        $script:lastUiDump = @($items | ForEach-Object { "ITEM: [$($_.Current.Name)]" })
        if ($items.Count -ge 2) { return $items }
        return $null
    }
    Assert-True ($null -ne $rendered) "Both user and assistant messages rendered in real MessageList"

    if ($rendered) {
        $itemTexts = @($rendered | ForEach-Object { $_.Current.Name })
        $userItem = $itemTexts | Where-Object { $_ -like "*Role = User*" -and $_ -like "*$testMessage*" }
        $assistantItem = $itemTexts | Where-Object {
            $_ -like "*Role = Assistant*" -and $_ -like "*Received: $testMessage*"
        }
        Assert-True ($null -ne $userItem) "Real user message text matches the unique test message"
        Assert-True ($null -ne $assistantItem) "Real assistant reply matches Core's documented deterministic echo (Received: <text>)"
    }

    $composerCleared = $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
    Assert-True ($composerCleared -eq "") "Composer cleared after send"

    # -----------------------------------------------------------------------
    # 13-14: prove the request crossed the real HTTP boundary + no memory
    # -----------------------------------------------------------------------

    Write-Host "Verifying against Core's real, authenticated audit trail..."
    Start-Sleep -Milliseconds 300 # audit write is synchronous server-side, but leave a small margin
    $auditResponse = Invoke-RestMethod -Uri "${coreBaseUrl}v1/audit-events?limit=50" -Headers $authHeaders -TimeoutSec 5
    $typedEvents = @($auditResponse.events | Where-Object { $_.action -eq "typed_request_received" })
    $expectedLength = $testMessage.Length

    Assert-True ($typedEvents.Count -eq 1) "Exactly one typed_request_received audit event recorded (real HTTP boundary proof)"
    if ($typedEvents.Count -ge 1) {
        Assert-True ($typedEvents[0].metadata.content_length -eq $expectedLength) `
            "Audit event content_length ($($typedEvents[0].metadata.content_length)) matches sent message length ($expectedLength)"
        Assert-True ($typedEvents[0].outcome -eq "success") "Audit event outcome is success"
    }

    $memoryEvents = @($auditResponse.events | Where-Object {
        $_.action -eq "memory_created" -or $_.action -eq "memory_create_requested"
    })
    Assert-True ($memoryEvents.Count -eq 0) "Ordinary typed message created zero memory audit events"

    $memoryQuery = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString($testMessage))" `
        -Headers $authHeaders -TimeoutSec 5
    Assert-True ($memoryQuery.results.Count -eq 0) "No memory exists matching the test message content"
}
finally {
    # Captured as the literal last thing before cleanup below forcibly
    # terminates the app, so Write-Diagnostics reports genuine pre-cleanup
    # state instead of "exited" purely because this script just killed it.
    if ($appProcess) {
        $script:appWasAliveBeforeCleanup = -not $appProcess.HasExited
    }

    # -------------------------------------------------------------------
    # 15: shut down cleanly, always  -  this block runs on success AND failure
    # -------------------------------------------------------------------

    Write-Host ""
    Write-Host "Cleaning up..."

    if ($appProcess -and -not $appProcess.HasExited) {
        try { $appProcess.Kill() } catch {}
        $appProcess.WaitForExit(5000) | Out-Null
    }

    if ($coreProcess -and -not $coreProcess.HasExited) {
        try { $coreProcess.Kill() } catch {}
        $coreProcess.WaitForExit(5000) | Out-Null
    }

    Get-EventSubscriber -ErrorAction SilentlyContinue | Where-Object {
        $_.SourceObject -eq $coreProcess
    } | Unregister-Event -ErrorAction SilentlyContinue

    if ($coreStdoutWriter) { $coreStdoutWriter.Dispose() }
    if ($coreStderrWriter) { $coreStderrWriter.Dispose() }
}

# ---------------------------------------------------------------------------
# 16: report result; preserve diagnostics on failure, clean up on success
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
