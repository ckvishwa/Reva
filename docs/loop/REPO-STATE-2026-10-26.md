# Repository state and remaining publication work — 2026-10-26

This is a read-only reconciliation of Git refs and visible worktree status. It does not declare unfinished work tested, merged, or released. The older `CLAUDE.md` Current state entries and `MASTER-LOOP-progress.md` remain historical snapshots unless a later dated entry supersedes them.

## GitHub and local refs

- `origin/main` is `df7a3dc2451243713e9f02362141e54e1e8087fb` (C3a merge, PR #30). GitHub CI run `38934452489` succeeded at that SHA. C3b PR #31 and stacked C3c PR #32 are open drafts; Android Finance/Health PR #37 is also an open draft. Open PR state can change after this date.
- `origin/feat/gym-1-workout` is `04407ba23e68b3c54e0a9a5ff2add6ffed9c20f2`, 24 commits ahead of `main` with no divergence at this snapshot. Its GYM-02.1 emulator acceptance passed 39/39 checks. Physical-phone acceptance is `NEEDS_HARDWARE`; the branch is not merged and has no PR at this snapshot.
- Four committed local-only tips were pushed as distinct branches: `feat/agent-platform-foundation` (`8bdebbd`), `archive/shutdown-wip` (`890d610`), `wip/planner-reasoning` (`cd94566`), and `wip/slice-8a-draft` (`27277c7`). These are preservation refs, not approvals to merge. The planner commit records a failing test and lint issue; the Slice 8A commit calls itself untested reference work.
- `git rev-list --branches --not --remotes --count` returned **0** after those pushes. This proves committed branch tips are reachable from remote branches; it says nothing about uncommitted files.
- Tags `v2.0.0-alpha.0`, `.1`, and `.2` exist locally. None of those tag commits is an ancestor of current `origin/main` or `origin/feat/gym-1-workout`. Treat their tag messages as records of their own lineages, not as current-main release evidence.

## Work that is still local

- `D:\Projects\Reva` (`fixing-things`, `6ea4236`) has 23 tracked changes and 68 visible `git status` entries. They include PIPE-1 voice, Kokoro, planner, API, Windows, and test work that overlaps other branches. This checkout was not edited, staged, committed, or pushed during this reconciliation.
- `D:\Projects\Reva-gym1` retains an untracked `scratchpad/` with run logs, screenshots, pulled APKs, and synthetic backup JSON. Selected safe evidence was already committed to the Gym branch; the full scratchpad remains local.
- `D:\Projects\Reva-int` has one untracked entry. The 11 Lana-derived copies described in `CLAUDE.md` are excluded from normal status output and still require the owner's separate disposition. Do not publish or delete them during a blanket cleanup.

## Prompt for the next reconciliation pass

> Act as REVA's repository maintainer. Reconcile the remaining unpublished **uncommitted** work without changing the original dirty checkout at `D:\Projects\Reva`. Start from current GitHub refs, `CLAUDE.md`, worktree instructions, and this inventory. Confirm all branch and PR heads again because they may have moved. Inventory each dirty or excluded path, then classify it as already present on a remote branch, unique code, generated or local evidence, sensitive/private material, or uncertain. Compare content, not just filenames. Never commit or push the 11 excluded Lana-derived copies, keys, model assets, backup data, or arbitrary `scratchpad/` files. Do not discard or reset any user work.
>
> For unique safe code, choose the correct parent branch, copy only the intended files into a clean worktree, run the relevant tests and security checks, commit with the configured owner identity, and push a clearly named branch without force. Keep known failing or untested work labeled WIP; do not merge it or claim PASS. Preserve the original files until the owner verifies the remote commit. Update `CLAUDE.md` and the evidence ledger only with results actually verified at exact SHAs. Report every file still local, each branch pushed, any test failures or hardware gates, and the recommended next slice. Do not merge into `main`, tag a release, or delete files without a separate request.
