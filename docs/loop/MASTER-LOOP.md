MASTER LOOP — REVA 2.0: S07 → v2.0.0. Run continuously. CLAUDE.md rules apply to everything.

FIRST ACTION
Save this entire prompt verbatim as docs/loop/MASTER-LOOP.md, commit "docs: master loop", push. All work follows this file. Progress lives in docs/loop/MASTER-LOOP-progress.md.
Resume command (for a new session): "Resume MASTER LOOP from docs/loop/MASTER-LOOP-progress.md".

LOOP RULES (every slice)
1. Branch from latest origin/main in its own worktree.
2. Build → full suites from a clean tree → code-review + security-review skills on the diff → fix findings.
3. Push, open PR, wait for CI. Failing lane → fix and re-push. Same lane failing 3 times → STOP and report.
4. CI 5/5 green → merge with a merge commit → update CLAUDE.md "Current state" + tests/evidence/ledger.csv → start the next slice immediately.
5. Hardware never blocks: write NEEDS_HARDWARE ledger rows and keep going. Never tag a slice with open NEEDS_HARDWARE rows; list it as "pending tag". When I later confirm hardware results, flip rows to PASS and push the pending tags in order.
6. STOP and ask only if: a CLAUDE.md safety invariant would be touched, a security finding can't be fixed in-slice, a merge conflict would change another slice's behaviour, a decision is missing from this file, or a slice says "ask me".
7. After every slice update docs/loop/MASTER-LOOP-progress.md: slice id, PR, merge commit, CI run id + lanes, findings fixed/left, test counts, open hardware rows, pending tag, next slice. If context runs long: finish the current slice, write progress, and tell me to start a new session with the resume command.
8. At the end of each PHASE, post a short phase report and a NEEDS_HARDWARE checklist (exact commands, run order), then continue into the next phase without waiting.

