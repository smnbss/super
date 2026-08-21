---
name: brain-upgrade
description: >
  Update local tooling and sync the brain repo: brew, npm globals, uv, the vendored copies of
  super's skills, gstack, and a rebase pull. Use when the user says "brain upgrade", "upgrade
  tools", "update tools", "update my tooling", "sync my skills", "upgrade gstack", or asks whether
  the local setup is current. Run it on demand — `brain-morning-start` deliberately does NOT
  invoke it.
---

# Brain — Upgrade

Bring local tooling and the brain checkout up to date. Everything here is a script or a package
manager — **no phase in this skill needs a model to decide anything**, so run the commands and report
what moved.

**This skill does not touch content.** It exports nothing, rebuilds no memory, and never runs
`gbrain sync` — the index is refreshed after content is written, not after tools are updated. Run
`brain-pull-sources` / `brain-rebuild-memory` for content, or `brain-morning-start` for the whole
routine.

**Run it on demand.** `brain-morning-start` does **not** invoke this skill — updating tools is not
something that has to happen before the day's first meeting, and the gstack gate in Step 3 was 13% of
that routine's entire cost when it did. A bare invocation runs every step; honour a caller that says
"skip gstack" or "tools only".

## Step 1 — Package managers (parallel)

Run concurrently in the background, then collect:

- `brew update && brew upgrade` — may fail on casks needing interactive sudo (e.g. `windows-app`).
  **Non-fatal in a scheduled run**: report and move on.
- `npm update -g`
- `uv sync --upgrade`

## Step 2 — Vendored-skill drift (run the script, never do this with a model)

super's own checkout is the source of truth for its skills, and the vendored copies drift from it.
**Update the install first, then resync** — in that order, because a resync from a stale install
propagates stale skills everywhere and reports success.

```bash
git -C "${SUPER_HOME:-$HOME/.super}" pull --rebase --autostash   # the super install itself
"${SUPER_HOME:-$HOME/.super}/bin/resync-vendored-skills" --check # exit 1 = drift; names the copies
"${SUPER_HOME:-$HOME/.super}/bin/resync-vendored-skills"         # fix, then re-verify
super install all --skills-only                                  # project skills into .claude/skills
```

**Run `resync-vendored-skills` from the brain root, not from `$SUPER_HOME`.** It discovers the brain's
copy via `$PWD/.claude/skills`, so running it from the wrong directory checks one fewer copy and still
prints a clean all-clear.

### Why `super install all --skills-only`, and never bare `super install`

The resync keeps the vendored copies equal to canonical; `super install` is what makes each skill
*visible to Claude Code*, by symlinking every `.agents/skills/<name>` into `.claude/skills/<name>`.
`.agents/skills` is the canonical project store and `.claude/skills` is a view of it, so a skill that
never gets projected is invisible no matter how in-sync it is.

- **`--skills-only` is mandatory here.** A full `super install` also runs the configure phase, which
  calls `cleanClaudeJsonMcps()` → `data.mcpServers = {}`. That *empties* `~/.claude.json` rather than
  removing the keys super manages, so it deletes user-scope MCPs from outside the catalog (`gbrain`,
  `mailtrap`, …). `gbrain` self-heals via a SessionStart hook; anything needing interactive OAuth does
  not, and this skill is run often enough that the loss would be routine.
- **Pass the `all` target explicitly.** With no target, `cmdInstall` falls through to an interactive
  CLI picker and an unattended run hangs there.

⚠️ **`DIVERGED and skipped` in its output is a finding, not noise.** A *real directory* at
`.claude/skills/<name>` shadows `.agents/skills/<name>`: the two stop being one store, so later writes
land on one and the other goes stale invisibly. Install repairs the case where the shadowing copy holds
nothing unique, and refuses to touch one that has diverged — those need a human to diff the two, keep
what matters, and delete the shadow to restore the symlink. Report the count; don't try to auto-resolve
them.

⚠️ **The resync syncs `skills/` and nothing else**, so it cannot update the install's own `bin/`,
`lib/` or `super.mjs`. That is a real split-brain worth checking: measured 2026-08-21, the installed
skills were current while `${SUPER_HOME}` sat **17 commits behind `origin/main`** with no `bin/`
directory at all — so the resync script itself was missing from the very place it is supposed to run
from. **If the script is not found, the pull above is the fix, not a different path.**

