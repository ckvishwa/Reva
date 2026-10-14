# VOICE-1 code and security review

Scope: the voice pipeline merged onto `main` after alpha-2: `reva_core/{api/voice_sessions.py,
session/,providers/,voice/}`, the shared edits they need, and the tests and tools around them.
Method: read the full diff against `origin/main` (50 files), run the real Kokoro package and
weights through the production provider, and write a failing test before every fix.

Result: **no blocking finding open.** Seven findings were fixed (six with tests that failed
first, one by keeping a file out of git); five items are recorded as residual risk and one as a latent gap for S06.

## Scope check (what this slice does not touch)

`git diff origin/main...HEAD --name-only` lists no file under `reva_core/domains`,
`reva_core/gateway`, `reva_core/planner`, `reva_core/memory`, `reva_core/security`, `kernel/`,
`android/`, `desktop/`, `tests/gateway` or `tests/cross_binding`. Four shared modules change:

| File | Change | Behavior outside voice |
|---|---|---|
| `reva_core/api/app.py` | include the voice router, add a lifespan that closes voice sessions | unchanged; every other router and handler is as on `main` |
| `reva_core/api/auth.py` | adds `record_auth_failure()`, a public wrapper over the existing private function | no existing function changes |
| `reva_core/config/settings.py` | adds `asset_root`, `asset_manifest`, `tts_provider`, `kokoro_*`, `tts_stop_ack_timeout_seconds` | all new fields have defaults; no existing field changes |
| `reva_core/orchestration/lifecycle.py` | builds the TTS provider from the registry instead of directly | an earlier Chatterbox-only setup is still honored (test below) |

Settings compatibility is covered by `test_an_existing_chatterbox_only_setup_keeps_speaking_without_kokoro`:
with only the earlier Chatterbox settings, the new `tts_provider = "kokoro"` default does not strand
the setup; the registry falls back to Chatterbox.

## Findings fixed

| ID | Severity | Where | Finding | Fix and evidence |
|---|---|---|---|---|
| V-1 | High (availability) | `voice/kokoro_worker.py` | Kokoro prints `WARNING: Defaulting repo_id ...` to stdout while loading. Core reads stdout as JSON lines and refused the worker as non-JSON, so the real voice could never start. Invisible with the fake worker. | The worker keeps the real stdout for its protocol and points `sys.stdout` at stderr before importing the library. `test_kokoro_worker_protocol.py` (failed first). |
| V-2 | High (availability) | `voice/kokoro_worker.py` | On Windows a thread blocked in `ReadFile` on a pipe makes `import numpy` hang in the main thread (0.1 s vs over 150 s, reproduced without Kokoro). The worker is exactly that shape, so the first `health` command never answered under a Python-created pipe. | `stdin_lines()` peeks the pipe and sleeps 10 ms when empty, so no read is outstanding. `test_kokoro_worker_stdin.py`: the Popen test times out at 30 s without the change. |
| V-3 | Medium (confidentiality) | `voice/supervised_worker.py` | The worker inherited Core's entire environment (tokens, API keys, proxy and Python startup variables) and could reach the network. | Allow-list environment plus `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`; started from the package parent. `test_worker_environment.py`. |
| V-4 | Medium (reliability) | `voice/kokoro_worker.py`, `voice/kokoro_provider.py` | A `stop` arriving mid-sentence was not acknowledged inside Core's 0.2 s window in 2 of 5 real runs. Core then killed the worker and the next utterance waited about 9.4 s for a model reload. | Synthesis runs in a side thread; `stop` is answered at once and exactly one terminal message is ever sent. Real model: stop 0 ms, worker survived 5/5. `test_kokoro_worker_interrupt.py` (ack was 0.61 s before). |
| V-5 | Low | `api/voice_sessions.py` | The WebSocket bearer check used `hmac.compare_digest` on `str`; a non-ASCII `Authorization` value raised `TypeError` during the handshake, so the attempt was refused without an audit record. | Compare UTF-8 bytes. `test_a_non_ascii_bearer_is_a_clean_refusal_not_a_server_error` (failed first with the `TypeError`). |
| V-6 | Low | `api/voice_sessions.py` | Control messages of any size were parsed with `json.loads`. | Over 4096 characters is a typed `BAD_CONTROL_MESSAGE` before parsing, and the session stays usable. `test_an_oversized_control_message_is_refused_without_being_parsed` (it hung before the change). |
| V-7 | Medium (privacy) | repository root | The feature branch committed an `assets.manifest.json` that names private reference recordings, including recordings of named real people, with their hashes. This repository is public. | Not brought into this branch. Only the three Kokoro entries are tracked (`docs/voice/kokoro-assets.manifest.json`); the full manifest stays under the asset root. See "Action for the owner" below. |

