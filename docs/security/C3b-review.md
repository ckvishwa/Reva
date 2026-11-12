# C3b security review

Reviewed code: `brain/ModeController.kt`, `HostedPlanner.kt`, `HostedSecrets.kt`, `SharedPrefsModeSettings.kt`, app wiring and More/Talk UI. The hosted transport uses a fixed HTTPS endpoint, OS trust, no redirects, bounded response, no tool use, and no transcript/key logging. Unit capture verifies default-off and known sensitive negative cases make zero transport calls. Android Keystore protects the provider key at rest. Revocation during key read stops egress; revocation while awaiting a response discards it. Hosted text is never interpreted as verified action evidence.

Findings fixed during review: a planner deadline originally returned an unknown result without switching mode; a failing test established the gap, and a seven-second hosted deadline now moves to Offline-lite. A response such as "Done, Calculator is open" was initially accepted as plain text; the action-claim guard now rejects it. The first filter missed "my checking balance" and an email address; negative capture tests and a stricter filter were added. Mode controls now stack vertically to fit narrow displays.

The final consent boundary does not depend on classifying text: either domain consent off forces Offline-lite and makes the hosted planner refuse all requests. The lexical filter is defense in depth. This intentionally restricts even public hosted questions until both consents are on, and the UI explains the restriction.

Open finding: paired open-question delegation is absent because the signed PC gateway exposes no generic planner endpoint. Physical microphone, key, and PC/offline transitions remain `NEEDS_HARDWARE`. No release tag is justified.
