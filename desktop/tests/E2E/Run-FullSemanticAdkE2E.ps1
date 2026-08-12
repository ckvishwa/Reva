<#
.SYNOPSIS
    Real Windows E2E proof of Slice 6 spec section 14's complete chain:
    no Core running -> auto-start -> Core Connected -> 500+ memory corpus
    -> weak-keyword semantic query -> ADK-grounded chat answer -> kill
    Core -> Desktop reconnects/relaunches -> same memory still retrievable.

.NOTES
    Requires: real Ollama running with nomic-embed-text AND llama3.1:8b
    pulled, REVA_ASSISTANT_ORCHESTRATOR=adk set in this script's
    environment for the launched Core (set explicitly below, not
    inherited, so this script's requirement is self-documenting).
    Port 18760. Seeds exactly 500 memories via real authenticated
    POST /v1/memories calls — this script is slow (real HTTP x500 plus
    production embed-on-write) and is not part of CI.
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

$testPort = 18760
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$ollamaBaseUrl = "http://127.0.0.1:11434"
$adkModel = "ollama_chat/llama3.1:8b"
$chatModel = "llama3.1:8b"
$embeddingModel = "nomic-embed-text"
$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$dataDir = Join-Path $env:TEMP "reva-e2e-full-semantic-adk-$testId"
$dbPath = Join-Path $dataDir "reva.db"
$corpusOutDir = Join-Path $env:TEMP "reva-e2e-corpus-$testId"
$windowReadyTimeoutSeconds = 15
$autoStartTimeoutSeconds = 40
$corpusSeedTimeoutSeconds = 600  # 500 real HTTP creates + production embed-on-write
$adkResponseTimeoutSeconds = 120  # real llama3.1:8b inference + ADK tool call

$script:lastUiDump = $null
$script:testCoreProcessIds = New-Object 'System.Collections.Generic.HashSet[int]'
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
    if ($Process -and -not $Process.HasExited) { try { $Process.Kill() } catch {}; $Process.WaitForExit($TimeoutMs) | Out-Null }
}

function Get-ListeningProcessIdsOnTestPort {
    try {
        @(Get-NetTCPConnection -LocalPort $testPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        @()
    }
}

function Get-TestCoreProcesses {
    $candidateIds = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($processIdCandidate in (Get-ListeningProcessIdsOnTestPort)) { [void]$candidateIds.Add([int]$processIdCandidate) }
    foreach ($processIdCandidate in $script:testCoreProcessIds) { [void]$candidateIds.Add([int]$processIdCandidate) }
    if ($appProcess -and -not $appProcess.HasExited) {
        $children = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -eq $appProcess.Id -and $_.CommandLine -and $_.CommandLine.Contains("reva_core") }
        foreach ($child in $children) { [void]$candidateIds.Add([int]$child.ProcessId) }
    }

    foreach ($processIdCandidate in $candidateIds) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processIdCandidate" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -and $proc.CommandLine.Contains("reva_core")) { $proc }
    }
}

function Remember-TestCoreProcesses {
    foreach ($proc in (Get-TestCoreProcesses)) { [void]$script:testCoreProcessIds.Add([int]$proc.ProcessId) }
}

