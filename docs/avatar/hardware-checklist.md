# Avatar: steps only you can run (B2)

Needs the app built with the avatar (see below) and the windows on your own screen and speakers.

Build the avatar once: `cd avatar; npm ci; npm run build` (Git LFS files pulled). Then build and run the Windows app; the avatar shows at the top of Talk & Today.

1. **GPU and frame rate, 10 minutes.** Open Task Manager > Performance > GPU, then run `node avatar/scripts/poses.mjs` is not needed: just leave the app on Talk & Today with Voice on and talk to REVA for a while. Note the GPU percentage for the app (target under 15%), minimise the window (GPU for the app should fall to about 0) and restore it. Send me the numbers.
2. **Lip-sync offset on speakers.** With Voice on, ask something that gets a long spoken answer. The Windows app records each mouth level it sends and the sample-clock time; from those, `avatar/src/lipsyncOffset.js` estimates the lag. Until the logging step ships with the next slice, judge it by eye on a recorded phone video (mouth against sound); the setting is `LipSyncDelayMs` (default 40).
3. **Pose screenshots.** With the real GPU, take one screenshot each of: idle, listening (hold Ctrl+Space), thinking (right after you release), speaking, approval (when a draft is waiting for confirmation) and error (stop Core while the window is open). Send them.
