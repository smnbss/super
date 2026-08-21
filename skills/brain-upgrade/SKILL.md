---
name: brain-upgrade
description: >
  Update local tooling and sync the brain repo: brew, npm globals, uv, the vendored copies of
  super's skills, and a rebase pull. Use when the user says "brain upgrade", "upgrade tools",
  "update tools", "update my tooling", "sync my skills", or asks whether the local setup is
  current. Also invoked as Part 1 of `brain-morning-start`.
---

# Brain — Upgrade

Bring local tooling and the brain checkout up to date. Everything here is a script or a package
manager — **no phase in this skill needs a model to decide anything**, so run the commands and report
what moved.

**This skill does not touch content.** It exports nothing, rebuilds no memory, and never runs
`gbrain sync` — the index is refreshed after content is written, not after tools are updated. Run
`brain-pull-sources` / `brain-rebuild-memory` for content, or `brain-morning-start` for the whole
routine.

## Step 1 — Package managers (parallel)

Run concurrently in the background, then collect:

- `brew update && brew upgrade` — may fail on casks needing interactive sudo (e.g. `windows-app`).
  **Non-fatal in a scheduled run**: report and move on.
- `npm update -g`
- `uv sync --upgrade`

## Step 2 — Vendored-skill drift (run the script, never do this with a model)

super's canonical `skills/` (20 directories) is copied into several vendored trees, and they drift:

```bash
github/smnbss/super/bin/resync-vendored-skills --check   # exit 1 = drift; prints which copies
github/smnbss/super/bin/resync-vendored-skills           # fix, then re-verify
```

Why it is a script and not a model task: on 2026-08-18 applying one version bump and re-syncing one
drifted copy cost **4.3M tokens**, and the same drift had appeared **four mornings running**. It is a
diff and a copy.

What the script guarantees, so you don't have to reason about it:

- **Syncs per skill directory and never deletes.** Two of the copies are combined trees holding other
  people's skills (the Drive `.agents/skills` has 196 against super's 20), so a tree-level
  `rsync --delete` or a symlink would destroy them.
- **Skips any tree that does not already carry super's skills.** `~/.claude/skills`,
  `~/.agents/skills` and `~/.codex/skills` all exist and hold *other* skills; syncing into them would
  be a new global install of 20 skills nobody asked for, not a resync.
- **Refuses to overwrite a copy whose file is newer** than canonical, rather than silently clobbering
  a local edit.

⚠️ **Drift is not cosmetic — it silently corrupts data.** On 2026-08-14 Outline exported **stale
content for a full day with a clean exit status**, because the installed skill copy had drifted from
canonical. **The exit status describes the exporter, not the export.** Treat a non-zero `--check` as a
real finding, not housekeeping.

⚠️ **Patch canonical first, always.** Fix bugs in `github/smnbss/super/skills/<skill>/`, then resync.
The vendored copies are distribution artifacts; patching one of them leaves the bug in place for every
future install and every other machine.

## Step 3 — Pull the brain repo

```bash
git pull --rebase --autostash
```

`--autostash` is **required**: leftover working-tree WIP from a prior session otherwise aborts the
pull with *"cannot pull with rebase: You have unstaged changes"*.

## Step 4 — Report

One line, naming what actually moved:

```
Tools: brew <N> upgraded · npm/python <status> · skills <in sync | N copies resynced> · git <status>
```

Flag errors and notable version bumps. **A run where nothing moved is a good outcome, not a
misfire** — say "already current" rather than reporting nothing.
