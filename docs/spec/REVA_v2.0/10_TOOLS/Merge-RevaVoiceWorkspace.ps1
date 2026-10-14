<#
.SYNOPSIS
  Reorganizes "F:\Voice FOR Reva" into a clean REVA layout: heavy assets in an asset root
  (models, datasets, runs), code/configs copied into the REVA repo, nothing deleted.

.DESCRIPTION
  Dry run by default: prints and saves the plan, changes nothing. Add -Apply to execute.
  - Assets are MOVED within the same drive (source and asset root must share a drive).
  - Code and small text files are COPIED into the repo (never overwrites; conflicts are logged).
  - Python environments, vendored engine sources, temp dirs and duplicates go to _to-delete\ (you delete later).
  - Files named after real people go to _excluded\ and never enter the repo or a dataset.
  - Before moving each environment, its packages are frozen to tools\voice-lab\envs\<env>.requirements.txt.
  - Writes assets.manifest.json (schema: 08_CONTRACTS/voice-asset-manifest.schema.json) and a per-folder
    SHA-256 list. Fill in "source", "license" and "provenance_status" for every entry afterwards.
  Works in Windows PowerShell 5.1 and PowerShell 7. Run it as a FILE (do not paste it into the console).
  Safe to re-run: finished steps are detected and skipped; failures are logged and the rest continues.

.EXAMPLE
  .\Merge-RevaVoiceWorkspace.ps1                      # dry run, writes reva-voice-merge-plan.csv
  .\Merge-RevaVoiceWorkspace.ps1 -Apply               # execute
  .\Merge-RevaVoiceWorkspace.ps1 -Apply -SkipHash     # execute without hashing large files
