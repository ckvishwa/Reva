# Phase B reconciliation (2026-10-15)

Compared: `docs/loop/MASTER-LOOP.md` B0 to B4, the ledger (`tests/evidence/ledger.csv`), `docs/loop/COVERAGE.md` and the code on `main` at `d384df2`. Status comes from code and tests read in this pass, not from PR titles.

Not available to this pass: the "MASTER LOOP v2" additions were not in the session, so only the original B text was compared. Any v2-only B requirement is unchecked until that text is supplied.

Legend: **V** implemented and verified by automated tests. **H** implemented, awaiting hardware. **M** missing. **P** deliberately PARTIAL.

## Checklist

| Area | Requirement | Status | Evidence / note |
|---|---|---|---|
| B0 | Shared bearer check, constant time, fail closed | V | `B0-bearer-check` |
| B0 | Dialogue state encrypted at rest | V | `B0-dialogue-dpapi` |
| B1 | Voice loop code (capture, STT with vocabulary prompt, router, Kokoro, flush by `turn_epoch`) | V | `B1-stt-vocabulary`, `AR-WIN-004/005/010/015`, `B1b-*` |
| B1 | Real mic, Ctrl+Space, barge-in, device loss, STT benchmark, wake word, real cloud turn | H | `AR-WIN-*-hardware`, `B1-stt-benchmark`, `B1-wake-word-eval`, `B1-cloud-real-turn` |
| B1 | Cloud model opt-in, key in Credential Manager, consent filter, Ollama fallback with notice | V | `B1-cloud-key-handling`, `B1-cloud-fallback-event`, `B1d-*` |
| B2 | Avatar package, poses, mood engine, host, listening only when mic open | V | `B2-*`, `AR-WIN-004-avatar`, `B2c-webview-real-app` |
| B2 | GPU/FPS profile, lip-sync offset, pose screenshots on the real GPU | H | `B2-gpu-profile`, `B2-lipsync-offset`, `B2-pose-screenshots` |
| B3 | Rule fast path, entity ladder, pure `authorize()`, `/v1/actions/*` allowlist, forbidden refusals | V | `B3a-*`, `B3b-*` |
| B3 | Signed-grant checks (forged, replayed, expired, not-yet-valid, substituted, wrong device/actor) in Python and C# | V | `B3a-signed-grants`, `B3c-grant-verify-cross-language`, `B3c-executor-refuses-bad-grants` |
| B3 | Action-result templates; "done" only from executor evidence; 0 of 100 false successes | V | `B3a-false-success` (500 runs), `B3c-false-success-0-of-100`, `B3c-reply-from-executor`; `outcomes.py` |
| B3 | Voice expense: spoken yes drafts only, click commits, "Saved." from the Kernel event | V | `B3b-voice-expense-waits-for-tap`, `B3c-expense-confirm-card` |
| B3 | Open VS Code / close Spotify by voice; expense visible on PC and phone | H | `B3c-hw-*` |
| B3 | `assistant.stop`, `assistant.repeat` as T0 capabilities | **M, fixed in B3d** | not in the registry or rules on `main`; B3d adds them |
| B3 | `assistant.undo` as confirmed T2 reversal via Kernel event/tombstone | **M, fixed in B3d** | `main` kept only an undo pointer in the dialogue state and no capability or executor; B3d adds both |
| B4 | Grant expiry (stuck grants become `unknown`) and Activity | V | `B4-bounded-queues`, `B4-FIX-review-regressions` |
| B4 | API validation: typed errors, free-text limits, 1 MiB JSON cap | V | `B4-error-taxonomy`, `B4-free-text-limits` |
| B4 | Streamed request limits (chunked bodies stopped at the cap) | V | `B4-FIX-review-regressions` |
| B4 | Protocol versions (unknown major refused, newer minor accepted) | V | `B4-schema-major` |
| B4 | Reversible migrations, snapshot before upgrade, atomic script+version row, safe rollback/restore | V | `B4-migrations-reversible` |
| B4 | Telemetry off by default, redacted, local, removable | V | `B4-telemetry` |
| B4 | Privacy settings per domain enforced by sync and the consent filter | V | `B4-privacy-settings` |
| B4 | Config precedence defaults < file < env < vault | P | works with injected stores; production startup does not inject them (AR-CORE-008) |
| B4 | AR-CORE-010 network capture per domain | P | filter tested at the SDK boundary; no domain context reaches the cloud path until the G4 context builder lands. Spoken transcripts are sent when hosted voice is on (disclosed) |
| B4 | Embeddings via Ollama with lexical fallback; fake never the silent default | V | `tests/unit/test_embedding_defaults.py` |

