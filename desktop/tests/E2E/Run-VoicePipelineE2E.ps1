<#
.SYNOPSIS
    Real Slice 7 voice pipeline proof:
    generated speech fixture -> real STT -> authenticated message pipeline
    -> ADK memory recall -> real Chatterbox REVI speech WAV.

.NOTES
    This is an opt-in local hardware/runtime gate. It requires:
      - Ollama running with llama3.1:8b and nomic-embed-text pulled
      - faster-whisper model cached locally
      - REVA_TTS_PYTHON and REVA_TTS_REFERENCE_WAV supplied by env or param
      - Chatterbox model cached locally for the configured TTS Python env

    It never uses the developer's normal REVA_DATA_DIR and never commits or
    writes under the repository for generated audio.
#>

[CmdletBinding()]
param(
    [string]$Configuration = "Release",
    [string]$TtsPython = $env:REVA_TTS_PYTHON,
    [string]$TtsReferenceWav = $env:REVA_TTS_REFERENCE_WAV,
    [string]$TtsModelId = $(if ($env:REVA_TTS_MODEL_ID) { $env:REVA_TTS_MODEL_ID } else { "shankarpandala/chatterbox-telugu" }),
    [string]$TtsDevice = $(if ($env:REVA_TTS_DEVICE) { $env:REVA_TTS_DEVICE } else { "cuda" }),
    [string]$SttModel = $(if ($env:REVA_STT_MODEL) { $env:REVA_STT_MODEL } else { "Systran/faster-whisper-small" }),
    [string]$SttDevice = $(if ($env:REVA_STT_DEVICE) { $env:REVA_STT_DEVICE } else { "cpu" }),
    [string]$SttComputeType = $(if ($env:REVA_STT_COMPUTE_TYPE) { $env:REVA_STT_COMPUTE_TYPE } else { "int8" })
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$desktopExe = Join-Path $repoRoot "desktop\src\Reva.Desktop\bin\$Configuration\net10.0-windows10.0.19041.0\Reva.Desktop.exe"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$testPort = 18761
$coreBaseUrl = "http://127.0.0.1:$testPort/"
$ollamaBaseUrl = "http://127.0.0.1:11434"
$adkModel = "ollama_chat/llama3.1:8b"
$chatModel = "llama3.1:8b"
$embeddingModel = "nomic-embed-text"
$testId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$dataDir = Join-Path $env:TEMP "reva-e2e-voice-$testId"
$audioDir = Join-Path $env:TEMP "reva-e2e-voice-audio-$testId"
$coreStdoutLog = Join-Path $dataDir "core-stdout.log"
$coreStderrLog = Join-Path $dataDir "core-stderr.log"
$question = "Which project did I make for malware analysis?"
$malTraceMemory = "I built MalTrace to analyze malware behavior."
$failures = New-Object System.Collections.Generic.List[string]
$metrics = New-Object System.Collections.Generic.List[object]
$coreProcess = $null
$coreWriters = @()
$peakVramMiB = 0

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

function Test-OllamaModelPresent {
    param($Tags, [string]$ModelName)
    $models = @($Tags.models | ForEach-Object { $_.name })
    return [bool]($models | Where-Object { $_ -eq $ModelName -or $_ -like "$ModelName`:*" })
}

function Get-VramMiB {
    try {
        $value = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null | Select-Object -First 1
        if ($LASTEXITCODE -eq 0 -and $value) {
            $used = [int]($value.Trim())
            if ($used -gt $script:peakVramMiB) { $script:peakVramMiB = $used }
            return $used
        }
    } catch {}
    return $null
}

function Add-Metric {
    param([string]$Name, [double]$WallMs, [int]$AudioDurationMs = 0)
    $vram = Get-VramMiB
    $rtf = $null
    if ($AudioDurationMs -gt 0) { $rtf = [Math]::Round($WallMs / $AudioDurationMs, 3) }
    $metrics.Add([pscustomobject]@{
        name = $Name
        wall_ms = [Math]::Round($WallMs, 1)
        audio_duration_ms = $AudioDurationMs
        real_time_factor = $rtf
        observed_vram_mib = $vram
    })
}

function Measure-Step {
    param([string]$Name, [scriptblock]$Body)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $result = & $Body
    $sw.Stop()
    return [pscustomobject]@{ Result = $result; WallMs = $sw.Elapsed.TotalMilliseconds }
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
    Write-Host "=== VOICE E2E FAILURE DIAGNOSTICS ($Reason) ===" -ForegroundColor Red
    foreach ($log in @($coreStdoutLog, $coreStderrLog)) {
        if (Test-Path $log) {
            Write-Host "--- $log (last 80 lines) ---"
            Get-Content $log -Tail 80 -ErrorAction SilentlyContinue
        }
    }
    try {
        Write-Host "--- NVIDIA compute processes ---"
        & nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv 2>$null
    } catch {}
    Write-Host "Isolated data directory preserved for inspection: $dataDir"
    Write-Host "Temporary audio directory preserved for inspection: $audioDir"
}

function Invoke-SqliteScalar {
    param([string]$Sql)
    $dbPath = Join-Path $dataDir "reva.db"
    $code = "import sqlite3, sys; conn = sqlite3.connect(sys.argv[1]); print(conn.execute(sys.argv[2]).fetchone()[0]); conn.close()"
    $output = & $pythonExe -c $code $dbPath $Sql
    if ($LASTEXITCODE -ne 0) { throw "SQLite scalar query failed: $Sql" }
    return [int]($output | Select-Object -Last 1)
}

function Get-WavDurationMs {
    param([string]$Path)
    $code = @'
import struct
import sys
from pathlib import Path

data = Path(sys.argv[1]).read_bytes()
if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
    raise SystemExit("not a WAV file")
offset = 12
sample_rate = 0
block_align = 0
data_size = 0
while offset + 8 <= len(data):
    chunk_id = data[offset:offset + 4]
    chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
    chunk_start = offset + 8
    chunk_end = chunk_start + chunk_size
    if chunk_end > len(data):
        raise SystemExit("WAV chunk exceeds file size")
    if chunk_id == b"fmt ":
        audio_format, _, sample_rate, _, block_align, _ = struct.unpack_from("<HHIIHH", data, chunk_start)
        if audio_format not in {1, 3, 65534}:
            raise SystemExit(f"unsupported WAV format {audio_format}")
    elif chunk_id == b"data":
        data_size = chunk_size
    offset = chunk_end + (chunk_size % 2)
if sample_rate <= 0 or block_align <= 0 or data_size <= 0:
    raise SystemExit("incomplete WAV metadata")
print(int((data_size / block_align) / sample_rate * 1000))
'@
    $output = & $pythonExe -c $code $Path
    if ($LASTEXITCODE -ne 0) { throw "WAV duration read failed for $Path" }
    return [int]($output | Select-Object -Last 1)
}

function New-SpokenFixture {
    param([string]$Text, [string]$Path)
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $synth.SetOutputToWaveFile($Path)
        $synth.Speak($Text)
    } finally {
        $synth.Dispose()
    }
}