Why it is a script and not a model task: on 2026-08-18 applying one version bump and re-syncing one
drifted copy cost **4.3M tokens**, and the same drift had appeared **four mornings running**. It is a
diff and a copy.

What the script guarantees, so you don't have to reason about it:

- **Syncs per skill directory and never deletes.** A vendored copy can be a combined tree holding
  other people's skills, outnumbering super's by an order of magnitude, so a tree-level
  `rsync --delete` or a symlink would destroy them.
- **Targets local install roots only.** It never syncs into a cloud-synced or removable path
  (Drive/Dropbox/iCloud, external volumes) — writing a skill there uploads it, and these skills carry
  internal detail that must not leave the machine on a personal account.
- **Skips any tree that does not already carry super's skills.** `~/.claude/skills`,
  `~/.agents/skills` and `~/.codex/skills` all exist and hold *other* skills; syncing into them would
  be a new global install of 20 skills nobody asked for, not a resync.
- **Refuses to overwrite a copy whose file is newer** than canonical, rather than silently clobbering
  a local edit.

⚠️ **Drift is not cosmetic — it silently corrupts data.** On 2026-08-14 Outline exported **stale
content for a full day with a clean exit status**, because the installed skill copy had drifted from
canonical. **The exit status describes the exporter, not the export.** Treat a non-zero `--check` as a
real finding, not housekeeping.

The patch-upstream-first rule that governs *editing* these skills is a property of the brain, not of
this skill — it lives in the brain's root `AGENTS.md`.

## Step 3 — gstack (Step 2 does not cover it)

**`resync-vendored-skills` never touches gstack**, and this is structural, not an oversight: gstack
is not one of super's skills, and `~/.claude/skills` is skipped as a tree that carries no super
skills. So gstack needs its own check — a clean Step 2 says nothing about it.

**Gate on the purpose-built check. Empty output means up to date, and the step is then done at zero
model cost:**

```bash
~/.claude/skills/gstack/bin/gstack-update-check   # UPGRADE_AVAILABLE <old> <new> | JUST_UPGRADED | nothing
```

Invoke `/gstack-upgrade` **only** on `UPGRADE_AVAILABLE`, or on `JUST_UPGRADED` (which wants the
post-upgrade migration steps).

⚠️ **Never invoke it unconditionally.** It re-runs install-type detection and an interactive
`AskUserQuestion` every time, almost always to conclude nothing needed doing: measured over
2026-07-06→08-05 that was **1,589 model requests**, ~72 per run with spikes of 217 and 420. This is
why the step is a gate and not a call. `auto_upgrade` is already `true` (`gstack-config get
auto_upgrade`), so a genuine upgrade does not stop to ask.

⚠️ **If you check versions by hand, compare `VERSION` against the UPSTREAM CLONE** — never two
installed copies against each other. On 2026-08-19 the vendored and global copies both read the same
`VERSION` while upstream was already a release ahead: two matching copies prove only that they match,
not that either is current.

```bash
cat ~/.claude/skills/gstack/VERSION
cat github/garrytan/gstack/VERSION      # the only reference that can say "current"
```

**Do not use `dist/.version` for this.** It stamps the *enclosing* repo, so inside a vendored copy it
holds a brain commit and reads false-current — and on this machine both installed copies have it
empty, so it cannot answer the question at all.

## Step 4 — Pull the brain repo

```bash
git pull --rebase --autostash
```

`--autostash` is **required**: leftover working-tree WIP from a prior session otherwise aborts the
pull with *"cannot pull with rebase: You have unstaged changes"*.

## Step 5 — Report

One line, naming what actually moved:

```
Tools: brew <N> upgraded · npm/python <status> · super <up to date | N commits pulled> · skills <in sync | N copies resynced> · install <N projected, N repaired, N DIVERGED> · gstack <up to date | vA→vB | skipped> · git <status>
```

Flag errors and notable version bumps. **A run where nothing moved is a good outcome, not a
misfire** — say "already current" rather than reporting nothing.

Always surface the `DIVERGED` count from Step 2's install, even when it is unchanged from the last run —
a shadowed skill stays stale until someone resolves it, so a silent count lets it rot.
