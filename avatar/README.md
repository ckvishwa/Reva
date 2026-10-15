# avatar/

The avatar page: three.js + `@pixiv/three-vrm`, bundled locally (no CDN), shared by the Windows app (WebView2) and the Android app (WebView). It shows only true state (see CLAUDE.md safety invariants).

```
npm ci
npm run build     # dist/: avatar.js (everything inside), index.html, the model (from assets/avatar/, Git LFS)
npm test          # unit tests: events vs the JSON Schema, state/epoch/mouth/face rules, 60 fps cap, lip-sync offset
npm run test:e2e  # browser tests in Edge: offline load, CSP, no network, drawing stops when off
node scripts/poses.mjs   # one screenshot per pose into docs/avatar/poses/
```

Pinned: `three` 0.186.1 (2026-09-24), `@pixiv/three-vrm` 3.5.5 (2026-07-09), both MIT and more than 14 days old; dev tools `esbuild` 0.28.2, `ajv` 8.20.0, `playwright-core` 1.63.0.

## How the host talks to the page

Host to page only: WebView2 `PostWebMessageAsJson`, or `window.revaAvatar.handle(message)` (Android `evaluateJavascript`). The page answers with `avatar.ready` or `avatar.error` and nothing else. Messages are validated (`src/protocol.js`, checked against `contracts/avatar-events.schema.json`) before anything uses them; a refused message changes nothing.

| Message | Effect |
|---|---|
| `avatar.state` (idle, listening, thinking, speaking, approval, error) | Pose. A message from an older `turn_epoch` is dropped. Leaving `speaking` closes the mouth at once |
| `avatar.mouth` (`rms` or `viseme`, `turn_epoch`) | Moves the mouth, only while the state is `speaking` and only for the current epoch; closes by itself if the host goes quiet for 150 ms |
| `avatar.expression` (`name`, `cause`, `action_id`) | Face. Neutral during `approval`, sad on `error`; a result face needs `verified_outcome` + `action_id` and fades back after 4 s |
| `avatar.settings` (`enabled`, `reduced_motion`, `quality`) | Off stops drawing; reduced motion = no blends, no sway; low quality = 30 fps, smaller pixel ratio |

Query parameters: `?model=name.vrm` (a plain local file name only), `?debug=1` (exposes frame data to tests).

## Model

`assets/avatar/placeholder.vrm`: VRM1_Constraint_Twist_Sample by pixiv Inc. (VRM Consortium licence 1.0, redistribution and modification allowed; see `docs/licenses/THIRD_PARTY.md`). It has every face and mouth shape the persona needs. The owner's `reva-1.0.vrm` replaces it at F0 after validation. Poses are procedural (`src/pose.js`) until VRMA clips exist.