function Invoke-JsonPost {
    param([string]$Path, [hashtable]$Headers, [object]$Body, [int]$TimeoutSec = 120)
    Invoke-RestMethod -Uri "${coreBaseUrl}$Path" -Method Post -Headers $Headers `
        -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 5) -TimeoutSec $TimeoutSec
}

function Invoke-Speech {
    param([hashtable]$Headers, [string]$Text, [string]$Language, [string]$OutFile, [string]$MetricName)
    $step = Measure-Step $MetricName {
        Invoke-WebRequest -Uri "${coreBaseUrl}v1/voice/speech" -Method Post -Headers $Headers `
            -ContentType "application/json" -Body (@{ text = $Text; language = $Language } | ConvertTo-Json) `
            -OutFile $OutFile -TimeoutSec 240 | Out-Null
    }
    $durationMs = Get-WavDurationMs $OutFile
    Add-Metric -Name $MetricName -WallMs $step.WallMs -AudioDurationMs $durationMs
    Assert-True ((Test-Path $OutFile) -and ((Get-Item $OutFile).Length -gt 44)) "$MetricName produced a nonempty WAV"
    return $durationMs
}

function Start-RealCore {
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
    $info.EnvironmentVariables["REVA_ADK_TIMEOUT_SECONDS"] = "120"
    $info.EnvironmentVariables["REVA_EMBEDDING_MODEL"] = $embeddingModel
    $info.EnvironmentVariables["REVA_EMBEDDING_MODEL_API_BASE"] = $ollamaBaseUrl
    $info.EnvironmentVariables["REVA_TTS_ENABLED"] = "true"
    $info.EnvironmentVariables["REVA_TTS_PYTHON"] = $TtsPython
    $info.EnvironmentVariables["REVA_TTS_REFERENCE_WAV"] = $TtsReferenceWav
    $info.EnvironmentVariables["REVA_TTS_MODEL_ID"] = $TtsModelId
    $info.EnvironmentVariables["REVA_TTS_DEVICE"] = $TtsDevice
    $info.EnvironmentVariables["REVA_TTS_READY_TIMEOUT_SECONDS"] = "180"
    $info.EnvironmentVariables["REVA_TTS_SYNTHESIS_TIMEOUT_SECONDS"] = "240"
    $info.EnvironmentVariables["REVA_STT_MODEL"] = $SttModel
    $info.EnvironmentVariables["REVA_STT_DEVICE"] = $SttDevice
    $info.EnvironmentVariables["REVA_STT_COMPUTE_TYPE"] = $SttComputeType
    $info.EnvironmentVariables["REVA_STT_TIMEOUT_SECONDS"] = "120"

    $process = [System.Diagnostics.Process]::Start($info)
    $stdoutWriter = [System.IO.StreamWriter]::new($coreStdoutLog)
    $stderrWriter = [System.IO.StreamWriter]::new($coreStderrLog)
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

Write-Host "=== REVA Voice E2E: real STT -> ADK memory -> REVI TTS ===" -ForegroundColor Cyan
Write-Host "Test id: $testId"
Write-Host "Data dir: $dataDir"
Write-Host "Audio dir: $audioDir"
Write-Host "Core port: $testPort"
Write-Host "TTS model: $TtsModelId"
Write-Host "STT model: $SttModel ($SttDevice/$SttComputeType)"
Write-Host ""

if (-not (Test-Path $desktopExe)) { Write-Host "FAIL: Release Desktop build missing at $desktopExe" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $pythonExe)) { Write-Host "FAIL: Python venv missing at $pythonExe" -ForegroundColor Red; exit 1 }
if (-not $TtsPython -or -not (Test-Path $TtsPython)) { Write-Host "FAIL: REVA_TTS_PYTHON/TtsPython is missing" -ForegroundColor Red; exit 1 }
if (-not $TtsReferenceWav -or -not (Test-Path $TtsReferenceWav)) { Write-Host "FAIL: REVA_TTS_REFERENCE_WAV/TtsReferenceWav is missing" -ForegroundColor Red; exit 1 }

$listening = @(Get-NetTCPConnection -LocalPort $testPort -State Listen -ErrorAction SilentlyContinue)
if ($listening.Count -gt 0) { Write-Host "FAIL: port $testPort already in use" -ForegroundColor Red; exit 1 }

Write-Host "Checking Ollama and required models..."
$tags = Invoke-RestMethod -Uri "$ollamaBaseUrl/api/tags" -TimeoutSec 5 -ErrorAction Stop
if (-not (Test-OllamaModelPresent -Tags $tags -ModelName $chatModel)) { Write-Host "FAIL: missing $chatModel" -ForegroundColor Red; exit 1 }
if (-not (Test-OllamaModelPresent -Tags $tags -ModelName $embeddingModel)) { Write-Host "FAIL: missing $embeddingModel" -ForegroundColor Red; exit 1 }
Write-Host "  [PASS] Ollama reachable with required models" -ForegroundColor Green

Write-Host "Checking faster-whisper model cache..."
& $pythonExe -c "from faster_whisper import WhisperModel; WhisperModel('$SttModel', device='$SttDevice', compute_type='$SttComputeType', local_files_only=True); print('stt model cached')"
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: STT model is not cached locally" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
New-Item -ItemType Directory -Path $audioDir -Force | Out-Null

try {
    $questionWav = Join-Path $audioDir "question.wav"
    New-SpokenFixture -Text $question -Path $questionWav
    Assert-True (Test-Path $questionWav) "Generated neutral spoken English fixture outside the repository"

    $coreProcess = Start-RealCore
    $healthy = Wait-Until -TimeoutSeconds 40 -Description "Core healthy" -Condition {
        try { (Invoke-RestMethod -Uri "${coreBaseUrl}health" -TimeoutSec 2).status -eq "healthy" } catch { $false }
    }
    Assert-True ($null -ne $healthy) "Real Core became healthy with voice configured"
    if ($null -eq $healthy) { throw "Core did not become healthy" }

    $tokenPath = Join-Path $dataDir "local_auth_token"
    $token = Wait-Until -TimeoutSeconds 5 -Description "local_auth_token" -Condition {
        if (Test-Path $tokenPath) { return (Get-Content $tokenPath -Raw).Trim() }
        return $null
    }
    Assert-True ($null -ne $token -and $token.Length -gt 0) "Local auth token exists in isolated data dir"
    $authHeaders = @{ Authorization = "Bearer $token" }

    Invoke-JsonPost -Path "v1/memories" -Headers $authHeaders -Body @{ content = $malTraceMemory } -TimeoutSec 30 | Out-Null
    $memoryCountBefore = Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active'"
    Assert-True ($memoryCountBefore -eq 1) "Seeded exactly one durable MalTrace memory"

    $transcriptionStep = Measure-Step "english_transcription" {
        Invoke-RestMethod -Uri "${coreBaseUrl}v1/voice/transcriptions" -Method Post -Headers $authHeaders `
            -ContentType "audio/wav" -InFile $questionWav -TimeoutSec 120
    }
    Add-Metric -Name "english_transcription" -WallMs $transcriptionStep.WallMs
    $transcription = $transcriptionStep.Result
    Assert-True ($transcription.text -match "project" -and $transcription.text -match "malware") `
        "Real STT transcript preserves the question meaning: '$($transcription.text)'"
    Assert-True ($transcription.language -eq "en") "Real STT detected English"

    $messageStep = Measure-Step "adk_memory_answer" {
        Invoke-JsonPost -Path "v1/messages" -Headers $authHeaders -Body @{ content = $transcription.text } -TimeoutSec 180
    }
    Add-Metric -Name "adk_memory_answer" -WallMs $messageStep.WallMs
    $message = $messageStep.Result
    Assert-True ($message.reply -match "MalTrace") "ADK/memory response identifies MalTrace"

    $memoryCountAfter = Invoke-SqliteScalar "SELECT COUNT(*) FROM memories WHERE retention_state = 'active'"
    Assert-True ($memoryCountAfter -eq $memoryCountBefore) "Ordinary voice question did not create durable memory"

    $englishOut = Join-Path $audioDir "answer-en.wav"
    Invoke-Speech -Headers $authHeaders -Text $message.reply -Language "en" -OutFile $englishOut -MetricName "tts_cold_first_english" | Out-Null

    $warmOut = Join-Path $audioDir "warm-en.wav"
    Invoke-Speech -Headers $authHeaders -Text "Good morning." -Language "en" -OutFile $warmOut -MetricName "tts_warm_english" | Out-Null

    $teluguOut = Join-Path $audioDir "telugu.wav"
    Invoke-Speech -Headers $authHeaders -Text "నమస్తే. నేను రేవా." -Language "te" -OutFile $teluguOut -MetricName "tts_telugu" | Out-Null

    $teluguSttStep = Measure-Step "telugu_transcription" {
        Invoke-RestMethod -Uri "${coreBaseUrl}v1/voice/transcriptions" -Method Post -Headers $authHeaders `
            -ContentType "audio/wav" -InFile $teluguOut -TimeoutSec 120
    }
    Add-Metric -Name "telugu_transcription" -WallMs $teluguSttStep.WallMs
    Assert-True ($teluguSttStep.Result.text.Trim().Length -gt 0) "Real STT returned nonempty Telugu fixture transcript"

    for ($i = 1; $i -le 3; $i++) {
        $cycleMessage = Measure-Step "cycle_${i}_adk" {
            Invoke-JsonPost -Path "v1/messages" -Headers $authHeaders `
                -Body @{ content = "In one short sentence, which malware analysis project did I build?" } `
                -TimeoutSec 180
        }
        Add-Metric -Name "cycle_${i}_adk" -WallMs $cycleMessage.WallMs
        Assert-True ($cycleMessage.Result.reply -match "MalTrace") "Cycle $i ADK answer still identifies MalTrace"

        $cycleOut = Join-Path $audioDir "cycle-$i.wav"
        Invoke-Speech -Headers $authHeaders -Text $cycleMessage.Result.reply -Language "en" -OutFile $cycleOut -MetricName "cycle_${i}_tts" | Out-Null
    }

    $ollamaHealthy = $false
    try {
        $tagsAfter = Invoke-RestMethod -Uri "$ollamaBaseUrl/api/tags" -TimeoutSec 5 -ErrorAction Stop
        $ollamaHealthy = Test-OllamaModelPresent -Tags $tagsAfter -ModelName $chatModel
    } catch {}
    Assert-True $ollamaHealthy "Ollama remains healthy after ADK/TTS cycles"

    $auditToolCalls = Invoke-SqliteScalar "SELECT COUNT(*) FROM audit_events WHERE action = 'tool_invoked' AND metadata LIKE '%search_memory%'"
    Assert-True ($auditToolCalls -ge 1) "ADK search_memory tool invocation recorded"

    Write-Host ""
    Write-Host "=== Voice latency/GPU metrics ===" -ForegroundColor Cyan
    $metrics | Format-Table -AutoSize | Out-String | Write-Host
    Write-Host "Peak observed VRAM MiB: $peakVramMiB"
} catch {
    $failures.Add("Unexpected error: $($_.Exception.Message)")
    Write-Diagnostics "unexpected error"
} finally {
    if ($coreProcess) { Stop-Cleanly -Process $coreProcess }
    Get-EventSubscriber -ErrorAction SilentlyContinue | Where-Object {
        $_.SourceObject -eq $coreProcess
    } | Unregister-Event -ErrorAction SilentlyContinue
    foreach ($writer in $coreWriters) { try { $writer.Dispose() } catch {} }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "=== VOICE E2E PASSED: real STT -> ADK memory -> REVI TTS chain proven ===" -ForegroundColor Green
    Remove-Item -Path $dataDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $audioDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}

Write-Diagnostics "one or more assertions failed"
Write-Host ""
Write-Host "=== VOICE E2E FAILED: $($failures.Count) assertion(s) failed ===" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
exit 1