#>
[CmdletBinding()]
param(
    [string]$Source    = 'F:\Voice FOR Reva',
    [string]$AssetRoot = 'F:\reva-assets',
    [string]$RepoRoot  = 'D:\Projects\Reva',
    [switch]$Apply,
    [switch]$SkipHash,
    [int]$MaxRepoFileKB = 1024
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$SEP = [System.IO.Path]::DirectorySeparatorChar
function P([string]$rel) { return $rel.Replace('\', $SEP) }
function Test-SkippedPath([string]$path) {
    foreach ($d in $skipCodeDirs) {
        if ($path -like ('*' + $SEP + $d + $SEP + '*')) { return $true }
    }
    return $false
}
function Get-Root([string]$p) {
    $full = [System.IO.Path]::GetFullPath($p)
    return [System.IO.Path]::GetPathRoot($full).ToUpperInvariant()
}

if (-not (Test-Path -LiteralPath $Source)) { throw "Source not found: $Source" }
if ((Get-Root $Source) -ne (Get-Root $AssetRoot)) {
    throw "Source ($Source) and AssetRoot ($AssetRoot) must be on the same drive so assets are moved, not copied."
}
$repoAvailable = Test-Path -LiteralPath $RepoRoot
if (-not $repoAvailable) { Write-Warning "RepoRoot not found ($RepoRoot). Code copies will be planned but skipped." }

# ---------- rules (first match wins) ----------
$dirRules = @(
    @{ Name = '.claude';              Dest = '_archive\claude-config';               Kind = 'other' }
    @{ Name = 'chatterbox-env';       Dest = '_to-delete\envs\chatterbox-env';       Kind = 'env' }
    @{ Name = 'chatterbox-v3-env';    Dest = '_to-delete\envs\chatterbox-v3-env';    Kind = 'env' }
    @{ Name = 'xtts-env';             Dest = '_to-delete\envs\xtts-env';             Kind = 'env' }
    @{ Name = 'xtts-env310';          Dest = '_to-delete\envs\xtts-env310';          Kind = 'env' }
    @{ Name = 'chatterbox-v3-src';    Dest = '_to-delete\vendor-src\chatterbox-v3-src'; Kind = 'vendor' }
    @{ Name = 'indextts2-src';        Dest = '_to-delete\vendor-src\indextts2-src';  Kind = 'vendor' }
    @{ Name = 'tmpdir';               Dest = '_to-delete\tmpdir';                    Kind = 'other' }
    @{ Name = 'revi-checkpoints';     Dest = 'models\tts\revi\checkpoints';          Kind = 'tts_checkpoint' }
    @{ Name = 'revi-dataset';         Dest = 'datasets\revi\dataset';                Kind = 'dataset' }
    @{ Name = 'revi-synthetic-15min'; Dest = 'datasets\revi\synthetic-15min';        Kind = 'dataset' }
    @{ Name = 'style-bank';           Dest = 'datasets\revi\style-bank';             Kind = 'dataset' }
    @{ Name = 'Voices';               Dest = 'datasets\reference-voices';            Kind = 'reference_audio' }
    @{ Name = 'revi-model-bakeoff';   Dest = 'runs\revi-model-bakeoff';              Kind = 'run_output'; CodeTo = 'tools\voice-lab\revi-model-bakeoff' }
    @{ Name = 'revi-prosody-study';   Dest = 'runs\revi-prosody-study';              Kind = 'run_output'; CodeTo = 'tools\voice-lab\revi-prosody-study' }
    @{ Name = 'revi-reference-study'; Dest = 'runs\revi-reference-study';            Kind = 'run_output'; CodeTo = 'tools\voice-lab\revi-reference-study' }
    @{ Name = 'revi-timbre-study';    Dest = 'runs\revi-timbre-study';               Kind = 'run_output'; CodeTo = 'tools\voice-lab\revi-timbre-study' }
    @{ Name = 'voice-eval';           Dest = 'runs\voice-eval';                      Kind = 'eval_audio'; CodeTo = 'tests\voice-evals' }
)
$fileRules = @(
    @{ Pattern = '* (1).*';           Dest = '_to-delete\duplicates';                Kind = 'other' }
    @{ Pattern = '*Lana*Del*Rey*';    Dest = '_excluded\named-references';           Kind = 'excluded' }
    @{ Pattern = 'Angela-white*';     Dest = '_excluded\named-references';           Kind = 'excluded' }
    @{ Pattern = '*.py';              Dest = '_archive\root-scripts';                Kind = 'other'; CodeTo = 'tools\voice-lab\experiments' }
    @{ Pattern = 'revi-*.wav';        Dest = 'runs\loose-samples';                   Kind = 'run_output' }
    @{ Pattern = '*-controlled.wav';  Dest = 'runs\loose-samples';                   Kind = 'run_output' }
)
$codeExt = @('.py','.ps1','.sh','.bat','.json','.yaml','.yml','.toml','.cfg','.ini','.md','.txt','.csv','.ipynb')
$skipCodeDirs = @('__pycache__','.git','.venv','venv','node_modules','.ipynb_checkpoints','tmpdir','pretrained_models','.cache','huggingface','wandb','lightning_logs')

# ---------- plan ----------
$plan = New-Object System.Collections.Generic.List[object]
function Add-Step($action, $from, $to, $kind, $note) {
    $plan.Add([pscustomobject]@{ Action = $action; From = $from; To = $to; Kind = $kind; Note = $note }) | Out-Null
}

$items = Get-ChildItem -LiteralPath $Source -Force | Where-Object { $_.Name -notlike 'reva-voice-merge-plan*.csv' }
foreach ($it in $items) {
    $rule = $null
    if ($it.PSIsContainer) {
        foreach ($r in $dirRules) { if ($it.Name -ieq $r.Name) { $rule = $r; break } }
        if (-not $rule) { $rule = @{ Dest = ('_unsorted\' + $it.Name); Kind = 'other' } }
        $dest = Join-Path $AssetRoot (P $rule.Dest)
    } else {
        foreach ($r in $fileRules) { if ($it.Name -like $r.Pattern) { $rule = $r; break } }
        if (-not $rule) { $rule = @{ Dest = '_unsorted'; Kind = 'other' } }
        $dest = Join-Path (Join-Path $AssetRoot (P $rule.Dest)) $it.Name
    }

    if ($rule.Kind -eq 'env') {
        $req = Join-Path $RepoRoot (P ("tools\voice-lab\envs\{0}.requirements.txt" -f $it.Name))
        Add-Step 'FREEZE' $it.FullName $req 'env' 'pip freeze before moving'
    }
    if ($rule.ContainsKey('CodeTo')) {
        $codeRoot = Join-Path $RepoRoot (P $rule.CodeTo)
        if ($it.PSIsContainer) {
            $codeFiles = @(Get-ChildItem -LiteralPath $it.FullName -Recurse -File -Force | Where-Object {
                ($codeExt -contains $_.Extension.ToLowerInvariant()) -and ($_.Length -le ($MaxRepoFileKB * 1KB)) -and
                -not (Test-SkippedPath $_.FullName) -and
                -not ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
            })
            foreach ($cf in $codeFiles) {
                $rel = $cf.FullName.Substring($it.FullName.Length).TrimStart('\','/')
                Add-Step 'COPY_TO_REPO' $cf.FullName (Join-Path $codeRoot $rel) 'code' ''
            }
        } else {
            Add-Step 'COPY_TO_REPO' $it.FullName (Join-Path $codeRoot $it.Name) 'code' ''
        }
    }
    Add-Step 'MOVE_ASSET' $it.FullName $dest $rule.Kind ''
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $Apply) {
    $planFile = Join-Path (Get-Location) ("reva-voice-merge-plan-{0}.csv" -f $stamp)
    $plan | Export-Csv -LiteralPath $planFile -NoTypeInformation -Encoding UTF8
    $plan | Group-Object Action | ForEach-Object { '{0,-14} {1,6}' -f $_.Name, $_.Count } | Write-Host
    $plan | Where-Object { $_.Action -ne 'COPY_TO_REPO' } | Format-Table Action, Kind, @{n='From';e={Split-Path $_.From -Leaf}}, To -AutoSize | Out-String -Width 220 | Write-Host
    Write-Host "DRY RUN. Plan saved to $planFile. Re-run with -Apply to execute." -ForegroundColor Yellow
    return
}

# ---------- apply ----------
$logDir = Join-Path $AssetRoot '_logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$results = New-Object System.Collections.Generic.List[object]
function Log($step, $status, $detail) {
    $results.Add([pscustomobject]@{ Action = $step.Action; Status = $status; From = $step.From; To = $step.To; Kind = $step.Kind; Detail = $detail }) | Out-Null
}

foreach ($step in $plan | Where-Object { $_.Action -eq 'FREEZE' }) {
    $py = Join-Path $step.From (P 'Scripts\python.exe')
    if (-not (Test-Path -LiteralPath $py)) { $py = Join-Path $step.From 'bin/python' }
    if (-not $repoAvailable) { Log $step 'SKIPPED' 'repo not found'; continue }
    if (-not (Test-Path -LiteralPath $py)) { Log $step 'SKIPPED' 'no python in env'; continue }
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $step.To) | Out-Null
        & $py -m pip freeze --all 2>$null | Set-Content -LiteralPath $step.To -Encoding UTF8
        Log $step 'OK' ''
    } catch { Log $step 'FAILED' $_.Exception.Message }
}

foreach ($step in $plan | Where-Object { $_.Action -eq 'COPY_TO_REPO' }) {
    if (-not $repoAvailable) { Log $step 'SKIPPED' 'repo not found'; continue }
    try {
        if (Test-Path -LiteralPath $step.To) {
            $a = (Get-FileHash -LiteralPath $step.From -Algorithm SHA256).Hash
            $b = (Get-FileHash -LiteralPath $step.To -Algorithm SHA256).Hash
            if ($a -eq $b) { Log $step 'ALREADY_DONE' 'identical file already in repo' }
            else { Log $step 'CONFLICT' 'different file exists in repo; not overwritten' }
            continue
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $step.To) | Out-Null
        Copy-Item -LiteralPath $step.From -Destination $step.To -Force
        Log $step 'OK' ''
    } catch { Log $step 'FAILED' $_.Exception.Message }
}

foreach ($step in $plan | Where-Object { $_.Action -eq 'MOVE_ASSET' }) {
    if (Test-Path -LiteralPath $step.To) { Log $step 'CONFLICT' 'destination exists; left in source'; continue }
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $step.To) | Out-Null
        Move-Item -LiteralPath $step.From -Destination $step.To -Force
        Log $step 'OK' ''
    } catch { Log $step 'FAILED' ($_.Exception.Message + ' (close any program using this folder, then re-run; the script resumes)') }
}

$readme = @"
Everything in this folder is safe to delete once REVA runs from the new layout.
- envs\        Python environments. Rebuild from tools\voice-lab\envs\*.requirements.txt in the repo.
- vendor-src\  Third-party engine sources. Install pinned packages instead; record licenses in assets.manifest.json.
- tmpdir\, duplicates\  Temporary files and duplicate downloads.
"@
$tdRoot = Join-Path $AssetRoot '_to-delete'
if (Test-Path -LiteralPath $tdRoot) { Set-Content -LiteralPath (Join-Path $tdRoot 'README.txt') -Value $readme -Encoding UTF8 }

# ---------- manifest (merged with any existing manifest; user-filled fields kept) ----------
$manifestPath = Join-Path $AssetRoot 'assets.manifest.json'
$existing = @{}
if (Test-Path -LiteralPath $manifestPath) {
    $old = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($a in @($old.assets)) { $existing[$a.id] = $a }
}
$assetSteps = $plan | Where-Object { $_.Action -eq 'MOVE_ASSET' -and @('tts_checkpoint','dataset','reference_audio','run_output','eval_audio','excluded') -contains $_.Kind }
$hashDir = Join-Path $AssetRoot '_manifest'
New-Item -ItemType Directory -Force -Path $hashDir | Out-Null
$rootFull = [System.IO.Path]::GetFullPath($AssetRoot).TrimEnd('\','/')
foreach ($s in $assetSteps) {
    if (-not (Test-Path -LiteralPath $s.To)) { continue }
    if (Test-Path -LiteralPath $s.From) { continue }   # still in source = not moved yet
    $item = Get-Item -LiteralPath $s.To -Force
    $rel = $item.FullName.Substring($rootFull.Length).TrimStart('\','/')
    $id = ($rel -replace '[\\/ ]','.').ToLowerInvariant()
    if ($item.PSIsContainer) {
        $all = @(Get-ChildItem -LiteralPath $item.FullName -Recurse -File -Force)
        $files = @($all | Where-Object { -not ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) })
        $links = $all.Count - $files.Count
        $bytes = [int64]0; foreach ($f in $files) { $bytes += $f.Length }
        if (-not $SkipHash) {
            $lines = foreach ($f in $files) {
                try { $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant() } catch { $h = 'UNREADABLE' }
                '{0}  {1}' -f $h, $f.FullName.Substring($item.FullName.Length).TrimStart('\','/')
            }
            Set-Content -LiteralPath (Join-Path $hashDir ($id + '.sha256')) -Value $lines -Encoding UTF8
        }
        $sha = 'DIRECTORY'
    } else {
        $bytes = [int64]$item.Length
        if ($SkipHash) { $sha = 'TODO' } else { $sha = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    $kind = $s.Kind; if ($kind -eq 'excluded') { $kind = 'reference_audio' }
    $entry = [ordered]@{ id = $id; kind = $kind; path = $rel; sha256 = $sha; bytes = $bytes; source = 'TODO'; license = 'TODO'; provenance_status = 'TODO'; notes = '' }
    if ($s.Kind -eq 'excluded') { $entry.provenance_status = 'excluded'; $entry.notes = 'named after a real person; never used in repo or datasets' }
    elseif ($item.PSIsContainer -and $links -gt 0) { $entry.notes = ('{0} symlink(s) not hashed (likely model cache links)' -f $links) }
    if ($existing.ContainsKey($id)) {
        foreach ($k in @('source','license','provenance_status','notes','engine','version','language')) {
            $prop = $existing[$id].PSObject.Properties[$k]
            if ($prop -and $prop.Value -and $prop.Value -ne 'TODO') { $entry[$k] = $prop.Value }
        }
    }
    $existing[$id] = [pscustomobject]$entry
}
$ordered = @($existing.Values | Sort-Object id)
$manifest = [ordered]@{ manifest_version = '1.0'; asset_root = $AssetRoot; assets = $ordered }
($manifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $manifestPath -Encoding UTF8
if ($repoAvailable) { Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $RepoRoot 'assets.manifest.json') -Force }

$logFile = Join-Path $logDir ("merge-{0}.csv" -f $stamp)
$results | Export-Csv -LiteralPath $logFile -NoTypeInformation -Encoding UTF8
$results | Group-Object Status | ForEach-Object { '{0,-10} {1,6}' -f $_.Name, $_.Count } | Write-Host
Write-Host "Log: $logFile"
Write-Host "Manifest: $manifestPath  (fill in source, license, provenance_status for every entry)"
$left = @(Get-ChildItem -LiteralPath $Source -Force)
$failed = @($results | Where-Object { $_.Status -eq 'FAILED' })
foreach ($f in $failed) { Write-Warning ("FAILED {0}: {1} -> {2}" -f $f.Action, $f.From, $f.Detail) }
if ($left.Count -eq 0) { Write-Host "Source folder is empty; you can remove it." -ForegroundColor Green }
else { Write-Warning ("{0} item(s) left in source. Fix the FAILED/CONFLICT lines above and run again with -Apply; finished steps are skipped." -f $left.Count) }
