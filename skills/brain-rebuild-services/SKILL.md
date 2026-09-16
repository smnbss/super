---
name: brain-rebuild-services
description: >-
  RETIRED redirect. A repo documents itself in its own docs/ tree. Use this to
  find where a service's architecture documentation lives, and which skill
  writes it. This skill generates nothing.
---

# brain-rebuild-services — RETIRED, kept as a redirect

🚨 **THIS SKILL NO LONGER GENERATES ANYTHING. DO NOT INVOKE IT TO PRODUCE A DOC.**

Simone deleted `outputs/services/weroad` on 2026-09-15 — 50 files — and the `services` phase sits
in `morning_start.skip_phases` permanently. **There is no weroad target left to regenerate.**
This file stays only so an agent that routes here learns where to go instead.

⚠️ **DO NOT CREATE A SERVICE DOC FOR ANY WEROAD REPO ANYWHERE.** Nothing regenerates one, and a
hand-written one has no home. **A repo documents itself.**

## Where a service's documentation lives now

**`github/<org>/<repo>/docs/`.** Read it in this order:

1. `docs/documentation-guide.md` — the repo's own product names, canonical service names, related
   repos, terminology and grouping decisions. **Read this first. It overrides every general rule.**
2. `docs/domain/index.md` — the domain corpus entry point.
3. `docs/domain/tech/features/_features.md` — the area map.
4. `docs/project/` — the developer-facing technical layer (architecture, patterns, debugging).

Four traps, each measured:

1. ⚠️ **IN A MONOREPO THE TREE SITS UNDER THE PACKAGE**, not the repo root. `booking` carries
   `booking/docs/` **and** `booking/api/docs/`, `booking/checkout/docs/`, `booking/admin/docs/`.
   **Name the package you read.**
2. ⚠️ **A FLAT `docs/*.md` IS THE COMMON CASE, NOT AN EMPTY ONE.** A repo without `docs/domain/`
   is not undocumented.
3. ⚠️ **A REPO WITH NO `docs/` TREE FALLS BACK TO `src/outline/`** — the docs.weroad.com mirror.
   Measured 2026-09-17: 75 repos under `github/weroad/` carry a `docs/` tree, and 53 of those
   carry the `coverage.yml` stamp. **Re-measure both figures every run. Never carry one forward.**
4. ⚠️ **`docs/domain` IS A CLOSED CORPUS.** It links only within itself and never links the
   technical layer. Do not expect a path from one to the other.

## Which skill writes it

**None in this repository.** The `code-documentation` plugin owns them, in `weroad/jungle/ai`:

| Task | Skill |
|---|---|
| A repo has no docs structure | `docs-init` |
| A repo has no feature docs at all | `docs-backfill` |
| A feature shipped or changed | `docs-feature` — run it BEFORE opening the pull request |
| The corpus is behind the convention | `docs-upgrade` |
| Rebuild the glossary alone | `docs-glossary` |

⚠️ **A DOCS CHANGE BELONGS IN THE REPO, ON A BRANCH, IN A PULL REQUEST.** Never write into a clone
under `github/` from a brain skill. `pull_sources` skips any clone with uncommitted changes, so a
write there makes that repo stale and invisible to every later health figure.

## How to tell whether a repo's docs are behind its code

The docs convention stamps `docs/domain/tech/features/coverage.yml` with `source_commit:` (the sha
the docs were generated from) and `watched_roots:` (the paths a docs change must follow).
**That pair replaces the deleted `<!-- verified: … head: … -->` stamp.**

⚠️ **SCOPE THE DIFF TO `watched_roots`.** A commit outside them does not stale the docs, and an
unscoped diff reports every repo as drifted every run.

The sweep lives in one place, in `brain-morning-start`'s **Part 1 → 1b docs-drift sweep**. Read it
there rather than copying it — one copy, re-measured from disk each run.

⚠️ **`NO-STAMP`, `BAD-SRC` and `LOST-SHA` are findings, not errors to swallow.** `LOST-SHA` means
the recorded commit is absent from the clone, so the drift is **unmeasurable, not zero.**

## What survives in `outputs/services/`

**5 files, all NON-weroad**, re-measured 2026-09-16 with `find outputs/services -type f | wc -l`:
`smnbss/{super,paperclip,weprep,weprep.db}` and `NikolaiGoMedicus/personio-mcp-server`.
⚠️ **NO BYTE CAP GOVERNS `outputs/services/` ANY MORE.** The 65,536 B cap and every byte figure
attached to it described files that no longer exist. **Never repeat one.**

⚠️ **`outputs/services/archive/` AND `outputs/services/TRAPS-from-deleted-docs.md` BOTH NO LONGER
EXIST.** The TRAPS file and the three cross-cutting RabbitMQ docs were **not** per-repo generated
docs, and **nothing can recreate them.** They survive only in git:
`git show 8d4188326:outputs/services/<path>` (verified 2026-09-16).

## Recovering a deleted doc

`git show <sha>:outputs/services/<path>`. ⚠️ **Seven of the 17 deleted on 2026-09-14 were
force-removed carrying uncommitted rebuild work, and THAT regeneration is not in git.** The last
committed version of each doc is.
