# Baseline snapshot 2026-10-11 (S00)

Recorded before any branch change or commit. Source of truth for what the tree looked like at S00.

## Git
```
HEAD: 6004fedc3599ec1d4e0a7dc06bc46ad52e4b4c61
Branch: fixing-things
Stash entries: 0
Staged diff: empty
  feature/windows-app-command-routing 6004fed docs(wakeword): correct provider-selection finding with startup evidence
* fixing-things                       6004fed docs(wakeword): correct provider-selection finding with startup evidence
  main                                7f68db6 [origin/main: ahead 16] docs(desktop): record Task 0 recon findings for app-command routing
  master                              4ffdaa4 chore: import REVA Phase 0 foundation and Phase 1A typed memory slice
  wip/slice-8a-draft                  fd151f5 wip: uncommitted Slice 8A draft fixes (untested, reference only, do not merge as-is)
  remotes/origin/HEAD                 -> origin/main
  remotes/origin/main                 ef7212a docs(desktop): implementation plan for transcription-only voice slice
```

## Archive tags
```
archive/pre-merge-2026-10-11/feature/windows-app-command-routing 6004fed
archive/pre-merge-2026-10-11/fixing-things 6004fed
archive/pre-merge-2026-10-11/main 7f68db6
archive/pre-merge-2026-10-11/master 4ffdaa4
archive/pre-merge-2026-10-11/origin-main ef7212a
archive/pre-merge-2026-10-11/wip/slice-8a-draft fd151f5
```

## Off-repo archives
```
D:\Projects\reva-archive-2026-10-11.bundle
  git bundle verify: okay (complete history, 6 archive tags present)
  sha256: 429BC5200AF20AC04DA421EF3998E8EAA31970C2C093FD1F9ECD43B61984C137

D:\Projects\reva-backup-2026-10-11\  (ACL: current user only; not in git)
72c5cfaf792156969aee5ffa2ec55b06522d53d55a93a3daee8b77829bbc35bb  HEAD.txt
6ec4a213605f7ba9c7881b91c72424556fafa1ea3ce0240d18cdd51c3fb9cf7c  status.txt
0ef105e8bed5318fe69fff0ba3b27fe5f416ed41aabce58023f1178c4b7f18a7  tracked-modified-worktree-copies.tar.gz
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  tracked-staged.patch
31201d1a757b0bf60d435f70862af1574b4b9b83534a45288cf035845666aa29  tracked-unstaged.patch
f91118b361b0690ae499256b6e569b8545a7943d310c519cc167521bbdda8bbb  untracked.tar.gz
```

Backup holds: unstaged tracked diff (patch + byte copies of the 25 modified files) and a tarball of all 307 untracked, non-ignored files. No audio, weights, keys or tokens among them (checked by extension and name).

## Toolchains
```
git version 2.53.0.windows.2
Python 3.12.10 (.venv)
.NET SDK 10.0.302
```

## Test results (real, dirty tree at HEAD)

- .NET: `dotnet test desktop/Reva.Desktop.sln` => Passed 338, Failed 0, Skipped 0 (baseline was 334). A first run with REVA_DATA_DIR exported failed 1 test (DesktopConfigurationTests default-dir) from my env var, not a code defect.
- Python: `pytest -q --ignore=tests/voice-evals` with REVA_DATA_DIR=temp dir => 456 passed, 1 failed, 2 skipped (baseline 326 passed / 2 skipped).
  - Failed: tests/unit/test_planner_pipeline.py::test_forged_answer_cannot_claim_action_success (untracked planner work, other session).
- Python without the ignore: 7 collection errors in untracked tests/voice-evals/tests (ModuleNotFoundError: soundfile, voice_eval). Not part of the suite.
- Both suites include untracked/modified work in the tree, so they are not a clean-HEAD number.

## Dirty inventory

