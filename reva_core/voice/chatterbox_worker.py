"""NDJSON worker for ChatterboxMultilingualTTS.

This module is launched by Core using a configured external Python
interpreter that owns the Chatterbox/Torch/CUDA environment. stdout is
reserved for protocol JSON only; model chatter is redirected to stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

_EXAGGERATION = 0.5
_CFG_WEIGHT = 0.5
_TEMPERATURE = 0.8
_REPETITION_PENALTY = 2.0
_MIN_P = 0.05
_TOP_P = 1.0
_SUPPORTED_LANGUAGES = frozenset({"en", "te"})


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _load_model(model_id: str, device: str) -> Any:
    with contextlib.redirect_stdout(sys.stderr):
        snapshot_download = importlib.import_module("huggingface_hub").snapshot_download

        ckpt = snapshot_download(model_id, local_files_only=True)
        chatterbox_tts = importlib.import_module("chatterbox.mtl_tts")

        return chatterbox_tts.ChatterboxMultilingualTTS.from_local(ckpt, device)


def _duration_ms(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("output is not a WAV file")

    offset = 12
    sample_rate = 0
    block_align = 0
    data_size = 0
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        if chunk_end > len(data):
            raise ValueError("WAV chunk exceeds file size")
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                raise ValueError("WAV fmt chunk is too small")
            audio_format, _, sample_rate, _, block_align, _ = struct.unpack_from(
                "<HHIIHH", data, chunk_start
            )
            if audio_format not in {1, 3, 65534}:
                raise ValueError("unsupported WAV sample format")
        elif chunk_id == b"data":
            data_size = chunk_size
        offset = chunk_end + (chunk_size % 2)

    if sample_rate <= 0 or block_align <= 0 or data_size <= 0:
        raise ValueError("WAV metadata is incomplete")
    frames = data_size / block_align
    return sample_rate, int((frames / sample_rate) * 1000)


def _handle_synthesize(model: Any, reference_wav: Path, request: dict[str, Any]) -> dict[str, Any]:
    request_id = str(request.get("id", ""))
    text = request.get("text")
    language = request.get("language")
    output_path_value = request.get("output_path")
    if not isinstance(text, str) or not text.strip():
        return {"id": request_id, "status": "error", "kind": "validation"}
    if language not in _SUPPORTED_LANGUAGES:
        return {"id": request_id, "status": "error", "kind": "validation"}
    if not isinstance(output_path_value, str) or not output_path_value:
        return {"id": request_id, "status": "error", "kind": "validation"}

    output_path = Path(output_path_value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(sys.stderr):
        torchaudio = importlib.import_module("torchaudio")

        wav = model.generate(
            text,
            language_id=language,
            audio_prompt_path=str(reference_wav),
            exaggeration=_EXAGGERATION,
            cfg_weight=_CFG_WEIGHT,
            temperature=_TEMPERATURE,
            repetition_penalty=_REPETITION_PENALTY,
            min_p=_MIN_P,
            top_p=_TOP_P,
        )
        torchaudio.save(str(output_path), wav, model.sr)
    sample_rate, duration = _duration_ms(output_path)
    return {
        "id": request_id,
        "status": "completed",
        "sample_rate": sample_rate,
        "duration_ms": duration,
        "output_path": str(output_path),
    }


def _serve(model: Any, reference_wav: Path) -> int:
    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("id", ""))
            command = request.get("command")
            if command == "health":
                _emit({"id": request_id, "status": "ready"})
            elif command == "synthesize":
                _emit(_handle_synthesize(model, reference_wav, request))
            else:
                _emit({"id": request_id, "status": "error", "kind": "unknown_command"})
        except Exception as exc:  # noqa: BLE001 - worker boundary must normalize every failure
            print(f"worker request failed: {type(exc).__name__}", file=sys.stderr)
            _emit({"id": request_id, "status": "error", "kind": "internal"})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="REVA Chatterbox TTS worker")
    parser.add_argument("--reference-wav", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--device", required=True)
    args = parser.parse_args()

    reference_wav = Path(args.reference_wav)
    if not reference_wav.is_file():
        print("reference audio unavailable", file=sys.stderr)
        return 2
    try:
        model = _load_model(args.model_id, args.device)
    except Exception as exc:  # noqa: BLE001 - startup failure becomes worker unavailable
        print(f"model load failed: {type(exc).__name__}", file=sys.stderr)
        return 3
    return _serve(model, reference_wav)


if __name__ == "__main__":
    raise SystemExit(main())
