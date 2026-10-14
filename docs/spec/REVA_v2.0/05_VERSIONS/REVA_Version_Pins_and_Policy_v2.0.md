# REVA — Version Pins and Versioning Policy v2.0

**Document ID:** REVA-VER-002 · **Version:** 2.0.2 · **Date:** 2026-10-12
Pins marked **confirm** are recommendations to lock in the first slice that uses them (record the exact value in the repo and here), then never float.

## 1. What gets a version

| Thing | Scheme | Current |
|---|---|---|
| Product (Windows app, Android app, Core, Kernel together) | SemVer + pre-release: `2.0.0-alpha.N` → `beta.N` → `rc.N` → `2.0.0` | target 2.0.0 |
| Spec pack (PRD, ARDs, ADRs, slices) | `2.0.x`; patch = wording/fixes, minor = new requirements, major = boundary change | 2.0.1 |
| Contract `schema_version` | major.minor; additive = minor; breaking = major | 2.0 |
| Kernel domain event schema | per domain, major.minor | 1.0 each |
| Capability registry | integer revision | 2 |
| Avatar asset | major.minor | 1.0 at A4 |
| Voice asset (Revi) | `revi-major.minor`; new training data or engine = major | revi-1.0 at V3 |
| Language artifacts (rules, aliases, templates) | integer revision each, recorded in every TurnEvent | 1 |
| Asset manifest | `manifest_version` 1.0 | 1.0 |
| Android `versionCode` | `major*1_000_000 + minor*10_000 + patch*100 + prerelease_index` | — |

## 2. Platform and toolchain pins

| Area | Pin | Note |
|---|---|---|
| Windows OS | Windows 11 23H2+ (Windows 10 22H2 best effort) | WebView2 runtime required |
| .NET | .NET 10 (LTS) | Audit baseline |
| Windows App SDK / WinUI 3 | 2.x stable; 2.4.0 was latest stable as of 2026-07-30 — **confirm** current patch | Upgrade in its own commit |
| WebView2 | Evergreen runtime | Bundled bootstrapper in installer |
| Python (Core) | 3.12 — **confirm** | ML wheels (faster-whisper, Kokoro, torch) |
| Rust | stable, pinned in `rust-toolchain.toml` — **confirm** | targets x86_64-pc-windows-msvc, aarch64-linux-android, x86_64-linux-android |
| UniFFI | one pinned version for Python + Kotlin — **confirm** | bindings generated in CI |
| SQLCipher | `rusqlite` with bundled SQLCipher + vendored OpenSSL | proven on Windows (PR #8); Android NDK = S04 spike |
| Android NDK | current LTS — **confirm** | for Kernel cross-build |
| Android minSdk | 31 (Android 12) | on-device recognizer, FGS rules |
| Android target/compileSdk | 36 (Android 16) | Play requires it for new apps and updates from 2026-08-31 |
| Kotlin, AGP, Compose BOM | latest stable at S11 — **confirm** | Gradle version catalog |
| Health Connect client | latest stable — **confirm** | read-only permissions |
| Blender | current LTS — **confirm** | VRM Add-on for Blender |
| Avatar format | VRM 1.0 (+ VRMA clips) | |
| three.js, @pixiv/three-vrm | exact versions in `avatar/package.json` — **confirm** | bundled locally; versions at least 14 days old |
| TTS | Revi on the bakeoff-chosen engine (pin engine package version in V2); Kokoro-82M `af_heart` fallback | engine license recorded in manifest |
| NLU libraries | spaCy (English model pinned), RapidFuzz — **confirm** | same versions on Android equivalents where used |
| STT | faster-whisper; model size by WER/latency eval | Android platform recognizer |
| LLM | Ollama; model by FR-AI-002 tool-call eval | Anthropic opt-in |
| Wake word | Porcupine, default off, SHA-256 manifest | |
| E2E Windows | FlaUI — **confirm** | self-hosted Windows runner |

## 3. Version ↔ gate map

| Tag | Gate | Slice |
|---|---|---|
| v2.0.0-alpha.0 | G0 / P0 | S03 |
| v2.0.0-alpha.7 | G1 / R1 | S10 |
| v2.0.0-alpha.12 | G2 / R2 | S15 |
| v2.0.0-alpha.17 | G3 | S20 |
| v2.0.0-beta.4 | G4 / R3 | S24 |
| v2.0.0 | G5 / R4 | S27 |

## 4. Sources

- Android target API requirements: https://developer.android.com/google/play/requirements/target-sdk
- Play target API policy: https://support.google.com/googleplay/android-developer/answer/11926878
- Windows App SDK 2.4.0 release mirror: https://sourceforge.net/projects/windows-app-sdk.mirror/files/v2.4.0/