════════ PHASE A — COVERAGE AUDIT (no code) ════════
A0. Read docs/spec/REVA_v2.0: PRD v2 §7, ARD-100, ARD-200, ARD-300, ARD-400, ARD-450, ARD-500, ARD-600, ARD-700, ARD-800. For every AR-* and FR-* row mark DONE (test + commit) / PARTIAL (what's missing) / NOT STARTED / DEFERRED (with reason). Write docs/loop/COVERAGE.md. Fold every uncovered gap into the matching slice below and note it. Update COVERAGE.md at the end of every phase.

════════ PHASE B — TALK TO REVA ON WINDOWS (Gate G1) ════════

B0 Housekeeping (no tag)
- auth.py shared HTTP bearer check: non-ASCII safe, constant-time byte compare, fail closed; tests (closes VOICE-1 R-1).
- Dialogue state at rest: DPAPI-encrypted (or Kernel-owned store); migrate data/dialogue/*.json; tests.
- Ledger: VOICE-1 blind-comparison row → NOT_APPLICABLE (no second voice); STT CER row moves to B1.

B1 S07 Real voice loop → pending v2.0.0-alpha.6
1. NAudio WASAPI capture: device select, mic mute, device loss → safe idle; real mic-open state drives LISTENING.
2. capture → Corx endpointing → faster-whisper with words-only vocabulary prompt (app names, finance categories) → planner → Kokoro → playback with per-session turn_epoch flush. Push-to-talk Ctrl+Space.
3. Intent router calls reference() for "it / that one / the last one" and accept_proposal() after every accepted proposal. Test: "add twelve dollars for lunch" → "make it fifteen".
4. STT benchmark on my desk mic: tiny/base/small, 50-sentence script incl. finance phrases, WER + latency → docs/voice/stt-benchmark.md; pick model.
5. Ollama model choice: 20-prompt tool-call eval across 2–3 local models that fit this PC; pick one.
6. Wake word: Porcupine (default OFF, hash-listed .ppn, AccessKey in Credential Manager) + openWakeWord custom "Hey Reva" evaluated: false accepts/hour on 1 h non-wake audio, miss rate on 50 phrases; I pick.
7. Cloud model: Anthropic provider, opt-in, key in Credential Manager, Settings disclosure, per-domain consent filter (Finance/Health/Memory/Personal default off), timeout → Ollama fallback with notice.
8. Speaker mute + mic mute on Talk page; TurnEvent recording (local, redacted).
NEEDS_HARDWARE: 3 recorded turns (budget question, expense to confirm card, barge-in); mic unplug; wake-word runs; one cloud turn with my key.

B2 S08 Avatar + moods → pending v2.0.0-alpha.7
1. avatar/ package: three.js + @pixiv/three-vrm pinned (versions ≥ 14 days old), bundled locally, no CDN; placeholder.vrm (license-clear sample; report which + license).
2. Poses idle/listening/thinking/speaking/approval/error; RMS lip sync from played audio with turn_epoch; stale epochs dropped.
3. Mood engine as a pure function per docs/persona/REVA_Persona.md (priority, decay, overrides; flirty off by default and auto-off for finance/health/memory/errors/approvals); outputs template variant, TTS params, avatar expression. Add `mood` to avatar.expression cause enum (schema minor bump). Action-linked positive expressions still need verified_outcome.
4. WebView2 host: virtual host mapping, navigation + network blocked, FPS cap 60, pause when minimized; avatar off / reduced motion / quality settings.
5. Tests: event schema validation, offline load, listening only when mic open, mood engine incl. no-flirty + no-dependency-phrase fixtures, lip-sync offset script.
NEEDS_HARDWARE: 10-min GPU/FPS profile; lip-sync offset on speakers; screenshot of each pose.

B3 S09 Understand commands + open apps → pending v2.0.0-alpha.8
1. Rule fast path (regex + spaCy Matcher): app.open/close, finance.add_transaction, finance.summary, today.get, memory.remember/recall, assistant.stop/repeat/undo; positive + negative fixtures.
2. Resolution ladder: exact → alias → lexical → fuzzy (RapidFuzz) → vector (shadow-only, logs scores + margin) → ask.
3. Pure authorize() → AuthorizationDecision with stable reason codes, shared by rule and planner paths.
4. /v1/actions/* : change the route-allowlist test deliberately in its own commit — exactly /v1/actions/proposals, /v1/actions/{id}/approval, /v1/actions/{id}, auth on each.
5. Start Menu discovery → "waiting for you" list; I approve apps + spoken aliases (Apps & Actions page per docs/design/Apps.dc.html).
6. Windows executor: open (T1) / close (T2, click approval) allowlisted apps only; signed grants bound to action, args, target, expiry, idempotency key; evidence (process + window); Activity page.
7. Voice expense end to end: "add twelve dollars for lunch" → confirm card → Kernel commit → "Saved." → visible on phone after sync.
8. Tests: forbidden capabilities (pay/transfer/shell) → refusal template; forged/replayed/substituted grants; filler vs content words; false-success corpus 0/100; registry absence test in CI.
NEEDS_HARDWARE: "open VS Code" and "close Spotify" (approve) by voice; voice expense visible on PC and phone.

B4 CORE-2 Finish ARD-300 → pending v2.0.0-alpha.9
- /v1/today across enabled domains; /v1/settings/privacy (per-domain sync / devices / hosted-model) enforced by sync and the consent filter; /v1/domains (enabled, schema versions, switches); per-domain export/import.
- Error taxonomy incl. DOMAIN.VALIDATION, DOMAIN.LOCKED, DOMAIN.MIGRATION_FAILED, DOMAIN.CONSENT_REQUIRED, AVATAR.UNAVAILABLE — one typed error shape.
- AR-CORE-006 unknown major schema_version rejected; AR-CORE-008 config precedence (defaults < file < env < Credential Manager for secrets); AR-CORE-010 network-capture test per domain; AR-CORE-011 reversible Core SQLite migrations with snapshot upgrade/rollback; AR-CORE-012 bounded queues + saturation tests; AR-CORE-013 opt-in redacted local telemetry, off by default.
- Embeddings provider (Ollama) with lexical fallback; assert the fake provider is never the silent default.

PHASE B report + hardware checklist → continue.

════════ PHASE C — TALK TO REVA ON THE PHONE (Gate G2) ════════

C1 AND-2 Android voice + avatar → pending v2.0.0-alpha.10
- Foreground service type microphone, started only from a tap; mic permission deny / deny-forever / revoke mid-session; text fully usable without mic.
- SpeechRecognizer on-device only after availability check; disclosed fallback.
- Android TTS synth-to-file + AudioTrack with RMS envelope + turn_epoch; when paired, option to stream Kokoro audio from the PC.
- Same avatar/ package in WebView via WebViewAssetLoader, network blocked; same mood engine rules artifact.
- Recognizer, TTS, WebView released on session end (leak test); main thread never blocked (StrictMode + jank trace).
- Same language artifacts and authorize() logic as Windows; cross-platform parity suite.
NEEDS_HARDWARE: talk to REVA on my phone, interrupt, mic deny/revoke, screenshots.

C2 AND-3 Phone actions + phone→PC → pending v2.0.0-alpha.11
- Android executor via intents/public APIs only: open app (user-approved alias list), alarm, reminder, calendar insert, share; no QUERY_ALL_PACKAGES, no AccessibilityService.
- Phone asks the PC to act through the gateway; T2 PC actions need click approval on the PC; phone-only approval must fail.
- Gateway grant scope extended: finance sync + allowlisted PC actions; re-pair/upgrade path; tests.
NEEDS_HARDWARE: from phone open Calculator on PC (T1) and close Spotify on PC (T2, approved on PC); set an alarm by voice on the phone.

C3 AND-4 Phone works alone → pending v2.0.0-alpha.12
- Android local brain: session state machine, provider registry, planner client, same capability registry + policy as Core.
- Modes shown on screen: Paired / Standalone (opt-in hosted model, disclosed, per-domain consent) / Offline-lite (rules + Kernel queries only; "advanced reasoning unavailable" for open questions).
- Network capture: consent off → no Finance/Memory content outbound.
- Battery + thermal profiling script for a 30-min voice session on 2 device tiers.
- Debug APK to D:\reva-releases\v2.0.0-alpha.12\ with SHA-256.
NEEDS_HARDWARE: PC off — offline Finance question, standalone open question with my key; battery/thermal run.

PHASE C report + hardware checklist → continue.

════════ PHASE D — MEMORY + ALL LIFE DOMAINS (Gate G3) ════════

D1 Memory domain → pending v2.0.0-alpha.13
- Kernel Memory domain (fact, preference, candidate, citation, embedding); candidates wait for approval; nothing saved silently.
- Hybrid recall FTS + Ollama embeddings, lexical fallback; cited answers; "I don't have that" when missing.
- Benchmark: port old Memory Engine questions from github.com/ckvishwa/AuraO history if recoverable, else 30 questions from my real use; ≥ 9/10.
- Deleted items never retrievable (FTS, vectors, sync). Memory screens on PC + phone; voice "remember …" / "what do you know about …"; syncs.
NEEDS_HARDWARE: remember a fact by voice on PC, recall it on the phone.

D2 Finance complete + Today v2 → pending v2.0.0-alpha.14
- Bills with due-date reminders (T2), recurring transactions, net-worth snapshots, OFX + CSV per-bank mappings, duplicate detection.
- Today on both apps reads every enabled domain.
- Dry-run every file in F:\reva-data\finance-import\ against my real vault; import nothing until I approve per file (ask me).
NEEDS_HARDWARE: approve imports; bill reminder fires on the phone.

D3 Health + Health Connect → pending v2.0.0-alpha.15
- Health domain: workouts, steps, sleep, heart rate, weight, meals, medication schedule; manual entry on both apps.
- Android Health Connect read-only, per-type permission, rationale screen, revocation stops import.
- Safety: no diagnosis or dosing; urgent-symptom phrases → "contact a professional or emergency services"; health safety eval 100% on urgent set.
- Voice: "log a 40-minute run", "how did I sleep this week". Play health-apps declaration draft in docs/release/.
NEEDS_HARDWARE: grant Health Connect, import sleep + steps, revoke and confirm import stops.

D4 Coach + Personal → pending v2.0.0-alpha.16
- Coach: goals, milestones, habits + daily check-ins, weekly review.
- Personal: journal (local-only by default), people, reminders, events.
- Voice: "check in", "remind me at 7 to call mom", "journal: …".
NEEDS_HARDWARE: reminder created by voice on PC fires on the phone.

D5 Learn + Career + Cyber → pending v2.0.0-alpha.17
- Learn: courses, certification progress, flashcards, "quiz me", study log + streak.
- Career: applications pipeline, contacts, interviews, resume versions; never sends messages.
- Cyber: lab notes, CVE notes, home-lab inventory; no scanning or exploit tools.
- Screens per docs/design visual language on both apps.

D6 Privacy, export, import, delete → pending v2.0.0-alpha.18 (Gate G3)
- Per-domain switches enforced everywhere; hosted-model default off for Memory, Finance, Health, Personal.
- Per-domain + full export (CSV/JSON) round-trips into a fresh install; per-domain delete clears UI, search, embeddings, sync queue.
- File import for every domain with row reports.
- Gate G3: 8/8 domains read+write offline on both devices; network capture clean with switches off.
NEEDS_HARDWARE: airplane-mode tour of all 8 domains on phone and PC.

PHASE D report + hardware checklist → continue.

════════ PHASE E — AWAY-FROM-HOME, TELUGU, UI CONTROL, HARDENING (Gate G4) ════════

E1 Encrypted relay → pending v2.0.0-beta.1 (ask me for Supabase URL + anon key when you get here)
- Group key created on PC at pairing, delivered over the paired channel; events encrypted on device; Supabase mailbox stores ciphertext + routing metadata only.
- Opt-in, off by default; LAN stays default.
- Adversarial review: key handling, recovery, replay, metadata leakage, relay operator view. UI says "encrypted on your devices before upload"; never "end-to-end encrypted" until the review passes; record the verdict.
NEEDS_HARDWARE: phone on mobile data, PC on home Wi-Fi, expense syncs through the relay.

E2 Telugu → pending v2.0.0-beta.2
- Telugu + Telugu–English code-mixed normalization, rule aliases, templates.
- Evaluate Telugu STT + TTS options (Kokoro has none): quality, latency, license; I pick (ask me).
- Telugu fixture suite; Telugu enabled only if it passes.
NEEDS_HARDWARE: 20 Telugu and code-mixed commands on my mic.

E3 Windows UI control → pending v2.0.0-beta.3
- UI Automation: inspect window, click named control, set text; fresh snapshot ids + target window identity; password/OTP fields redacted; elevated/secure desktops fail closed. Max 2 steps per plan.
NEEDS_HARDWARE: "open Notepad and type Meeting notes", verified by evidence.

E4 Hardening + calibration → pending v2.0.0-beta.4 (Gate G4)
- Failure injection: Core kill, sync drop, permission loss, sleep/resume, stale approvals.
- Per-stage latency budgets recorded; viseme lip sync replaces RMS if offset improves.
- Vector auto-resolve per entity type only after ≥ 200 labels and ≥ 99.5% precision; otherwise stays shadow.
- Long randomized sync replay: 0 lost / 0 duplicated / 0 resurrected.
- Battery + thermal on 2 phone tiers.

PHASE E report + hardware checklist → continue.

════════ PHASE F — RELEASE v2.0.0 (Gate G5) ════════

F0 My Blender avatar (whenever I deliver it)
- When reva-1.0.vrm (+ VRMA clips) appears in assets/avatar/: validate (VRM 1.0, ≤ 50k triangles, ≤ 2048 px textures, required expressions + clips), swap out the placeholder on both apps, re-run avatar tests. If not delivered by F3, ship with the placeholder and list it as open.

F1 Windows release → pending v2.0.0-rc.1
- Installer bundles .NET runtime, Windows App SDK, Core Python runtime, Kokoro interpreter, Kernel library; no repo or venv needed.
- Kokoro GPL/LGPL bundling decision documented in docs/licenses/THIRD_PARTY.md (bundle with source offer, or download on first run) — ask me.
- Code signing, checksums, SBOM; upgrade keeps all data; uninstall keeps data unless I choose wipe.
NEEDS_HARDWARE: clean Windows VM install, upgrade, uninstall.

F2 Android release → pending v2.0.0-rc.2
- Release keystore: give me the exact keytool command; I create it; never commit it. Signed APK + AAB; upgrade keeps data.
- docs/release/: privacy policy draft, Play data-safety answers, health-apps declaration, permission justifications.

F3 Final → v2.0.0 (Gate G5)
- Security signoff checklist (MASVS, transport, policy, secrets, privacy, sync, relay).
- Accessibility smoke on both apps (keyboard, Narrator, TalkBack).
- Evidence ledger complete for every MUST; open items listed with reasons.
- Tag v2.0.0 only after I confirm every NEEDS_HARDWARE row.

════════ FINAL REPORT (once, at the very end) ════════
- COVERAGE.md final: every AR/FR row DONE / PARTIAL / DEFERRED with evidence.
- Per slice: PR, merge commit, CI run + lanes, findings fixed/left, test counts.
- Tags pushed vs pending; one combined NEEDS_HARDWARE checklist in run order.
- Future items left: VLM grounding, 3+ step workflows, email/calendar integrations, iOS.