### git status --short
```
 M desktop/src/Reva.Desktop/App.xaml.cs
 M desktop/src/Reva.Desktop/MainWindow.xaml
 M desktop/src/Reva.Desktop/MainWindow.xaml.cs
 M desktop/src/Reva.Desktop/Services/DesktopConfiguration.cs
 M desktop/src/Reva.Desktop/Services/RevaCoreClient.cs
 M desktop/src/Reva.Desktop/Services/WakeWordKeywordResolver.cs
 M desktop/tests/Reva.Desktop.Tests/Unit/CommandRouterTests.cs
 M desktop/tests/Reva.Desktop.Tests/Unit/MainWindowShutdownOrderTests.cs
 M desktop/tests/Reva.Desktop.Tests/Unit/RevaCoreClientTests.cs
 M desktop/tests/Reva.Desktop.Tests/Unit/WakeWordKeywordResolverTests.cs
 M docs/superpowers/specs/2026-08-17-windows-app-command-routing-design.md
 M pyproject.toml
 M reva_core/api/app.py
 M reva_core/api/auth.py
 M reva_core/api/routes.py
 M reva_core/api/schemas.py
 M reva_core/config/settings.py
 M reva_core/models/tts.py
 M reva_core/orchestration/lifecycle.py
 M tests/conftest.py
 M tests/integration/test_v1_voice_speech_api.py
 M tests/security/test_api_boundary.py
 M tests/security/test_no_tool_endpoint.py
 M tests/security/test_v1_auth_required.py
 M tests/unit/test_settings.py
?? CLAUDE.md
?? REVA_Persona.md
?? assets.manifest.json
?? desktop/src/Reva.Desktop/Contracts/ReasoningSettings.cs
?? desktop/src/Reva.Desktop/Services/IReasoningSettingsClient.cs
?? docs/01_PRD/
?? docs/02_ARD/
?? docs/03_ADR/
?? docs/04_SLICES/
?? docs/05_VERSIONS/
?? docs/06_CONCEPTS/
?? docs/07_TRACEABILITY/
?? docs/08_CONTRACTS/
?? docs/09_ARCHIVE_v1/
?? docs/10_TOOLS/
?? docs/11_PROMPTS/
?? docs/CHANGELOG.md
?? docs/README.md
?? docs/SHA256SUMS.txt
?? docs/archive/
?? docs/superpowers/plans/2026-08-10-core-lifecycle.md
?? docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md
?? docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md
?? docs/voice/
?? evals/
?? reva-voice-merge-plan-20261011-202837.csv
?? reva-voice-merge-plan-20261011-203937.csv
?? reva_core/api/voice_sessions.py
?? reva_core/planner/
?? reva_core/providers/
?? reva_core/session/
?? reva_core/voice/__init__.py
?? reva_core/voice/kokoro_provider.py
?? reva_core/voice/kokoro_worker.py
?? reva_core/voice/supervised_worker.py
?? reva_core/voice/wav.py
?? tests/contract/test_planner_packaged_contracts.py
?? tests/fixtures/fake_kokoro_worker.py
?? tests/fixtures/kokoro_assets.py
?? tests/fixtures/process_utils.py
?? tests/fixtures/tts_host.py
?? tests/integration/test_cloud_reasoning_api.py
?? tests/integration/test_planner_wiring.py
?? tests/integration/test_tts_orphan_processes.py
?? tests/integration/test_voice_sessions_api.py
?? tests/security/test_cloud_consent_boundary.py
?? tests/unit/test_asset_manifest.py
?? tests/unit/test_cloud_settings.py
?? tests/unit/test_kokoro_provider.py
?? tests/unit/test_planner_pipeline.py
?? tests/unit/test_planner_providers.py
?? tests/unit/test_provider_registry.py
?? tests/unit/test_tts_facade_stop.py
?? tests/unit/test_tts_registry_wiring.py
?? tests/unit/test_voice_session.py
?? tests/unit/test_windows_planner_executor.py
?? tests/voice-evals/
?? tools/
```

