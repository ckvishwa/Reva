# C2c Android sender review

The phone side of phone-to-PC actions (open/close an app on the PC) and the phone's own actions (alarm,
reminder, calendar, share, open an approved app) merged cleanly with C2b's Windows pickup side. The
merge conflicts git reported in `RevaApp.kt`, `TalkScreen.kt`, `VoiceController.kt`, `Outcomes.kt`,
`PolicyReplies.kt`, `AuthorizeParityTest.kt` and `tests/fixtures/rules-cases.json` all resolved to C2c's
own tip: C2c's `pcrequests`/`phone` packages are a newer superset of what C2b's android-side glue
(`SignedPcGateway`/`ApprovedApps`) did on an earlier common ancestor. Verified in the merged tree that
`PcRequestTracker`, `PhoneActions`, `VoiceController.postReply`, `PcRequestCard`, `PhoneActionCard` and
`PolicyReplies(registry, pc=, phone=)` are all present and wired — no C2b functionality was dropped by
the resolution. Desktop-side C2b work (`PhoneRequestPoller.cs`, devices API/UI) merged untouched.

## Security invariants (executable coverage)

All ten required by this slice have existing passing tests once the Kernel binding is built:

1. Authenticated pairing required — `test_a_phone_paired_without_action_scopes_can_ask_for_nothing`,
   `test_the_gateway_has_no_inbox_and_no_approval_the_phone_can_reach`, `test_no_credentials_no_service_on_the_action_routes`.
2. Revoked devices cut off — `test_revoking_a_phone_withdraws_what_it_asked_and_the_pc_never_runs_it`.
3. No duplicate execution from a request id — `test_sending_the_same_request_again_is_one_action_not_two`,
   `test_the_same_id_with_different_content_is_refused_not_merged`.
4. Expiry fails closed — `test_a_request_that_sat_too_long_is_refused_as_expired`,
   `test_an_approval_that_waits_too_long_expires_and_nothing_runs`.
5. Replay rejected — `test_a_replayed_signed_request_is_refused_and_does_not_act_twice`.
6. T2 PC actions need a PC-side click — `test_a_phone_request_to_close_waits_for_a_click_on_this_pc_and_never_a_phone_tap`.
7. The phone cannot approve its own privileged action — the same test above also tries a spoken
   "yes", a `via="tap"` approval carrying the phone's own device id, and the phone's gateway route
   directly (`/actions/approve` — 404, no such route exists for a phone); only the PC's
   `/v1/actions/{id}/approval` with `via: click` grants it.
8. Capability/argument allowlist — `test_the_phone_can_not_ask_for_anything_outside_the_allowlist`,
   `test_an_unknown_app_or_extra_arguments_are_refused_before_anything_is_granted`,
   `test_oversized_or_malformed_requests_are_422`.
9. Rate limit without breaking idempotent retries — `test_completed_requests_are_rate_limited_per_phone_without_blocking_retries`,
   `test_one_phone_cannot_fill_the_broker_and_starve_this_pcs_own_actions`.
10. Completion reflects real executor evidence, never assumed — `test_open_is_granted_to_the_pc_and_the_phone_hears_done_only_after_the_executor_reports`,
    `test_a_verified_report_without_evidence_is_unknown_never_done`, `test_a_failure_the_phone_hears_is_a_failure`.

No gaps found; no new tests were needed. Before this pass all 47 of these tests (`tests/gateway/test_phone_actions.py`,
`tests/gateway/test_listener.py`) were silently **skipped** ("Domain Kernel binding not built"), not
passing — the 10 invariants were unverified in this environment until the binding was built (Strawberry
Perl, already installed at `C:\Strawberry\perl`, just not first on `PATH`, was required for the vendored
OpenSSL build; `tools/kernel/build_bindings.py` then succeeds). With the binding present: 97 passed, 0
skipped, 0 failed across the gateway/security/contract subset; no code defects found, so no fixes were
needed.

Remaining unverified: the same logic end to end against a real Android device signing with the real
Keystore and a real paired PC, and the instrumented `KernelConformanceTest`/`KeystoreSignerInstrumentedTest`
on-device (need the Android-ABI native library, cross-built separately — see ledger). `NEEDS_HARDWARE`.
