# Bounded queues and what happens when they fill (AR-CORE-012)

Nothing in the Core grows without a limit. Each buffer below has a number, a documented behaviour when it is full, and a test (`tests/unit/test_queue_saturation.py`, plus the tests named in the last column).

| Buffer | Bound | When full | Test |
|---|---|---|---|
| Session event subscription | 256 events per subscriber | Drops the oldest *droppable* event (partial transcript, text delta) first; if only essential events remain the subscriber is closed (`overrun`) and must reconnect and replay | `test_voice_session.py`, saturation test |
| Session event history (replay) | 64 | Oldest event forgotten | saturation test |
| Voice sessions | 4 open at once | `429` `too_many_sessions` / `CORE.RATE_LIMITED` | `test_voice_sessions_api.py` |
| Audio of one utterance | 30 s | `UTTERANCE_TOO_LONG`, audio discarded, nothing transcribed | `test_turn_pipeline.py` |
| One audio message from the client | 1 s of PCM | `BAD_AUDIO` error event | `test_turn_pipeline.py` |
| Synthesised replies waiting to be fetched | 4 | Oldest audio file deleted | saturation test |
| Control message | 4096 characters | `BAD_CONTROL_MESSAGE` | `test_voice_sessions_api.py` |
| Actions waiting (approval or executor, including attempted/observed) | 64 | `429` `too_many_actions` / `CORE.RATE_LIMITED`; expired grants become `unknown` on the next broker read, proposal, approval or outcome report, releasing capacity without claiming success or executing again | saturation test |
| Finished actions kept in memory | 1000 | Oldest finished action forgotten (the ledger keeps all) | saturation test |
| Used grant keys remembered | 4096 | Oldest forgotten (grants live 60 s) | saturation test |
| Action ledger payload | 4000 characters | Largest fields replaced with `<truncated>` and `truncated: true`; if keys alone exceed the bound, retain only the truncation marker. JSON stays valid and execution arguments are unchanged | saturation test, `test_policy_broker.py` |
| Domain change long-polls | 8 | `429` `too_many_watchers` | `test_domain_changes.py` |
| Dialogue references / undo | 10 / 5 | Oldest dropped | `test_dialogue.py` |
| Gateway request body | 9 MiB (16 KiB before pairing) | Request refused | `tests/gateway/` |
| Gateway events per pull | 500 | Returns a page and a cursor | `tests/gateway/` |
| Turn log files | rotated and pruned | Oldest file deleted | `test_turn_log.py` |
| Turn tasks in flight | one per turn, only started while Listening | A new turn cannot start while one runs | `test_turn_pipeline.py` |

Rule for new code: a new queue, list, cache or buffer needs a bound, a stated behaviour at the bound, and a row here.