function Stop-TestCoreProcesses {
    foreach ($proc in (Get-TestCoreProcesses)) {
        try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
}

function Invoke-SqliteScalar {
    param([string]$Sql)
    if (-not (Test-Path $dbPath)) { throw "SQLite database not found at $dbPath" }
    $code = "import sqlite3, sys; conn = sqlite3.connect(sys.argv[1]); print(conn.execute(sys.argv[2]).fetchone()[0]); conn.close()"
    $output = & $pythonExe -c $code $dbPath $Sql
    if ($LASTEXITCODE -ne 0) { throw "SQLite scalar query failed: $Sql" }
    return [int]($output | Select-Object -Last 1)
}

function Test-OllamaModelPresent {
    param($Tags, [string]$ModelName)
    $models = @($Tags.models | ForEach-Object { $_.name })
    return [bool]($models | Where-Object { $_ -eq $ModelName -or $_ -like "$ModelName`:*" })
}

function Write-Diagnostics {
    param([string]$Reason)
    Write-Host ""
    Write-Host "=== E2E FAILURE DIAGNOSTICS ($Reason) ===" -ForegroundColor Red
    if ($script:lastUiDump) {
        Write-Host "--- Last known UI text dump ---"
        $script:lastUiDump | ForEach-Object { Write-Host $_ }
    }
    $testCoreProcesses = @(Get-TestCoreProcesses)
    if ($testCoreProcesses.Count -gt 0) {
        Write-Host "--- Test-associated Core process(es) ---"
        $testCoreProcesses | ForEach-Object { Write-Host "PID $($_.ProcessId): $($_.CommandLine)" }
    }
    if (Test-Path $dbPath) {
        try {
            Write-Host "--- Isolated database summary ---"
            Write-Host "Active memories: $(Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active'")"
            Write-Host "Embedding rows: $(Invoke-SqliteScalar "SELECT COUNT(*) FROM memory_embeddings WHERE model_id = '$embeddingModel'")"
            Write-Host "ADK starts: $(Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'adk_orchestration_started'")"
            Write-Host "search_memory tool calls: $(Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'tool_invoked' AND metadata LIKE '%search_memory%'")"
        } catch {
            Write-Host "Could not read isolated database diagnostics: $($_.Exception.Message)"
        }
    }
    Write-Host "Isolated data directory preserved for inspection: $dataDir"
    Write-Host "Temporary corpus directory: $corpusOutDir"
}

Write-Host "=== REVA Desktop E2E: full automatic-startup + semantic + ADK + reconnect chain ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host "Core port: $testPort"
Write-Host "ADK model: $adkModel via $ollamaBaseUrl"
Write-Host "Embedding model: $embeddingModel via $ollamaBaseUrl"
Write-Host ""

if (-not (Test-Path $desktopExe)) {
    Write-Host "FAIL: Reva.Desktop.exe not found at $desktopExe" -ForegroundColor Red
    Write-Host "Build first: dotnet build desktop\Reva.Desktop.sln --configuration $Configuration"
    exit 1
}
if (-not (Test-Path $pythonExe)) { Write-Host "FAIL: Python venv not found at $pythonExe" -ForegroundColor Red; exit 1 }

$listeningPids = @(Get-ListeningProcessIdsOnTestPort)
if ($listeningPids.Count -gt 0) {
    Write-Host "FAIL: port $testPort is already in use by PID(s): $($listeningPids -join ', ')" -ForegroundColor Red
    Write-Host "Cannot prove a cold Desktop-owned Core auto-start." -ForegroundColor Red
    exit 1
}

