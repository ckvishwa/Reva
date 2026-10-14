# S06 security review

Scope: `reva_core/language/{normalizer,numbers,dialogue}.py`, `reva_core/voice/endpointing.py`,
`reva_core/session/ack.py`, the per-session TTS scope, the voice warm-up in `api/app.py`, and the
`data/dialogue/` store. No new route, no new network surface, no new secret.

Method: read every new module against the invariants in CLAUDE.md; hostile-input probes on the
normalizer; path and parse probes on the file store; `ruff`, `mypy`, the security suite.

## Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| S06-1 | Medium | `normalize()` raised `decimal.InvalidOperation` on a transcript such as `$1,1,1,…` or a 60-digit amount, which would have ended a turn with an internal error. A 200 000-character transcript also cost seconds of CPU. | Fixed: scan capped at 2000 characters, amounts of 10^12 and up rejected, arithmetic errors treated as "not a value". Tests in `test_normalizer.py` ("hostile input"). |
| S06-2 | Low | Dialogue state kept entity labels (for example a transaction description) on disk after they were stale in memory. | Fixed: resume rewrites the file after dropping what expired. Test: `test_what_expired_is_removed_from_disk…`. |
| S06-3 | Low | A dialogue file that was valid JSON but the wrong shape raised `KeyError` out of the store. | Fixed: any of `OSError, ValueError, KeyError, TypeError` starts the conversation fresh. |

## Checked, no finding

* Device id never names a path: the file is `sha256(device_id)[:32].json` under one directory. Tested
  with a traversal-style id.
* Writes are atomic (temp file then `os.replace`); no temp file is left behind; files over 64 KiB are
  ignored; an unwritable directory degrades to memory.
* The ack text comes from two fixed templates and is checked against a forbidden-words list; it never
  claims an outcome. "Done" still comes only from executor evidence.
* The tracker, normalizer and endpointing do no network I/O and no model calls. Nothing here calls
  `authorize()` or changes a tier; mood and persona do not reach any of it.
* The voice warm-up is a local worker start behind the same asset-hash check as speaking. It is
  cancelled on shutdown and never blocks startup.
* Per-session TTS scope: one session's `stop` cannot cancel another session's speech, and a new
  session's speech waits for the current speaker.

## Residual risks

* **R-1.** `data/dialogue/*.json` is plain JSON and holds up to ten short entity labels and the ids of
  the last five committed actions. Labels can be finance descriptions. It lives in the same data
  directory as other Core state and expires after 30 minutes (labels) or 24 hours (undo ids), but it is
  not encrypted at rest. If labels need protecting, store ids only and look labels up from the Kernel
  (S04).
* **R-2.** The shared HTTP bearer check (`auth.py`) still compares non-ASCII headers loosely; carried
  over from VOICE-1 R-1.
* **R-3.** Silero is loaded from the optional `vad` extra. Its model weights come with the pip package;
  they are not covered by the asset manifest.
