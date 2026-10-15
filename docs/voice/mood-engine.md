# Mood engine (B2a)

`reva_core/language/mood.py` is the persona's mood engine (docs/persona/REVA_Persona.md section 3) as a pure function:
`next_mood(previous_state, inputs) -> MoodResult`. No model, no I/O, no clock read (the caller passes local time).

Rules are data: `contracts/mood-rules.v1.json` (priority, thresholds, decay, restricted moods, voice parameters,
avatar mapping, acknowledgement phrases, forbidden phrases). Core reads its packaged copy
`reva_core/language/data/mood-rules.v1.json`; a test keeps the three copies (contracts, spec pack, package) equal.
Android reads the same file and must pass the same fixtures (phase C parity suite).

Judgement calls where the persona text pulls two ways:

- Failures. "Finance, Health, Memory, errors, approvals, refusals sound Calm or Concerned only" and "Sad: an action failed"
  (with a sorry template for an unconfirmed outcome) both appear. Resolved: after a **failure** the mood may also be Sad;
  nothing cheerful is ever allowed on a sensitive turn or an error.
- Approvals. The avatar uses the approval pose with a neutral face; no mood expression while an action is pending.
- Result moods. Happy and Excited are about results, so they produce an `avatar.expression` only with
  `cause = verified_outcome` and the action id. Without evidence there is no expression event at all.

What the Core does with it (`TurnPipeline`): each reply event carries `mood` (name, template variant, voice, avatar) and,
when allowed, an `avatar_event` ready for the avatar page. The speaking rate goes to the voice (clamped to 0.8 to 1.2)
when the provider accepts it (Kokoro does). Pitch and softness are recorded but not applied yet: Kokoro has no such control.
No executor exists before S09, so nothing is ever "verified" on this path and Happy cannot occur yet.

Schema: `avatar-events` is now 2.1 (minor bump): `avatar.expression.cause` gains `mood`.