### Untracked files (expanded, 307)
```
CLAUDE.md
REVA_Persona.md
assets.manifest.json
desktop/src/Reva.Desktop/Contracts/ReasoningSettings.cs
desktop/src/Reva.Desktop/Services/IReasoningSettingsClient.cs
docs/01_PRD/REVA_PRD_v2.0.md
docs/02_ARD/ARD-000_System_Architecture_v2.0.md
docs/02_ARD/ARD-100_Windows_App_v2.0.md
docs/02_ARD/ARD-200_Cross_Platform_App_v2.0.md
docs/02_ARD/ARD-300_REVA_Core_v2.0.md
docs/02_ARD/ARD-400_Voice_and_Avatar_v2.0.md
docs/02_ARD/ARD-450_Language_Understanding_and_Generation_v2.0.md
docs/02_ARD/ARD-500_Data_Sync_Security_v2.0.md
docs/02_ARD/ARD-600_AI_Agent_and_Actions_v2.0.md
docs/02_ARD/ARD-700_Life_Domains_and_Domain_Kernel_v2.0.md
docs/02_ARD/ARD-800_Merge_Build_Release_v2.0.md
docs/03_ADR/REVA_ADR_Register_v2.0.md
docs/04_SLICES/REVA_Version_Slices_v2.0.md
docs/05_VERSIONS/PIPE-2-Ollama-eval.json
docs/05_VERSIONS/REVA_Version_Pins_and_Policy_v2.0.md
docs/06_CONCEPTS/REVA_Concepts_v2.0.md
docs/07_TRACEABILITY/REVA_Traceability_v2.0.md
docs/07_TRACEABILITY/v1_to_v2_map.csv
docs/07_TRACEABILITY/v2_requirements.csv
docs/08_CONTRACTS/authorization-decision.schema.json
docs/08_CONTRACTS/avatar-events.schema.json
docs/08_CONTRACTS/capability-registry.v2.json
docs/08_CONTRACTS/domain-event.schema.json
docs/08_CONTRACTS/native-agent-v1.REFERENCE-ONLY.proto
docs/08_CONTRACTS/nlu-frame.schema.json
docs/08_CONTRACTS/planner-decision.schema.json
docs/08_CONTRACTS/session-event.schema.json
docs/08_CONTRACTS/sync-batch.schema.json
docs/08_CONTRACTS/voice-asset-manifest.schema.json
docs/09_ARCHIVE_v1/01_REVA_MASTER_PRD.md
docs/09_ARCHIVE_v1/02_REVA_MASTER_ARD.md
docs/09_ARCHIVE_v1/03_REVA_ADR_DECISIONS.md
docs/09_ARCHIVE_v1/04_REVA_REQUIREMENTS_TRACEABILITY.md
docs/09_ARCHIVE_v1/05_REVA_EXECUTION_AND_QA.md
docs/09_ARCHIVE_v1/06_REVA_AI_ML_ACTION_AGENT_PRD_ARD.md
docs/09_ARCHIVE_v1/07_REVA_NATIVE_AGENT_V1.proto
docs/09_ARCHIVE_v1/08_REVA_PLANNER_DECISION.schema.json
docs/09_ARCHIVE_v1/README.md
docs/09_ARCHIVE_v1/REVA_Full_PRD_ARD_AI_ML_Agent_2026-10-11.md
docs/09_ARCHIVE_v1/SHA256SUMS.txt
docs/10_TOOLS/Merge-RevaVoiceWorkspace.ps1
docs/11_PROMPTS/REVA_Slice_Playbook_and_Prompts_v2.0.md
docs/CHANGELOG.md
docs/README.md
docs/SHA256SUMS.txt
docs/archive/baseline-2026-10.md
docs/superpowers/plans/2026-08-10-core-lifecycle.md
docs/superpowers/plans/2026-08-10-hybrid-semantic-memory.md
docs/superpowers/plans/2026-08-10-semantic-eval-and-e2e.md
docs/voice/v1-cleanup-report.md
docs/voice/v1-fix-report.md
evals/__init__.py
evals/planner_tool_call_eval.py
reva-voice-merge-plan-20261011-202837.csv
reva-voice-merge-plan-20261011-203937.csv
reva_core/api/voice_sessions.py
reva_core/planner/__init__.py
reva_core/planner/cloud_settings.py
reva_core/planner/contracts/capability-registry.v2.json
reva_core/planner/contracts/planner-decision.schema.json
reva_core/planner/credentials.py
reva_core/planner/orchestrator.py
reva_core/planner/pipeline.py
reva_core/planner/providers.py
reva_core/planner/windows_executor.py
reva_core/providers/__init__.py
reva_core/providers/asset_manifest.py
reva_core/providers/registry.py
reva_core/providers/tts.py
reva_core/session/__init__.py
reva_core/session/coordinator.py
reva_core/session/events.py
reva_core/session/state.py
reva_core/voice/__init__.py
reva_core/voice/kokoro_provider.py
reva_core/voice/kokoro_worker.py
reva_core/voice/supervised_worker.py
reva_core/voice/wav.py
tests/contract/test_planner_packaged_contracts.py
tests/fixtures/fake_kokoro_worker.py
tests/fixtures/kokoro_assets.py
tests/fixtures/process_utils.py
tests/fixtures/tts_host.py
tests/integration/test_cloud_reasoning_api.py
tests/integration/test_planner_wiring.py
tests/integration/test_tts_orphan_processes.py
tests/integration/test_voice_sessions_api.py
tests/security/test_cloud_consent_boundary.py
tests/unit/test_asset_manifest.py
tests/unit/test_cloud_settings.py
tests/unit/test_kokoro_provider.py
tests/unit/test_planner_pipeline.py
tests/unit/test_planner_providers.py
tests/unit/test_provider_registry.py
tests/unit/test_tts_facade_stop.py
tests/unit/test_tts_registry_wiring.py
tests/unit/test_voice_session.py
tests/unit/test_windows_planner_executor.py
tests/voice-evals/README.md
tests/voice-evals/outputs/chatterbox_en_exag_025/report.json
tests/voice-evals/outputs/chatterbox_en_exag_025/report.txt
tests/voice-evals/outputs/chatterbox_en_exag_050/report.json
tests/voice-evals/outputs/chatterbox_en_exag_050/report.txt
tests/voice-evals/outputs/chatterbox_telugu/report.json
tests/voice-evals/outputs/chatterbox_telugu/report.txt
tests/voice-evals/outputs/controlled_check/report.json
tests/voice-evals/outputs/controlled_check/report.txt
tests/voice-evals/outputs/first_experiment/report.json
tests/voice-evals/outputs/first_experiment/report.txt
tests/voice-evals/outputs/second_experiment/report.json
tests/voice-evals/outputs/second_experiment/report.txt
tests/voice-evals/outputs/testfortest_experiment/report.json
tests/voice-evals/outputs/testfortest_experiment/report.txt
tests/voice-evals/requirements.txt
tests/voice-evals/revi_checkpoint_eval/compare_checkpoints.py
tests/voice-evals/revi_checkpoint_eval/comparison.baseline_zero_shot.csv
tests/voice-evals/revi_checkpoint_eval/comparison.baseline_zero_shot.json
tests/voice-evals/revi_checkpoint_eval/eval_prompts.py
tests/voice-evals/revi_checkpoint_eval/generate_baseline.py
tests/voice-evals/setup_and_test.ps1
tests/voice-evals/tests/test_audio.py
tests/voice-evals/tests/test_energy.py
tests/voice-evals/tests/test_formants.py
tests/voice-evals/tests/test_metrics.py
tests/voice-evals/tests/test_mfcc.py
tests/voice-evals/tests/test_report.py
tests/voice-evals/tests/test_self_comparison.py
tests/voice-evals/voice_eval/__init__.py
tests/voice-evals/voice_eval/audio.py
tests/voice-evals/voice_eval/cli.py
tests/voice-evals/voice_eval/energy.py
tests/voice-evals/voice_eval/formants.py
tests/voice-evals/voice_eval/mfcc.py
tests/voice-evals/voice_eval/pace.py
tests/voice-evals/voice_eval/pitch.py
tests/voice-evals/voice_eval/plotting.py
tests/voice-evals/voice_eval/report.py
tests/voice-evals/voice_eval/speaker.py
tests/voice-evals/voice_eval/spectrogram.py
tests/voice-evals/voice_eval/waveform.py
tools/revi-prototype/README.md
tools/revi-prototype/clone_revi.py
tools/revi-prototype/run-revi.ps1
tools/revi-prototype/setup-revi.ps1
tools/voice-lab/envs/chatterbox-env.requirements.txt
tools/voice-lab/envs/chatterbox-v3-env.requirements.txt
tools/voice-lab/envs/xtts-env.requirements.txt
tools/voice-lab/envs/xtts-env310.requirements.txt
tools/voice-lab/experiments/test_chatterbox_telugu.py
tools/voice-lab/revi-model-bakeoff/environment_reports/phase0_upstream_verification.md
tools/voice-lab/revi-model-bakeoff/environment_reports/phase5_indextts2_stop_report.md
tools/voice-lab/revi-model-bakeoff/prompts/prompts.py
tools/voice-lab/revi-model-bakeoff/reports/acoustic_pacing_metrics.json
tools/voice-lab/revi-model-bakeoff/reports/chatterbox_current_manifest.json
tools/voice-lab/revi-model-bakeoff/reports/chatterbox_v3_manifest.json
tools/voice-lab/revi-model-bakeoff/reports/listening_review.csv
tools/voice-lab/revi-model-bakeoff/reports/raw_model_comparison.csv
tools/voice-lab/revi-model-bakeoff/reports/raw_model_comparison.json
tools/voice-lab/revi-model-bakeoff/reports/soft2_secondary_manifest.json
tools/voice-lab/revi-model-bakeoff/reports/xtts_manifest.json
tools/voice-lab/revi-model-bakeoff/scripts/01_chatterbox_current_sweep.py
tools/voice-lab/revi-model-bakeoff/scripts/02_chatterbox_v3_sweep.py
tools/voice-lab/revi-model-bakeoff/scripts/03_pacing_and_acoustics.py
tools/voice-lab/revi-model-bakeoff/scripts/04_xtts_control.py
tools/voice-lab/revi-model-bakeoff/scripts/05_speaker_similarity.py
tools/voice-lab/revi-model-bakeoff/scripts/06_rank_models.py
tools/voice-lab/revi-model-bakeoff/scripts/07_listening_manifest.py
tools/voice-lab/revi-model-bakeoff/scripts/08_soft2_secondary_test.py
tools/voice-lab/revi-model-bakeoff/scripts/09_make_charts.py
tools/voice-lab/revi-prosody-study/analysis/lana_style_stats.json
tools/voice-lab/revi-prosody-study/analysis/native_pacing_control_check.md
tools/voice-lab/revi-prosody-study/analysis/timing_analysis.json
tools/voice-lab/revi-prosody-study/analysis/timing_analysis.txt
tools/voice-lab/revi-prosody-study/evaluations/en_L/human_0.json
tools/voice-lab/revi-prosody-study/evaluations/en_L/human_1.json
tools/voice-lab/revi-prosody-study/evaluations/en_L/human_2.json
tools/voice-lab/revi-prosody-study/evaluations/en_L/human_3.json
tools/voice-lab/revi-prosody-study/evaluations/en_mono/human_0.json
tools/voice-lab/revi-prosody-study/evaluations/en_mono/human_1.json
tools/voice-lab/revi-prosody-study/evaluations/en_mono/human_2.json
tools/voice-lab/revi-prosody-study/evaluations/en_mono/human_3.json
tools/voice-lab/revi-prosody-study/evaluations/te_R/human_0.json
tools/voice-lab/revi-prosody-study/evaluations/te_R/human_1.json
tools/voice-lab/revi-prosody-study/evaluations/te_R/human_2.json
tools/voice-lab/revi-prosody-study/evaluations/te_R/human_3.json
tools/voice-lab/revi-prosody-study/reports/REVI_SOFT_NATURAL_profile.json
tools/voice-lab/revi-prosody-study/reports/humanization_manifest.json
tools/voice-lab/revi-prosody-study/reports/humanization_metrics.json
tools/voice-lab/revi-prosody-study/reports/humanization_speaker_similarity.json
tools/voice-lab/revi-prosody-study/reports/listening_review.csv
tools/voice-lab/revi-prosody-study/reports/rate_experiment_manifest.json
tools/voice-lab/revi-prosody-study/reports/rate_experiment_metrics.json
tools/voice-lab/revi-prosody-study/reports/rate_experiment_speaker_similarity.json
tools/voice-lab/revi-prosody-study/reports/sibilance_experiment.json
tools/voice-lab/revi-prosody-study/reports/sibilance_speaker_similarity.json
tools/voice-lab/revi-prosody-study/reports/text_prosody_manifest.json
tools/voice-lab/revi-prosody-study/scripts/00_timing_analysis.py
tools/voice-lab/revi-prosody-study/scripts/01_rate_experiment.py
tools/voice-lab/revi-prosody-study/scripts/02_build_humanization_profiles.py
tools/voice-lab/revi-prosody-study/scripts/03_sibilance_experiment.py
tools/voice-lab/revi-prosody-study/scripts/04_text_prosody_experiment.py
tools/voice-lab/revi-prosody-study/scripts/05_lana_style_analysis.py
tools/voice-lab/revi-prosody-study/scripts/06_evaluate_all.py
tools/voice-lab/revi-prosody-study/scripts/07_speaker_similarity.py
tools/voice-lab/revi-prosody-study/scripts/08_make_charts.py
tools/voice-lab/revi-prosody-study/scripts/09_listening_manifest.py
tools/voice-lab/revi-prosody-study/scripts/common.py
tools/voice-lab/revi-prosody-study/scripts/dsp_humanize.py
tools/voice-lab/revi-reference-study/analysis/source_analysis.json
tools/voice-lab/revi-reference-study/analysis/source_analysis.txt
tools/voice-lab/revi-reference-study/candidates/candidates_manifest.json
tools/voice-lab/revi-reference-study/evaluations/ref_04s_A_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_04s_A_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_04s_B_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_04s_B_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_A_L/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_A_L/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_A_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_A_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_A_mono/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_A_mono/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_B_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_06s_B_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_08s_A_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_08s_A_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_08s_B_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_08s_B_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_10s_avoid_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_10s_avoid_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_10s_include_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_10s_include_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_12s_A_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_12s_A_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_15s_A_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_15s_A_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_full_R/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_full_R/te_T1.json
tools/voice-lab/revi-reference-study/evaluations/ref_full_mono/en_E1.json
tools/voice-lab/revi-reference-study/evaluations/ref_full_mono/te_T1.json
tools/voice-lab/revi-reference-study/generations/generation_log.json
tools/voice-lab/revi-reference-study/generations/sweep_cfg_weight/sweep_log.json
tools/voice-lab/revi-reference-study/generations/sweep_exaggeration/ref_08s_A_R/loudness_variants/exaggeration_0.35_en_E1_loudness_report.json
tools/voice-lab/revi-reference-study/generations/sweep_exaggeration/ref_08s_A_R/pitch_variants/exaggeration_0.35_en_E1_pitch_manifest.json
tools/voice-lab/revi-reference-study/generations/sweep_exaggeration/sweep_log.json
tools/voice-lab/revi-reference-study/generations/sweep_temperature/sweep_log.json
tools/voice-lab/revi-reference-study/reports/FINAL_RECOMMENDATION.md
tools/voice-lab/revi-reference-study/reports/candidate_rankings.json
tools/voice-lab/revi-reference-study/reports/candidate_rankings.txt
tools/voice-lab/revi-reference-study/reports/listening_review.csv
tools/voice-lab/revi-reference-study/reports/pitch_experiment_comparison.json
tools/voice-lab/revi-reference-study/reports/reference_comparison.csv
tools/voice-lab/revi-reference-study/reports/reference_comparison.json
tools/voice-lab/revi-reference-study/reports/sweep_cfg_weight_comparison.csv
tools/voice-lab/revi-reference-study/reports/sweep_cfg_weight_comparison.json
tools/voice-lab/revi-reference-study/reports/sweep_exaggeration_comparison.csv
tools/voice-lab/revi-reference-study/reports/sweep_exaggeration_comparison.json
tools/voice-lab/revi-reference-study/reports/sweep_temperature_comparison.csv
tools/voice-lab/revi-reference-study/reports/sweep_temperature_comparison.json
tools/voice-lab/revi-reference-study/scripts/00_analyze_source.py
tools/voice-lab/revi-reference-study/scripts/01_build_candidates.py
tools/voice-lab/revi-reference-study/scripts/02_generate_candidates.py
tools/voice-lab/revi-reference-study/scripts/03_evaluate.py
tools/voice-lab/revi-reference-study/scripts/04_rank_candidates.py
tools/voice-lab/revi-reference-study/scripts/05_sweep_generation.py
tools/voice-lab/revi-reference-study/scripts/06_evaluate_sweep.py
tools/voice-lab/revi-reference-study/scripts/07_loudness_normalize.py
tools/voice-lab/revi-reference-study/scripts/08_pitch_experiment.py
tools/voice-lab/revi-reference-study/scripts/09_make_charts.py
tools/voice-lab/revi-reference-study/scripts/09b_evaluate_pitch_experiment.py
tools/voice-lab/revi-reference-study/scripts/common.py
tools/voice-lab/revi-reference-study/scripts/prompts.py
tools/voice-lab/revi-timbre-study/evaluations/en_L/original.json
tools/voice-lab/revi-timbre-study/evaluations/en_L/soft_1.json
tools/voice-lab/revi-timbre-study/evaluations/en_L/soft_2.json
tools/voice-lab/revi-timbre-study/evaluations/en_L/soft_3.json
tools/voice-lab/revi-timbre-study/evaluations/en_mono/original.json
tools/voice-lab/revi-timbre-study/evaluations/en_mono/soft_1.json
tools/voice-lab/revi-timbre-study/evaluations/en_mono/soft_2.json
tools/voice-lab/revi-timbre-study/evaluations/en_mono/soft_3.json
tools/voice-lab/revi-timbre-study/evaluations/te_R/original.json
tools/voice-lab/revi-timbre-study/evaluations/te_R/soft_1.json
tools/voice-lab/revi-timbre-study/evaluations/te_R/soft_2.json
tools/voice-lab/revi-timbre-study/evaluations/te_R/soft_3.json
tools/voice-lab/revi-timbre-study/reports/baseline_analysis.json
tools/voice-lab/revi-timbre-study/reports/baseline_analysis.txt
tools/voice-lab/revi-timbre-study/reports/comparison.csv
tools/voice-lab/revi-timbre-study/reports/comparison.json
tools/voice-lab/revi-timbre-study/reports/comparison.txt
tools/voice-lab/revi-timbre-study/reports/eq_manifest.json
tools/voice-lab/revi-timbre-study/reports/listening_review.csv
tools/voice-lab/revi-timbre-study/reports/loudness_normalization_log.json
tools/voice-lab/revi-timbre-study/reports/speaker_similarity.json
tools/voice-lab/revi-timbre-study/reports/variant_metrics.json
tools/voice-lab/revi-timbre-study/scripts/00_baseline_analysis.py
tools/voice-lab/revi-timbre-study/scripts/01_apply_softness_eq.py
tools/voice-lab/revi-timbre-study/scripts/02_loudness_normalize.py
tools/voice-lab/revi-timbre-study/scripts/03_evaluate_variants.py
tools/voice-lab/revi-timbre-study/scripts/04_speaker_similarity.py
tools/voice-lab/revi-timbre-study/scripts/05_make_charts.py
tools/voice-lab/revi-timbre-study/scripts/06_spectral_inspection.py
tools/voice-lab/revi-timbre-study/scripts/07_listening_manifest.py
tools/voice-lab/revi-timbre-study/scripts/08_rank_variants.py
tools/voice-lab/revi-timbre-study/scripts/common.py
```
