# REVA 2.0 — Specification Pack

**Version:** 2.0.3 · **Date:** 2026-10-12 · **Status:** Proposed specification. Nothing in this pack claims a feature is built; every requirement is PLANNED until the evidence ledger (ARD-800 §5) says VERIFIED.

**What REVA 2.0 is:** one product, two full devices. A WinUI 3 Windows app and a Kotlin/Compose Android app, each with voice, an animated Blender/VRM avatar, and eight life domains (Memory, Finance, Health, Coach, Career, Learn, Cyber, Personal) that work offline on either device through one shared Rust Domain Kernel. A Python Core on the PC is the strongest brain; the phone has its own local brain. Devices sync over the LAN or an optional relay that stores only ciphertext. FRIDAY OS/AuraO is merged in by harvesting its proven designs.

## Read in this order

| # | File | What it is |
|---|---|---|
| 1 | `06_CONCEPTS/REVA_Concepts_v2.0.md` | Every concept in plain words — start here |
| 2 | `01_PRD/REVA_PRD_v2.0.md` | Product requirements: what REVA must do |
| 3 | `02_ARD/ARD-000_System_Architecture_v2.0.md` | How it all fits together |
| 4 | `02_ARD/ARD-100_Windows_App_v2.0.md` | Windows app (written first) |
| 5 | `02_ARD/ARD-200_Cross_Platform_App_v2.0.md` | Android app (written second) |
| 6 | `02_ARD/ARD-700_Life_Domains_and_Domain_Kernel_v2.0.md` | Finance, Health and all domains + the shared Kernel |
| 7 | `02_ARD/ARD-300_REVA_Core_v2.0.md` | Python Core, APIs, providers |
| 8 | `02_ARD/ARD-400_Voice_and_Avatar_v2.0.md` | Voice pipeline, Revi voice, avatar asset and runtime |
| 8b | `02_ARD/ARD-450_Language_Understanding_and_Generation_v2.0.md` | NLU / NLG: rules, resolution ladder, dialogue state, authorize(), templates, grounded answers (Lakewood patterns) |
| 9 | `02_ARD/ARD-500_Data_Sync_Security_v2.0.md` | Storage, pairing, sync, relay, threat model |
| 10 | `02_ARD/ARD-600_AI_Agent_and_Actions_v2.0.md` | Planner, policy, capability registry, executors |
| 11 | `02_ARD/ARD-800_Merge_Build_Release_v2.0.md` | Merge/cleanup, CI, tests, evidence, release |
| 12 | `03_ADR/REVA_ADR_Register_v2.0.md` | 22 v1 decisions with v2 status + 18 new ADRs (023–040) |
| 13 | `04_SLICES/REVA_Version_Slices_v2.0.md` | 28 slices in order with version tags and gates, plus avatar (A1–A4) and voice (V1–V4) tracks |
| 14 | `05_VERSIONS/REVA_Version_Pins_and_Policy_v2.0.md` | Toolchain pins and versioning rules |
| 15 | `07_TRACEABILITY/` | Every v1 and v2 requirement → owner → slice (MD + CSV) |
| 16 | `08_CONTRACTS/` | JSON Schemas, capability registry, planner schema, reference proto |
| 17 | `09_ARCHIVE_v1/` | Original v1.1 pack (schema filename fixed; duplicate removed; checksums verify) |
| 19 | `11_PROMPTS/REVA_Slice_Playbook_and_Prompts_v2.0.md` | Build order with reasons, feature v1→v2 splits, session preamble and a Claude Code prompt for every slice |
| 18 | `10_TOOLS/Merge-RevaVoiceWorkspace.ps1` | Reorganizes `F:\Voice FOR Reva` into asset root + repo; dry run by default; never deletes; writes the asset manifest |

## Release path

G0 `v2.0.0-alpha.0` clean & merge → G1 `alpha.7` Windows alpha (voice, avatar, verified action, Memory + Finance) → G2 `alpha.12` Android paired → G3 `alpha.17` all domains on both devices → G4 `beta.4` standalone Android + relay → G5 `v2.0.0` signed release.

## First actions

1. V1: run the merge script **as a file** (dry run, then `-Apply`; it resumes after the earlier pasted run); fill in provenance for every voice asset.
2. Unzip this pack to `D:\Projects\Reva\docs\spec`, then S00 → S01 → S02 → S03 using the prompts in `11_PROMPTS`.
3. S04 Kernel spike, V2 bakeoff decision, then S05.

## Contract validation

All `*.schema.json` files are JSON Schema 2020-12 and were validated with `jsonschema` when this pack was built; sample LAN and relay sync batches validate, and a relay batch with plaintext events is rejected. The capability registry contains no forbidden (money-movement, medical-dosing, shell) capability.

## Integrity

`SHA256SUMS.txt` covers every file in this pack. Verify with `sha256sum -c SHA256SUMS.txt`.
