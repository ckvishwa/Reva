# Kokoro production baseline (VOICE-1)

Kokoro-82M with the `af_heart` voice is REVA's default text-to-speech. It runs in its own worker
process under its own Python interpreter; Core never imports it. Qwen3-TTS and Chatterbox
(REVI research) are not production providers and are not switched on by this slice.

## What runs

```
Core (reva_core)                              Kokoro interpreter (own venv)
  RegistryTTS -> KokoroSpeechProvider  --JSON lines on stdin/stdout-->  kokoro_worker.py
     verify_assets(manifest)                                             kokoro 0.9.4 + torch (CPU)
     SupervisedWorker + kill-on-close job
```

* **Manifest-bound load (AR-VA-020).** The worker starts only after the config, weights and voice
  files match `assets.manifest.json` (SHA-256, size, provenance, no path escape). Anything else is
  refused with a stable reason and no process is started.
* **Epoch-gated audio (AR-VA-004).** Chunks carry the `turn_epoch` they were requested under.
  After `stop(turn_epoch=n)` returns, nothing older than `n` is delivered.
* **One producer.** A second request for the same epoch waits for the first; a newer epoch
  cancels the older one.
* **Stop is acknowledged at once.** The worker answers `stop` immediately; the sentence in flight
  finishes unseen and its temp WAV is deleted. Core therefore never needs to kill the worker to
  interrupt it (a kill costs a ~9 s model reload).
* **No orphans.** On Windows the worker is assigned to a kill-on-close job object, so killing
  Core outright also ends it.
* **Offline, minimal environment.** The worker gets an allow-list of environment variables plus
  `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. Core's tokens, API keys and proxy settings are
  not passed on. Both `torch.load` calls in kokoro 0.9.4 use `weights_only=True`.
* **Protocol channel.** Kokoro prints log lines to stdout while loading; the worker moves
  `sys.stdout` to stderr before importing it and keeps the real stdout for its JSON protocol.
* **Pipe reader.** The worker polls its stdin pipe instead of blocking in `ReadFile`, because on
  Windows a blocked pipe read makes `import numpy` hang in another thread.

## Install (one time)

```powershell
# 1. Interpreter (kept off C:). Versions: tools/voice/kokoro-requirements.txt
python -m venv D:\reva-venvs\kokoro
D:\reva-venvs\kokoro\Scripts\python.exe -m pip install kokoro==0.9.4 "misaki[en]==0.9.4" soundfile
D:\reva-venvs\kokoro\Scripts\python.exe -m pip install --no-deps `
  https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# 2. Weights: hexgrad/Kokoro-82M at revision f3ff3571791e39611d31c381e3a41a3af07b4987, into
#    F:\reva-assets\models\tts\kokoro\1.0\  (config.json, kokoro-v1_0.pth, voices\af_heart.pt,
#    and the model card README.md). Verify the two LFS hashes below.

# 3. Record the three manifest entries from the real files
python tools\voice\register_kokoro_assets.py --asset-root F:\reva-assets
```

Core reads `REVA_KOKORO_PYTHON` (the interpreter) and `REVA_ASSET_ROOT` (the asset root). With
both set, Kokoro is the default provider (`tts_provider = "kokoro"`).

## Manifest entries (`assets.manifest.json`, mirrored in `docs/voice/kokoro-assets.manifest.json`)