Write-Host "Checking real local Ollama server and required models..."
$ollamaTags = $null
try { $ollamaTags = Invoke-RestMethod -Uri "$ollamaBaseUrl/api/tags" -TimeoutSec 5 -ErrorAction Stop } catch {}
if ($null -eq $ollamaTags) {
    Write-Host "FAIL (BLOCKER): Ollama is not reachable at $ollamaBaseUrl." -ForegroundColor Red
    exit 1
}
if (-not (Test-OllamaModelPresent -Tags $ollamaTags -ModelName $chatModel)) {
    Write-Host "FAIL (BLOCKER): Ollama is reachable but '$chatModel' is not pulled." -ForegroundColor Red
    Write-Host "Run: ollama pull $chatModel" -ForegroundColor Red
    exit 1
}
if (-not (Test-OllamaModelPresent -Tags $ollamaTags -ModelName $embeddingModel)) {
    Write-Host "FAIL (BLOCKER): Ollama is reachable but '$embeddingModel' is not pulled." -ForegroundColor Red
    Write-Host "Run: ollama pull $embeddingModel" -ForegroundColor Red
    exit 1
}
try {
    $embeddingProbe = Invoke-RestMethod -Uri "$ollamaBaseUrl/api/embeddings" -Method Post `
        -ContentType "application/json" -Body (@{ model = $embeddingModel; prompt = "reva e2e embedding preflight" } | ConvertTo-Json) `
        -TimeoutSec 30 -ErrorAction Stop
    if (-not $embeddingProbe.embedding -or $embeddingProbe.embedding.Count -eq 0) { throw "empty embedding returned" }
} catch {
    Write-Host "FAIL (BLOCKER): '$embeddingModel' did not return a real embedding: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host "  [PASS] Ollama reachable with $chatModel and $embeddingModel present" -ForegroundColor Green

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

try {
    # --- Phase 1: automatic startup, no pre-started Core ---
    Write-Host "Phase 1: launching Reva.Desktop.exe with no Core pre-started (ADK mode)..."
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $desktopExe
    $info.UseShellExecute = $false
    $info.EnvironmentVariables["REVA_DATA_DIR"] = $dataDir
    $info.EnvironmentVariables["REVA_DESKTOP_CORE_URL"] = $coreBaseUrl
    $info.EnvironmentVariables["REVA_DESKTOP_REQUEST_TIMEOUT_SECONDS"] = "$adkResponseTimeoutSeconds"
    $info.EnvironmentVariables["REVA_CORE_REPO_ROOT"] = "$repoRoot"
    $info.EnvironmentVariables["REVA_ASSISTANT_ORCHESTRATOR"] = "adk"
    $info.EnvironmentVariables["REVA_ADK_MODEL"] = $adkModel
    $info.EnvironmentVariables["REVA_ADK_MODEL_API_BASE"] = $ollamaBaseUrl
    $info.EnvironmentVariables["REVA_ADK_TIMEOUT_SECONDS"] = "$adkResponseTimeoutSeconds"
    $info.EnvironmentVariables["REVA_EMBEDDING_MODEL"] = $embeddingModel
    $info.EnvironmentVariables["REVA_EMBEDDING_MODEL_API_BASE"] = $ollamaBaseUrl
    $appProcess = [System.Diagnostics.Process]::Start($info)
    Assert-True (-not $appProcess.HasExited) "Desktop application launched and is running"

    $root = Wait-Until -TimeoutSeconds $windowReadyTimeoutSeconds -Description "main window handle" -Condition {
        $appProcess.Refresh()
        if ($appProcess.MainWindowHandle -ne [IntPtr]::Zero) { return [System.Windows.Automation.AutomationElement]::FromHandle($appProcess.MainWindowHandle) }
        return $null
    }
    Assert-True ($null -ne $root) "Located the real WinUI window"
    if ($null -eq $root) { Write-Diagnostics "main window never appeared"; exit 1 }

    $statusText = Find-ById -Root $root -AutomationId "CoreStatusText"
    Assert-True ($null -ne $statusText) "Found real CoreStatusText control"
    if ($null -eq $statusText) { Write-Diagnostics "CoreStatusText control not found"; exit 1 }
    $connected = Wait-Until -TimeoutSeconds $autoStartTimeoutSeconds -Description "Core Connected (auto-started)" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Connected") { return $true }
        return $null
    }
    Assert-True ($null -ne $connected) "Automatic startup reached Core Connected"
    if ($null -eq $connected) { Write-Diagnostics "Core never reached Connected"; exit 1 }
    Remember-TestCoreProcesses
    Assert-True (@(Get-TestCoreProcesses).Count -ge 1) "Identified the Desktop-owned test Core process on port $testPort"

    $tokenPath = Join-Path $dataDir "local_auth_token"
    $token = Wait-Until -TimeoutSeconds 5 -Description "local_auth_token written" -Condition {
        if (Test-Path $tokenPath) { return (Get-Content $tokenPath -Raw).Trim() }
        return $null
    }
    Assert-True ($null -ne $token -and $token.Length -gt 0) "Core-created local_auth_token exists in the isolated data directory"
    if ($null -eq $token -or $token.Length -eq 0) { Write-Diagnostics "local_auth_token was not created"; exit 1 }
    $authHeaders = @{ Authorization = "Bearer $token" }

    # --- Phase 2: seed a real >=500 memory corpus via authenticated API ---
    Write-Host "Phase 2: seeding >=500 memory corpus via real POST /v1/memories (this is slow)..."
    $corpusExitCode = 0
    Push-Location $repoRoot
    try {
        & $pythonExe -m scripts.semantic_eval.build_corpus --total-size 500 --output-dir $corpusOutDir
        $corpusExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($corpusExitCode -ne 0) { throw "build_corpus.py failed with exit code $corpusExitCode" }
    $corpus = Get-Content (Join-Path $corpusOutDir "corpus.json") -Raw | ConvertFrom-Json
    $allContent = @($corpus.canonical) + @($corpus.distractors)
    $targetMemory = "MalTrace analyzes malware behavior."
    Assert-True ($allContent -contains $targetMemory) "Corpus includes the canonical durable MalTrace malware-analysis memory"

    $seeded = 0
    foreach ($content in $allContent) {
        try {
            $seedCorrelationId = [Guid]::NewGuid().ToString()
            Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories" -Method Post -Headers $authHeaders `
                -ContentType "application/json" -Body (@{ content = $content; correlation_id = $seedCorrelationId } | ConvertTo-Json) -TimeoutSec 10 | Out-Null
            $seeded++
        } catch {
            Write-Host "  [WARN] failed to seed one memory: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Assert-True ($seeded -ge 500) "Seeded at least 500 durable memories via real authenticated API ($seeded actually seeded)"
    if ($seeded -lt 500) { Write-Diagnostics "fewer than 500 memories were seeded"; exit 1 }
    $memoryCountAfterSeed = Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active'"
    Assert-True ($memoryCountAfterSeed -eq $seeded) "Isolated database active memory count matches successful seed count ($memoryCountAfterSeed)"
    $embeddingCountAfterSeed = Invoke-SqliteScalar "SELECT COUNT(*) FROM memory_embeddings WHERE model_id = '$embeddingModel'"
    Assert-True ($embeddingCountAfterSeed -eq $memoryCountAfterSeed) "All seeded memories have production embed-on-write rows for $embeddingModel ($embeddingCountAfterSeed)"
    if ($embeddingCountAfterSeed -ne $memoryCountAfterSeed) { Write-Diagnostics "not all seeded memories were embedded on write"; exit 1 }

    # --- Phase 3: weak-keyword semantic query via chat, grounded in ADK ---
    Write-Host "Phase 3: ordinary chat question requiring durable memory (weak keyword overlap)..."
    $countBefore = Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active'"
    $createdAuditBefore = Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'memory_created'"
    $composer = Find-ById -Root $root -AutomationId "ComposerBox"
    $sendButton = Find-ById -Root $root -AutomationId "SendButton"
    $messageList = Find-ById -Root $root -AutomationId "MessageList"
    Assert-True ($null -ne $composer) "Found real ComposerBox control"
    Assert-True ($null -ne $sendButton) "Found real SendButton control"
    Assert-True ($null -ne $messageList) "Found real MessageList control"
    if ($null -eq $composer -or $null -eq $sendButton -or $null -eq $messageList) {
        Write-Diagnostics "required chat UI controls were not found"
        exit 1
    }
    $composerValuePattern = $composer.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $question = "Which project did I make for malware analysis?"
    $composerValuePattern.SetValue($question)
    Wait-Until -TimeoutSeconds 5 -Description "composer text set" -Condition { $composerValuePattern.Current.Value -eq $question } | Out-Null
    $sendButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()

    $itemCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::ListItem)
    $answerFound = Wait-Until -TimeoutSeconds $adkResponseTimeoutSeconds -Description "ADK-grounded reply mentioning MalTrace" -Condition {
        $items = $messageList.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCond)
        $texts = @($items | ForEach-Object { $_.Current.Name })
        $script:lastUiDump = $texts
        $assistantTexts = @($texts | Where-Object { $_ -like "*Role = Assistant*" })
        if (($assistantTexts -join " ") -match "MalTrace") { return $true }
        return $null
    }
    Assert-True ($null -ne $answerFound) "ADK-grounded chat answer mentions 'MalTrace' for a weak-keyword-overlap question"

    Start-Sleep -Milliseconds 500
    $countAfter = Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active'"
    $createdAuditAfter = Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'memory_created'"
    Assert-True ($countAfter -eq $countBefore) "Memory count before/after ordinary chat is unchanged ($countBefore)"
    Assert-True ($createdAuditAfter -eq $createdAuditBefore) "memory_created audit count is unchanged by ordinary chat"
    Assert-True ((Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'adk_orchestration_started'") -ge 1) `
        "adk_orchestration_started audit event recorded (real ADK orchestration)"
    Assert-True ((Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'adk_orchestration_completed'") -ge 1) `
        "adk_orchestration_completed audit event recorded"
    Assert-True ((Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'tool_invoked' AND metadata LIKE '%search_memory%'") -ge 1) `
        "search_memory tool_invoked audit event recorded (real memory tool path)"
    Assert-True ((Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'memory_query_completed'") -ge 1) `
        "memory_query_completed audit event recorded after ADK memory search"

    # --- Phase 4: kill Core, prove Desktop shows Unavailable then reconnects ---
    Write-Host "Phase 4: killing Core process, expecting Desktop to detect and reconnect..."
    $coreProcessesToKill = @(Get-TestCoreProcesses)
    Assert-True ($coreProcessesToKill.Count -ge 1) "Found test-associated Core process(es) to kill without touching unrelated Core processes"
    $killedCoreProcessIds = @($coreProcessesToKill | ForEach-Object { [int]$_.ProcessId })
    foreach ($proc in $coreProcessesToKill) {
        try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop } catch {}
    }
    $unavailable = Wait-Until -TimeoutSeconds 30 -Description "Core Unavailable detected after kill" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Unavailable") { return $true }
        return $null
    }
    Assert-True ($null -ne $unavailable) "Desktop detected Core going away (Core Unavailable shown)"

    $reconnected = Wait-Until -TimeoutSeconds 60 -Description "Core Connected after relaunch" -Condition {
        $script:lastUiDump = @("CoreStatusText: [$($statusText.Current.Name)]")
        if ($statusText.Current.Name -eq "Core Connected") { return $true }
        return $null
    }
    Assert-True ($null -ne $reconnected) "Desktop's reconnect monitor relaunched Core and reached Core Connected again"
    Remember-TestCoreProcesses
    $currentCoreProcesses = @(Get-TestCoreProcesses)
    Assert-True (($currentCoreProcesses | Where-Object { $killedCoreProcessIds -notcontains [int]$_.ProcessId }).Count -ge 1) `
        "Reconnect is backed by a newly launched test-associated Core process"

    # --- Phase 5: same durable memory still retrievable after relaunch ---
    if ($reconnected) {
        Start-Sleep -Milliseconds 500
        $tokenAfter = (Get-Content $tokenPath -Raw).Trim()
        $authHeadersAfter = @{ Authorization = "Bearer $tokenAfter" }
        $persistedExactCount = Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active' AND content = '$targetMemory'"
        Assert-True ($persistedExactCount -eq 1) "The exact canonical MalTrace memory row still exists after Core relaunch"
        $persisted = Invoke-RestMethod -Uri "${coreBaseUrl}v1/memories?q=$([Uri]::EscapeDataString('MalTrace'))&limit=100" -Headers $authHeadersAfter -TimeoutSec 5
        $persistedContents = @($persisted.results | ForEach-Object { $_.content })
        $script:lastUiDump = @("Post-restart Core query results for 'MalTrace':") + $persistedContents
        $persistedMatches = @($persisted.results | Where-Object { $_.content -eq $targetMemory })
        Assert-True ($persistedMatches.Count -eq 1) `
            "The MalTrace memory is still retrievable through Core after relaunch (restart persistence proof)"
        $memoryCountAfterRestart = Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active'"
        Assert-True ($memoryCountAfterRestart -eq $countBefore) "Durable memory count remains unchanged after Core restart ($memoryCountAfterRestart)"
    }
} catch {
    $message = $_.Exception.Message
    Write-Host "  [FAIL] Unexpected E2E error: $message" -ForegroundColor Red
    $failures.Add("Unexpected E2E error: $message")
    Write-Diagnostics "unexpected error"
} finally {
    if ($appProcess) { Stop-Cleanly -Process $appProcess }
    Stop-TestCoreProcesses
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== E2E PASSED: full auto-startup + semantic + ADK + reconnect chain proven with real processes ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $corpusOutDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} else {
    Write-Diagnostics "one or more assertions failed"
    Write-Host ""
    Write-Host "=== E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