## Checks that passed (with the test that shows it)

* **Authentication before any session activity.** The WebSocket handler checks the bearer token
  before `accept()`; refusal closes with 1008 and is audited
  (`test_websocket_without_a_token_is_refused_and_audited`, `..._wrong_token_...`).
* **No token in the URL.** `test_websocket_never_accepts_the_token_in_the_query_string`.
* **No token in logs or events.** `test_the_token_never_reaches_the_logs_or_the_event_stream`.
* **Route allow-list does not bypass authentication.** The three route tests were extended, not
  loosened: `/v1/voice/sessions`, `/v1/voice/sessions/{id}` and `/v1/voice/sessions/{id}/events`
  are listed, and the two HTTP ones are in `test_v1_auth_required.py` (401 without a token).
* **Loopback only.** Unchanged: `load_settings` still rejects a non-loopback `api_host`.
* **Audio cannot trigger tools.** The control handler maps seven message types to state
  transitions and nothing else; `test_no_tool_endpoint.py` still forbids tool, action, execute
  and command paths.
* **Session lifecycle.** `turn_epoch` only increases (`_bump_epoch`); `interrupt`, `cancel` and
  `close` are idempotent; deleting a session releases it, a second delete is a 404, and a closed
  session cannot be attached to (`test_a_closed_session_cannot_be_attached_to`); a dropped
  WebSocket returns the session to idle and invalidates its turn.
* **Bounded resources.** At most 4 sessions (429 beyond); event queues are bounded and only
  droppable events are dropped; text is limited to 800 characters; one worker at a time.
* **No shell, no path traversal.** Workers start with `create_subprocess_exec` and an argument
  list. Asset paths that leave the root, tampered hashes, missing files, unlisted ids, `TODO` or
  `excluded` provenance and a missing manifest are all refused and no process is started
  (8 real-model tests). Chunk paths returned by a worker must lie under Core's output directory.
* **Safe model loading.** Both `torch.load` calls in kokoro 0.9.4 use `weights_only=True`.
* **No orphans.** Killing the owner outright ends the worker (kill-on-close job object): fake
  worker, real worker, and a real Core process. `lifecycle.shutdown()` also ends it.
* **No microphone data is written.** This slice adds no capture; the only files are Core-owned
  TTS chunks, deleted by the consumer (and by the worker when a stop discards one).
* **Dependencies.** `pip-audit` on the Kokoro interpreter: 12 advisories, all in the venv's own
  `pip 25.0.1`; fixed by upgrading to 26.2.1, then "No known vulnerabilities found". The spaCy
  model wheel cannot be audited (not on PyPI).

## Residual risks (accepted, not fixed here)

| ID | Risk | Why it is accepted |
|---|---|---|
| R-1 | The HTTP bearer check (`api/auth.py:50`) has the V-5 weakness: a non-ASCII header raises `TypeError` and the request is refused as a 500 with no auth audit. Fails closed. | Pre-existing code outside this slice; behavior change on shared auth is the owner's call. One-line fix: compare bytes. |
| R-2 | uvicorn's default WebSocket frame limit (16 MiB) applies before the 4096-character guard, so an authenticated loopback client can make Core read one large frame. | Loopback and authenticated only. `uvicorn.run(..., ws_max_size=...)` lives in `__main__.py`, a shared file. |
| R-3 | Between the manifest hash check and the worker's load there is a short window in which a file could be replaced. | The asset root is user-owned; anyone who can write there already controls the account. |
| R-4 | GPL/LGPL packages (`phonemizer-fork`, `espeakng-loader` bundling espeak-ng, `num2words`) are in the Kokoro interpreter. | Separate process, never imported by Core. A distribution decision is needed before REVA ships with this interpreter (see `docs/voice/kokoro-production.md`). |
| R-5 | `lifecycle.shutdown()` runs the provider's async shutdown on a fresh event loop, so asyncio prints "Exception ignored ... closed pipe" noise on stderr. | Cosmetic: the test shows shutdown completes, status is `stopped` and no worker survives. |

## Latent gap for S06

The provider's `turn_epoch` is one global counter; each `VoiceSession` numbers its turns from 0.
Once any session has interrupted, another session (or the same one reopened) would be silently
ignored by `speak`. Nothing calls `speak` from a session yet, so nothing is broken today.
`tests/unit/test_tts_epoch_scope.py` states the wanted behavior as a strict xfail; S06 must make
the epoch per session (or globally monotonic) before it wires sessions to TTS.

## Action for the owner

The local branch `feat/pipe-1-voice` still contains the original commit with the sensitive
`assets.manifest.json`. It has not been pushed to any remote. **Do not push that branch.** If it
is ever published, rewrite that commit first. The integration branch replays its two commits
without the file.