| id | file under `models\tts\kokoro\1.0\` | bytes | SHA-256 |
|---|---|---|---|
| `models.tts.kokoro-82m.config` | `config.json` | 2351 | `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f` |
| `models.tts.kokoro-82m.model` | `kokoro-v1_0.pth` | 327212226 | `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4` |
| `models.tts.kokoro-82m.voice.af_heart` | `voices\af_heart.pt` | 523425 | `0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff` |

The weights and voice hashes equal the Hugging Face LFS hashes for that revision. All three
entries carry provenance `licensed`. The repository keeps only this Kokoro subset: the full
manifest also names private recordings and stays under the asset root, outside git.

## License check (recorded, not a legal approval)

| Component | What was checked | Result |
|---|---|---|
| Kokoro-82M weights and voices | model card metadata `license: apache-2.0`; card text "Apache-licensed weights" | Apache-2.0 declared. The card lists training audio under permissive terms including CC BY 3.0 and CC BY 4.0 sources, which ask for attribution. The card is stored beside the weights. |
| `kokoro` 0.9.4, `misaki` 0.9.4 | installed package metadata | Apache License |
| `torch` 2.14.1, `spacy` 3.8.16, `numpy` 2.5.4 | installed package metadata | permissive (BSD / MIT) |
| `phonemizer-fork` 3.3.2 | installed package metadata | **GPL**. Pulled in by `misaki[en]`. |
| `espeakng-loader` 0.2.4 | bundles the espeak-ng library | **GPL-3.0** (espeak-ng) |
| `num2words` 0.5.14 | installed package metadata | LGPL |

The GPL and LGPL packages live only in the separate Kokoro interpreter and are never imported by
Core, so they are not linked into REVA's own code. **Before REVA is distributed with this
interpreter bundled**, get a licensing decision on shipping espeak-ng and phonemizer-fork (or
move to a G2P path without them). Until then the interpreter is a per-machine install.

## Tests

| Where | Command | What it proves |
|---|---|---|
| CI and local, no model | `python -m pytest` | protocol, stop acknowledgement, pipe reader, scrubbed environment, manifest refusals, orphan kill (fake worker), session API security |
| Local, real model (opt-in) | see below | the genuine package and weights through the production provider |

```powershell
$env:REVA_RUN_KOKORO_REAL = "1"
$env:REVA_KOKORO_PYTHON   = "D:\reva-venvs\kokoro\Scripts\python.exe"
$env:REVA_ASSET_ROOT      = "F:\reva-assets"
python -m pytest tests\integration\test_kokoro_real.py -v -rs
```

Without those variables the real tests are reported as SKIPPED, never as passed.

## Hardware demonstration

Needs a speaker and `pip install sounddevice` in the interpreter that runs the script.
`REVA_KOKORO_PYTHON` and `REVA_ASSET_ROOT` as above.

**Command A, speak**
```powershell
python tools\voice\kokoro_hardware_demo.py speak --runs 10
```
Speaks "Hello! I'm Reva. My voice system is online and working." ten times (the model load is not
timed) and records text ready, request dispatched, first audio generated, first audible sample
(device DAC clock) and natural completion.

**Command B, interrupt**
```powershell
python tools\voice\kokoro_hardware_demo.py interrupt --runs 10
```
Starts a long utterance, calls the production Stop while it is audible, checks that nothing
resumes, plays a second utterance on the same worker, and counts leftover Kokoro processes.

Both print a line to open the report, for example
`Start-Process "C:\Users\<you>\AppData\Local\Temp\reva-voice-timing\<stamp>\report.html"`.
`timings.json` and `timings.csv` hold every run.

**Reading the report (AR-VA-021).** The table shows p50 and p95 per metric with a verdict.

| Check | Pass when |
|---|---|
| `first_audible_after_text_ms` | p50 <= 700 ms |
| `stop_to_silence_ms` | p95 <= 300 ms |
| orphan processes | 0 |
| `chunks_after_stop`, `resumed_frames_after_silence`, `overlap_events` | all 0 |

`NOT_MEASURED` means the run had no way to measure it (for example `--sink null` plays nothing);
it is not a pass. `--gain 0` runs the real audio device path silently, which exercises the clocks
but proves nothing about audibility. STT round-trip CER and the blind owner comparison are not
part of this run.

## Known limits

* **Speaker mute is not implemented in this tree.** The desktop app is currently
  transcription-only (no TTS playback, the stop-speaking control is hidden), and Core has no mute
  state. Nothing was invented to cover that; it belongs with the S07 playback work.
* The sentence in flight when `stop` arrives is still synthesized (silently) before the next
  utterance starts; the next first chunk is therefore up to about one sentence later.
* Between the manifest check and the worker's load there is a short window in which a file with
  write access could be swapped. The asset root is user-owned, so this adds no new attacker.
* uvicorn's default WebSocket frame limit (16 MiB) applies before the 4096-character control
  message guard.
* Pre-existing, not changed here: the HTTP bearer check in `reva_core/api/auth.py` has the same
  `hmac.compare_digest` non-ASCII weakness that was fixed for the WebSocket path.
