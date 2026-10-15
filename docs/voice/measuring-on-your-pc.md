# Measurements only you can run (B1.4 and B1.6)

## Speech-to-text benchmark (desk microphone)

1. `pip install sounddevice` (any Python), then
   `python tools/voice/stt_benchmark.py record --out D:\reva-bench\wavs`
   Read the 50 sentences in `docs/voice/stt-benchmark-script.txt` when prompted (about 10 minutes).
2. `D:\Projects\Reva\.venv\Scripts\python tools/voice/stt_benchmark.py score --wavs D:\reva-bench\wavs --models tiny base small --download`
   (`--download` lets faster-whisper fetch models that are not cached; Core itself never downloads.)
3. Send me `docs/voice/stt-benchmark.json`. I write `docs/voice/stt-benchmark.md` with WER and latency per model
   and set `stt_model`. Today's default is `Systran/faster-whisper-small` (CPU, int8).

The vocabulary prompt (app names, finance categories) is on by default in the score step, matching Core;
add `--no-vocabulary` to see what it buys.

## Wake word (default stays OFF)

You need about one hour of audio that does **not** contain "Hey Reva" (TV, talking, room noise) and 50
short clips of you saying it, as 16 kHz mono 16-bit WAV.

- Porcupine: a hash-listed `.ppn`, AccessKey in `PICOVOICE_ACCESS_KEY` for the run only.
  `python tools/voice/wake_eval.py --engine porcupine --ppn <file>.ppn --negatives <dir> --positives <dir>`
- openWakeWord: a custom "Hey Reva" model (it must be trained; this repo has none).
  `python tools/voice/wake_eval.py --engine openwakeword --model <file>.onnx --negatives <dir> --positives <dir>`

Output: false accepts per hour and miss rate for each engine. You pick; nothing is enabled by running it.