Found stale and corrected in this pass: about 26 `COVERAGE.md` rows for B3 (AR-AGT, AR-LANG, AR-WIN-008/009, FR-LNG, FR-DOM-004) still said NOT STARTED. They now carry their real status. Planner-dependent rows (AR-AGT-009/011/015, AR-LANG-006) stay NOT STARTED because the planner exists only on the `wip/planner-reasoning` branch.

## Gaps and where they were fixed

1. `assistant.stop` / `assistant.repeat` / `assistant.undo` missing: slice B3d (`feat/b3d-assistant-controls`).
2. Latent flaw found while doing it: the dialogue undo pointer was set when the owner said "yes" to a draft, before any executor saved anything. B3d sets it only when the Kernel confirms the expense.

## Known limits of B3d (recorded, not hidden)

- Undo covers voice expenses the running Core saved. The map from an action to its transaction is held in memory (bounded to 32), so after a Core restart REVA says "There's nothing I can undo."
- Undo reverses with the Kernel `transaction.delete` tombstone; the event stays in the history and syncs to the phone like any delete.
- "Repeat" replays the text of the last thing said in the session, including a model answer. It makes no new claim.
- "Stop" drops REVA's own draft, question or guessed app. It does not cancel a confirm card already on screen (those expire in two minutes) and never commits anything.

## Remaining B hardware checklist (blocks tags `alpha.6` to `alpha.9`)

Run in order. Each row flips to PASS only with your result or recording.

**Prerequisites:** Core running with the faster-whisper model cached; Kokoro installed (`REVA_KOKORO_PYTHON`, `REVA_ASSET_ROOT`); app built with the avatar (`cd avatar; npm ci; npm run build`, Git LFS pulled); Ollama running with `OLLAMA_MODELS=F:\AI\Ollama\models`; Domain Kernel binding built; a finance account exists; microphone, speakers and (for step 9) the paired phone.

| # | Steps | Expected | Rows |
|---|---|---|---|
| 1 | Voice on. Hold the button, say "add twelve dollars for lunch". Hold Ctrl+Space in Notepad, say "make it fifteen". Interrupt a long answer. Unplug the mic while talking. Mute mic, then speaker (`docs/voice/live-voice-windows.md`). | Green mic dot only while open; draft reads "$12.00" then "Changed to $15.00"; speech stops within 300 ms of interrupting; unplug returns to Ready with "The microphone was disconnected"; muted mic never opens | `AR-WIN-004/005/010/015-*` |
| 2 | Screen-record a budget question, an expense that shows the confirm line, and a barge-in. | Recordings show the three turns | B1 recorded turns |
| 3 | `python tools\voice\kokoro_hardware_demo.py speak --runs 10 --device 20` | First audible p50 under 700 ms | `S06-first-audio-speaker` |
| 4 | Record the 50-sentence script, run `docs/voice/measuring-on-your-pc.md` | WER and latency table for tiny/base/small; you pick the model | `B1-stt-benchmark`, `AR-VA-021-stt-cer-benchmark` |
| 5 | One hour of non-wake audio, then 50 wake phrases, Porcupine and (once trained) openWakeWord | False accepts per hour and miss rate recorded; you pick | `B1-wake-word-eval` |
| 6 | `docs/voice/cloud-reasoning.md` steps 1 to 4: store key, ask a question, repeat offline, remove key | Reply shows the cloud provider; offline falls back to the local model with the notice; key gone afterwards | `B1-cloud-real-turn` |
| 7 | `docs/avatar/hardware-checklist.md` steps 1 to 3 | Under 15% GPU for 10 minutes, 60 fps cap, paused when minimized; lip-sync offset 100 ms p95 or less; one screenshot per pose | `B2-gpu-profile`, `B2-lipsync-offset`, `B2-pose-screenshots` |
| 8 | Older rows: SYNC-1e on the phone, Narrator pass of Finance, Home/Finance screenshots, AND-1 phone install | Per the row text | older rows |
| 9 | Say "open VS Code" (opens, REVA says "Opened Visual Studio Code."). Open Spotify, say "close Spotify", click Confirm ("Closed Spotify."). Say "add twelve dollars for lunch", "yes" (nothing saved), click Confirm ("Saved."). Open Activity. | Each sentence only after the action; transaction shows on PC and, after sync, on the phone; Activity lists all three with evidence | `B3c-hw-open-vscode-close-spotify`, `B3c-hw-voice-expense-both-devices` |
| 10 (new, B3d) | After step 9's expense: say "stop" while REVA talks; say "repeat that"; say "undo", say "yes" (nothing changes), click Confirm on the card. | "Stop" silences with no reply; "repeat" says the last sentence again; the card reads "Undo the last expense?"; only the click removes it; REVA says "Undone."; the Finance list no longer shows it | `B3d-hw-stop-repeat-undo` |
