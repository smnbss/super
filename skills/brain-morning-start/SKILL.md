---
name: brain-morning-start
description: >
  Daily bootstrap: sync brain sources, rebuild memory and service docs, and harvest meeting
  notes since the last harvest. Use when the user says "morning start", "start my day", "daily
  bootstrap", or "morning routine". Does NOT update tools and does NOT prepare meeting agendas —
  `brain-upgrade`, `brain-prepare-my-deep-dives` and `brain-prepare-my-one-on-one` are all run
  separately, on demand.
---

# Morning Start

Daily bootstrap: sync brain sources, rebuild memory + service docs, harvest every meeting since the
last harvested day, then refresh the gbrain index in one pass.

## How to run this (keep the orchestrator lean)

**Delegate each heavy phase to a subagent and keep only its summary.** Parts 1, 2 and 3 each do
bulky work. Spawn an `Agent` per phase that invokes the named skill and returns **counts and errors,
not file dumps** — the verbose output stays in the subagent. Each sub-skill carries its own
instructions; dispatch and collect, do not restate them here.

### ⚠️ Write the run's findings to ONE briefing file. Never paste them into each dispatch.

**A finding repeated across N dispatch prompts is paid N times.** Measured 2026-09-10: the same
~10K-token block of source deltas, service-doc findings and open decisions was pasted into **eight
separate worker prompts** — about **80K tokens of pure duplication**, for content that had a single
source of truth.

**Do this instead:**

1. Write the run's findings ONCE to `outputs/agents/brain-morning-start/<date>-briefing.md`.
2. In each dispatch, give the **path** plus the two or three lines that worker specifically needs.
3. Tell the worker to read the briefing for context it does not already have.

⚠️ **Give a worker the findings that bear on ITS target, not the whole register.** A `team-stomp`
worker does not need the gdrive export traps. The briefing exists so the shared context is
addressable, **not so every worker reads all of it** — that would just move the duplication from
the prompt into the worker's first tool call.

⚠️ **This is one of only three real levers on run cost**, alongside fewer workers and a smaller
always-loaded `AGENTS.md`. A worker's opening context is ~130K tokens of which only about **1.4%**
is its own task prompt — so the prompt is not where the bulk sits, but duplicated bulk is the one
part of it you control completely.

**Gate every phase on a deterministic signal before spending a model on it.** `brain-pull-sources`
moves 82 declared sources for ~7 model requests because it is a script; `brain-rebuild-services` was
**55% of the entire routine** until it was gated on `.github-changed-repos.tsv`, because nothing told
it which repos to look at so it re-derived that across 137 clones every morning. A phase that reports
"nothing to do" for zero cost is the goal, not a misfire.

**Never trust a subagent's "done" — verify by filesystem state.** Sub-skills spawn their own
workers, and wrapper subagents return before those workers finish (observed 3× on 2026-07-14:
pull_sources still exporting, memory "Wave 1 dispatched" with 0 files written).

1. Tell every phase subagent: *do the work inline in your own context; do NOT dispatch detached
   background workers and return* — orphaned workers write nothing. If it spawns helpers it must
   block on them and verify their writes before returning.
2. On an ambiguous or early return, check output-file **mtimes** and live processes. Match workers by
   **command + start time**, never by name — long-`etime` `claude` processes are unrelated sessions.
3. ⚠️⚠️ **ONE BLOCKING WAIT PER PHASE. NEVER POLL.** A wait belongs **inside one shell call**, where
   blocking is free. One `Bash` call costs one request whether it returns in 1 second or 20 minutes;
   re-invoking the model to look again re-sends the whole orchestrator context each time (measured
   2026-08-18: 219 orchestrator requests, ~40 substantive — the rest were wake-ups).

   ```bash
   until <completion-predicate>; do sleep 20; done; echo PHASE-DONE      # ONE request
   ```

   Bound a phase that can hang in the *same* call: `timeout 3000 bash -c 'until …; do sleep 20; done'`.
   Use `run_in_background: true` only when you have other substantive work meanwhile — never to
   check back repeatedly.
4. ⚠️ **Use the phase's OWN predicate — a narrower one silently truncates it.** "Expected outputs
   exist" is not safe: waiting on `memory/**/*.md` does not match `AGENTS.md` at the repo root, so on
   2026-08-18 the memory phase was declared done early and `AGENTS.md` **missed the commit entirely**.
   Watch the whole tree a phase writes.

   | Phase | Completion predicate |
   |---|---|
   | 1a `brain-pull-sources` | `[ -z "$(find src github -newermt '-90 seconds' -type f 2>/dev/null \| head -1)" ]` |
   | 1b docs-drift sweep | **no wait — it writes nothing.** It is a read-only report. Assert the sweep printed a list (possibly empty) and carry it to Part 4 |
   | 2a meeting harvest | **no separate wait — it is a lane INSIDE 1a.** After 1a, assert a per-day `index.md` exists for every day since the last harvest |
   | 1c `brain-rebuild-memory` | `[ -z "$(find memory AGENTS.md DEVELOPER.md -newermt '-90 seconds' 2>/dev/null \| head -1)" ]` — the generator writes all three |

   **Before Part 3's commit, run `git status --porcelain` and read it.** It is the only check that
   cannot miss a file by construction. An unexpected *absence* is as informative as a presence.
5. Never launch a duplicate export/rebuild while the previous one is still running.
6. ⚠️⚠️ **EVERY `Agent` DISPATCH — INCLUDING ONES A SUB-SKILL SPAWNS INTERNALLY — MUST PASS
   `subagent_type: "general-purpose"` EXPLICITLY.** The `wr-agents` plugin ships a `PreToolUse` hook
   (`enforce-subagents.sh`) that forces an interactive confirmation whenever an `Agent` call **without**
   `subagent_type` (which defaults to `"claude"`) mentions a known jungle service or repo name
   (`coordinators`, `cashew`, `terraform`, …) — which service-doc and team-L2 dispatches do routinely.
   That ask **overrides bypass-permissions by design**, so on an unattended run it stalls forever with
   nobody to answer it (confirmed 2026-08-20: a `team-stomp.md` worker blocked a run for hours on its
   own "coordinators" mention). `general-purpose` is allow-listed and is the correct type regardless —
   these workers synthesize markdown and call MCP tools, never a stack-specialist persona. Tell every
   sub-skill you invoke to do the same, `brain-rebuild-memory` above all since it fans out its own workers.

## Phase gating — check this BEFORE dispatching anything

Some phases are disabled per-brain in `$BRAIN_CONFIG` under `morning_start.skip_phases`. **Check
the gate first. A skipped phase costs zero model requests.**

```bash
.claude/skills/brain-morning-start/bin/phase-enabled --list          # what is on and off
.claude/skills/brain-morning-start/bin/phase-enabled services        # exit 0 = RUN, 1 = SKIP
```

Gate each of the four phases on its own name: `services` (1b), `additional` (1b.5), `meetings`
(2b), `memory` (1c). **Part 1a and the 2a harvest always run** — they are `pull_sources`, and they
are what keeps `src/` current.

⚠️ **A MISSING OR UNREADABLE CONFIG MEANS RUN EVERY PHASE.** The gate fails open on purpose: a
typo must not silently skip the rebuild that keeps memory current.

⚠️ **SKIPPING A PHASE DOES NOT MEAN ITS WORK IS DONE. IT MEANS ITS OUTPUTS ARE GOING STALE, AND
NOTHING DOWNSTREAM REPORTS THEM AS STALE.** A skipped `services` phase means the docs-drift sweep
does not run, so **nothing tells you how far any repo's `docs/` tree is behind its clone.** A
skipped `memory` phase leaves `verified:` dates that look current because they were correct on
their own date.

⚠️ **SAY WHICH PHASES WERE SKIPPED, AND WHY, IN THE PART 4 REPORT.** A run that silently does less
than the reader expects is worse than one that fails. Print the `--list` output.

⚠️ **A SKIP IS A STANDING CONFIG VALUE, NOT A ONE-RUN DECISION.** It stays until someone edits the
config. Re-read it every run — never remember that a phase "was disabled".

## Part 0 — First-run bootstrap

If `agents/morning-start-additional/SKILL.md` (relative to the brain root) does not exist, seed it
once from `resources/morning-start-additional.template.md` (relative to this skill).

## Part 1 — Brain sync & rebuild (sequential chain, subagent per phase)

- **1a `brain-pull-sources`** — export all external sources → `src/`. Heavy. ⚠️ **This includes the
  gmeet harvest (Part 2a), because `sources.md` declares it. Do NOT start a second `gmeet_to_md`
  alongside it.** Part 2b, the digests, runs **after** 1a because it reads what 1a wrote.
- **1b docs-drift sweep** — report which repos' own `docs/` trees are behind their clones. *After 1a.*

  🚨 **THIS PHASE NO LONGER GENERATES ANYTHING, AND IT IS PERMANENTLY SKIPPED BY DEFAULT.**
  `outputs/services/weroad` was deleted on 2026-09-15 (50 files) and `services` sits in
  `morning_start.skip_phases`. **`brain-rebuild-services` has no weroad target left. Do not
  invoke it.** **A repo documents itself now**, in its own `docs/` tree.

  ⚠️ **AND THIS PHASE MUST NOT WRITE.** A docs change belongs in the repo, through `docs-feature`
  or `docs-backfill`, on a branch, in a pull request. **Never commit into a clone under
  `github/`** — `pull_sources` skips any clone with uncommitted changes, so a write here makes
  that repo stale and invisible to every later health figure.

  **What 1b produces is a LIST for the Part 4 report.** Nothing else.

  **Read the work-list before dispatching anything.** `.github-changed-repos.tsv` is written by 1a,
  one line per repo whose HEAD moved.

  ```bash
  wc -l < .github-changed-repos.tsv
  cut -f1 .github-changed-repos.tsv
  ```

  ⚠️⚠️ **THE LEDGER IS A STARTING POINT, NOT THE WORK-LIST. GATE ON DRIFT, NEVER ON MOVEMENT.**
  The ledger
  records *"HEAD moved during this run"*, which is a different question from *"are this repo's docs
  behind its clone?"*. A repo whose HEAD moves on a day its docs are **not** regenerated — the run
  failed, was interrupted, or the clone was skipped for uncommitted work — never appears in a later
  ledger, so a ledger-driven work-list can **never** repair it. Measured 2026-09-17 against the
  repos' own `coverage.yml` stamps: **53 stamps · 39 DRIFTED · 2 NO-STAMP · 5 LOST-SHA**.
  ⚠️ **Do not carry those four figures forward — re-measure every run.**
  The same shape was measured on the old `outputs/services/` gate, which caught `weroad/cli` (3 files stale)
  plus **both** `.db.agent.md` docs, for `wemeet-hosted-ops` and `wetracker` — **all three absent from
  that day's 56-line ledger.**

  **Zero ledger lines does NOT mean zero work.** Run the divergence sweep anyway.

  ⚠️ **GATE ON THE REPO'S OWN COVERAGE STAMP, NOT ON A BRAIN-SIDE DOC.** The docs convention
  writes `docs/domain/tech/features/coverage.yml` carrying `source_commit:` (the sha the docs were
  generated from) and `watched_roots:` (the paths a docs change must follow). **That pair is the
  replacement for the deleted `<!-- verified: … head: … -->` stamp.** Measured 2026-09-17:
  53 repos under `github/weroad/` carry one.

  ⚠️ **SCOPE THE DIFF TO `watched_roots`. A CHANGE OUTSIDE THEM DOES NOT STALE THE DOCS**, and an
  unscoped diff reports every repo as drifted on every run, which trains the reader to ignore the
  list.

  ```bash
  # ⚠️ THREE TRAPS LIVE IN THIS LOOP AND ALL THREE FAIL SILENTLY.
  #
  # 1. NEVER name a shell variable `path`. In zsh `path` is a special array TIED TO $PATH, so
  #    `read -r repo path` overwrites PATH and EVERY later command in the loop dies with
  #    "command not found" - grep, head, cut and git all fail, every stamp comes back empty, and
  #    the rule below reads that as "inert, do not report". Measured on a real ledger
  #    2026-09-04: 0 work-list entries against a true 25.
  #
  # 2. NEVER glob the doc path with `**` inside double quotes. `**` does not recurse without
  #    globstar, and inside double quotes it is not glob-expanded at all, so the consumer gets a
  #    literal path that never exists and the whole sweep reads as inert. USE `find`.
  #
  # 3. ANCHOR the stamp read to the start of the line (`^source_commit:`). A bare grep matches the
  #    first sha-shaped string anywhere in the file, and coverage.yml carries many `source:` paths
  #    with line numbers below it.
  #
  # 4. DO NOT `find github -maxdepth 4` FOR THE COVERAGE FILE. The file sits 8 or 9 path segments
  #    deep (`github/<org>/<repo>/docs/...` and `github/weroad/jungle/<repo>/docs/...`), so a
  #    maxdepth-4 find returns NOTHING and reads as "no repo has drifted". Measured 2026-09-17:
  #    0 hits against a true 53. Drive the loop from the REPO DIRS instead - it is also far
  #    cheaper than an unbounded find over a 446K-file tree.
  #
  # Drive the loop from the REPOS, not from the ledger - that is what makes it a drift gate.
  for repo_root in github/*/*/ github/weroad/jungle/*/; do
    repo_root=${repo_root%/}
    cov="$repo_root/docs/domain/tech/features/coverage.yml"
    [ -f "$cov" ] || continue
    rec=$(grep -m1 -oE '^source_commit: *[0-9a-f]{7,40}' "$cov" | grep -oE '[0-9a-f]{7,40}$')
    [ -z "$rec" ] && { echo "NO-STAMP $repo_root"; continue; }
    [ -d "$repo_root/.git" ] || repo_root=$(git -C "$repo_root" rev-parse --show-toplevel 2>/dev/null)
    [ -n "$repo_root" ] && [ -d "$repo_root/.git" ] || { echo "BAD-SRC $cov"; continue; }
    git -C "$repo_root" cat-file -e "$rec^{commit}" 2>/dev/null || { echo "LOST-SHA $repo_root $rec"; continue; }
    cur=$(git -C "$repo_root" rev-parse HEAD 2>/dev/null)
    case "$cur" in "$rec"*) continue;; esac          # MATCH, nothing to do
    # Scope the diff to watched_roots. No roots declared = whole repo.
    roots=$(sed -n 's/^watched_roots: *\[\(.*\)\]/\1/p' "$cov" | tr -d '"' | tr ',' ' ')
    changed=$(git -C "$repo_root" diff --name-only "$rec..HEAD" -- $roots 2>/dev/null)
    [ -z "$changed" ] && continue                    # moved, but not under watched_roots
    printf '=== %s | %s..%s\n%s\n' "$repo_root" "$rec" "${cur:0:8}" "$changed"
  done
  ```

  A repo whose scoped file list comes back **empty is inert — do not report it as drifted.** Its
  HEAD moved outside `watched_roots`, which is exactly the case the scoping exists to filter out.

  ⚠️ **`NO-STAMP`, `BAD-SRC` and `LOST-SHA` are findings, not errors to swallow.** `NO-STAMP` means
  the docs were never generated by the convention. `LOST-SHA` means the recorded commit is not in
  the clone — usually a force-push or a shallow clone — and the drift is **unmeasurable**, not zero.
  **Report each one and correct nothing until a human decides.**

  ⚠️ **A REPO WITH NO `docs/` TREE AT ALL IS THE LARGER GAP, AND THIS LOOP CANNOT SEE IT.** The
  sweep is driven by existing `coverage.yml` files, so a repo that never adopted the convention
  never appears. **List those separately** — they are `docs-init` / `docs-backfill` candidates:

  ```bash
  for d in github/*/*/ github/weroad/jungle/*/; do
    [ -d "$d/.git" ] || continue
    [ -d "$d/docs" ] || echo "NO-DOCS $d"
  done
  ```

  ⚠️ **STATE THE SCOPE OF THAT NEGATIVE.** A skipped clone is stale and invisible here, and
  `github/` is gitignored so `rg` will not see it either.
- **1b.5 additional agents** — if `agents/morning-start-additional/SKILL.md` exists, run its
  `run <path>` directives in order. *After 1b, before 1c.*
- **1c `brain-rebuild-memory`** — rebuild L2 + L1 → `memory/`, plus `AGENTS.md` and `DEVELOPER.md`.
  It only **writes markdown** — the gbrain index is refreshed by the single `gbrain sync` in Part 3.
  **No gbrain step inside 1c.** *After 1b.5.*
  ⚠️ **Never state the L1/L2 file counts here or in the dispatch prompt. Re-measure them from disk**
  (`ls memory/L1/*.md | wc -l`, `ls memory/L2/*.md | wc -l`). A count written into a skill file is a
  count nobody re-measures, and it goes stale silently.

  ⚠️⚠️ **PASS THE `AGENTS.md` BYTE BUDGET INTO THE 1c DISPATCH, AND MEASURE IT BEFORE AND AFTER.**
  `AGENTS.md` is loaded into every session on every surface, because `CLAUDE.md` and `GEMINI.md` are
  symlinks to it. **Measured 2026-09-04 it had reached 210,519 B, about 58,500 tokens per session,
  because it was the one generated page on this brain with no cap and no rotation target.** Its
  `## Repository Layout` block was 125,983 B, and only 2,645 B of that was actual layout — 98% was
  dated run-log narrative already duplicated in the `memory/L1` pages that own it.

  ```bash
  stat -f '%z' AGENTS.md    # target ≤ 61,440 B · hard warn at 81,920 B
  ```

  The generator carries the rule (`brain-rebuild-memory` §3.5a-2, "the eviction rule"): a **durable
  trap** is copied through verbatim forever, a **dated run-log line** is written to the owning
  `memory/L1` page and left out of `AGENTS.md`. **Your job here is only to measure and report** —
  ⚠️ **never instruct the subagent to cut a caveat to hit the number.** The carry-through rule
  outranks the budget. If the file cannot fit on durable content alone, that is a finding for
  Simone, not something to fix by deleting.

## Part 2 — Meeting digests (2a runs INSIDE Part 1a)

**2a — Harvest raw artifacts (deterministic, no LLM). ⚠️ DO NOT RUN THIS YOURSELF. Part 1a
ALREADY DID IT.** `sources.md` declares `gmeet_to_md <gws-email>` as an ordinary source, so
`pull_sources` harvests gmeet in its own tool lane on every run. It walks Calendar, discovers Drive
artifacts (Gemini notes, agendas, recordings, attachments, transcripts) and writes per-meeting
folders plus a static per-day `index.md` under `src/gmeet/YYYY/WNN/MM-DD/`. It is idempotent, the
full-span re-harvest self-heals gaps, and it **preserves existing `*-digest.md` and `transcript.md`**.

⚠️ **A SECOND COPY IS A DUPLICATE AND IT IS ALSO NARROWER. Launching one is strictly worse than
doing nothing.** Measured 2026-09-15, `resolve_range` in `utils/gmeet_to_md.py`:

| invocation | days harvested |
|---|---|
| bare `gmeet_to_md <email>` — what `pull_sources` runs | `[last_harvested .. today]`, **today INCLUDED** |
| `gmeet_to_md <email> --since <date>` | `[date .. yesterday]`, **today DROPPED** |

⚠️ **AND THE REGISTRY HAS NO LOCK.** `load_registry`/`save_registry` take no file lock.
`pull_sources` serializes same-tool lanes so its OWN lanes cannot collide, but that guard does not
cover a copy you start from outside it. Two writers race on `src/gmeet/.registry.json`.

⚠️ **`grep gmeet .claude/skills/brain-pull-sources/bin/pull_sources` RETURNS NOTHING, AND THAT IS
NOT EVIDENCE.** The script is generic. The source list lives in `sources.md`. **Read `sources.md`,
never the script.** This is exactly how the duplicate got written into this skill.

**Gap-fill only, and only when a day is provably missing.** After 1a, check coverage. If a day has
no folder, harvest that day alone, and only while nothing else is running:

```bash
grep -n gmeet_to_md sources.md                      # confirm 1a owns the harvest
bin/gmeet_to_md <gws-email> --day YYYY-MM-DD        # ONE missing day
```

**2b — Generate digests (LLM synthesis). THIS is Part 2's real work.** For each harvested day
generate the daily digest, then roll up weekly / monthly / YTD per the
[digest appendix](#meeting-digest-generation). These are the rollups `gmeet_to_md` deliberately does
not produce. ⚠️ Weekly rollups target the **ISO week each harvested day actually belongs to** — a
Monday opens a new `WNN` folder, so don't assume the span stays in one week.

## Tool updates are NOT part of this routine

`brain-upgrade` — brew / npm / uv, the vendored-skill resync, gstack, the rebase pull — is **invoked
separately, on demand.** Nothing about a tool upgrade has to happen before the day's first meeting,
and the gstack gate alone was 13% of this routine's cost when it lived here.

⚠️ **One consequence to know:** this routine no longer resyncs the vendored copies of super's skills,
and **a drifted skill copy exports stale content with a clean exit status** — Outline did exactly that
for a full day on 2026-08-14. Every phase below reads what the exporters wrote, so when source data
looks wrong, run `brain-upgrade` and check for drift before believing the export.

## Meeting prep is NOT part of this routine

`brain-prepare-my-deep-dives` and `brain-prepare-my-one-on-one` are **invoked separately, on demand**
— they are not dispatched here and this routine does not read the day's calendar to find them. Do not
re-add them: an agenda is only useful immediately before its meeting, and building every one at 07:00
measures Linear hours early, which is how a row goes stale before the room reads it.

Consequently this routine writes **no** files under `outputs/agents/my-deep-dives/` or
`outputs/agents/my-one-on-one/`, and a run reporting none is correct, not truncated.

## Part 3 — commit, THEN gbrain reindex (runs LAST)

Every file is now written — src exports, gmeet, service docs, memory.

**Commit first — this ordering is mandatory.** `gbrain sync` is **commit-based**: it git-diffs the
repo against its last bookmark and imports only *committed* changes. Everything Parts 1–2 wrote is
still in the working tree, so syncing before committing indexes **nothing new**.

Delegate to a subagent (returns the sync delta):

```bash
cd <brain-root> && set -a && source .env.local && set +a      # OPENAI_API_KEY + OPENAI_BASE_URL
# 1) COMMIT FIRST (prefer brain-git-sync, or inline:)
git add -A && git commit -m "chore(brain): morning-start sync $(date +%F)" && git push
# 2) Then reindex the just-committed changes — import + embed + extract in one pass
gbrain sync --repo "$(pwd)" --skip-failed --no-pull --yes
# 3) Scope the link graph to curated pages. Idempotent; safe every sync.
psql "$(gbrain config show 2>/dev/null | sed -n 's/^ *database_url: *//p')" -c \
  "DELETE FROM links WHERE from_page_id NOT IN (SELECT id FROM pages WHERE slug LIKE 'memory/%' OR slug LIKE 'outputs/%');"
```

- **The `DELETE` is mandatory.** `link_resolution.global_basename` must stay `true` so bare
  `[[hub]]`/`[[teams]]` wikilinks resolve in the L1/L2 MOCs — and that same flag basename-resolves
  the raw `src/` exports' local navigation links into a multi-million-edge hairball. Dropping edges
  that *originate* outside `memory/`+`outputs/` keeps the curated graph clean.
- `--skip-failed` is required: ~18 oversized (>5 MB) / null-byte `src/` exports cannot parse and
  would otherwise block the sync. A couple of chunks stay unembedded (403-filtered); sync exits 0.
- A daily run is **incremental** — only git-changed files are re-imported. A full re-embed happens
  only on `--full`.
- Don't pipe `sync`/`embed` through `| tail` — it hides progress and can spin retrying 403 chunks.

**Large-sync deferral — read the sync output.** On a big diff `gbrain sync` **defers embed and
extract** and says so. Then run both explicitly, extract first (it creates the edges the `DELETE`
then scopes):

```bash
gbrain extract links --source fs --repo "$(pwd)"
gbrain embed --stale
# then the link-scoping DELETE from above
```

⚠️ **Use `--source fs`. The two other forms fail silently:**

- `extract --stale` stamps `links_extracted_at` while creating **zero** `wikilink_basename` edges
  (it passes a null resolver and no globalBasename opt, so bare `[[name]]` refs are dropped twice
  over). Pages look done. **Never use it.**
- `extract links --source db --since <date>` creates real edges but only for pages whose row it can
  date. It is a date filter on a mutable column, and a large sync is exactly when those timestamps
  are least trustworthy — it **silently under-covered a large diff on 2026-08-18**.
- `--source fs` re-reads the working tree, so coverage does not depend on a DB timestamp being right.

**Verify, don't assume.** Before writing the final report:

```bash
psql "$(gbrain config show 2>/dev/null | sed -n 's/^ *database_url: *//p')" -tAc \
  "SELECT count(*), count(embedding), count(*)-count(embedding) FROM content_chunks;"
```

Missing should be ~0 (a couple dozen permanently-unembeddable oversized/403 chunks are normal). Also
check that a freshly-rewritten page has outgoing links: `gbrain backlinks memory/l1/hub` non-empty.

## Part 4 — Final report

```
Morning start complete:

Phases:   <all | skipped: services, …>   (from morning_start.skip_phases)
Sources:  <N> exported (X ok, Y failed)
Clones:   <N> repos with local work — <merged | skipped | CONFLICT> (else "all clean mirrors")
Changed:  <N> repos moved HEAD (from .github-changed-repos.tsv)
Services: <N> docs refreshed, <M> repos skipped (HEAD unchanged)
Memory:   L2 <N> files, L1 <N> MOCs · gbrain graph: <N> edges, <N> timeline
Context:  AGENTS.md <N> B (<±N> B) · layout block <N> B · budget 61,440 B <ok | OVER>
Meetings: <last_harvested> → today (<D> days), <N> processed → src/gmeet/  (harvested by 1a)
gbrain reindex: <N> chunks embedded
```

**The `Context:` line is not decoration.** `AGENTS.md` grew to 210,519 B — roughly 58,500 tokens
charged to every session on every surface — over weeks in which no run ever printed its size. **A
number nobody prints is a number nobody notices moving.** Print it every run, breach or not, and
print the delta so a slow climb is visible before it becomes a rewrite. Re-measure both figures from
disk; never carry either forward.

**`Clones:` and `Changed:` come from two files `github_clone` writes during Part 1a** (repo root),
both truncated at the start of each run: `.github-clone-report.md` (anything that wasn't a clean
mirror update) and `.github-changed-repos.tsv` (one line per repo whose HEAD moved). **Read the
files, not the subagent's stdout** — `pull_sources` sends the jungle loop's output to `/dev/null`, so
they are the only reliable record.

- Absent or empty → `all clean mirrors`.
- Otherwise list each repo and what happened, and **call out any `merge conflict` line explicitly** —
  that clone is stuck on a branch that could not take the remote's changes and stays stale until
  someone merges by hand.

A clone carrying local work is by definition **not** a faithful mirror, so anything reading it
(service docs, `technologies.md`, freshness checks) may be describing your branch rather than `main`.
Worth one line a day.

## Dependency chain

```
Part 1a pull-sources ─────→ 1b services ──→ 1b.5 additional ──→ 1c memory (markdown only)
  └─ 2a gmeet harvest       └─ 2b digests (LLM)                          ↓
     (a LANE inside 1a,        (reads what 2a wrote)
      never a second run)
                                       Part 3 commit (brain-git-sync) → gbrain reindex
                                                                         ↓
                                                                  Part 4 report
```

The reindex is intentionally **last**: it depends on every prior write. Because `gbrain sync` only
indexes *committed* files, the commit must run immediately **before** it — commit-then-reindex, never
the reverse. On Postgres the sync runs concurrently with the always-on server, so it never blocks.

## Skill References

| Skill | Output |
|-------|--------|
| `brain-pull-sources` | `src/<source>/` |
| 1b docs-drift sweep (inline, no skill) | a report only — **writes nothing** |
| `brain-rebuild-memory` | `memory/L1/`, `memory/L2/`, `AGENTS.md`, `DEVELOPER.md` |
| `gmeet_to_md` (in `brain-pull-sources`) + [digest appendix](#meeting-digest-generation) | `src/gmeet/` |

## When to Use

Run at the start of each working day to bootstrap the brain. Meeting agendas are prepared separately,
on demand, immediately before the meetings that need them.

---

## Meeting digest generation

Used by **Part 2b**. The raw per-meeting artifacts and the per-day `index.md` are produced
deterministically by `gmeet_to_md` (Part 2a); these steps are the **LLM synthesis** on top: a daily
digest per harvested day, then weekly → monthly → YTD rollups at each boundary as it completes.

### Daily digest — two passes

**Pass 1 — per-meeting summary.** For each meeting with notes or a transcript, produce **key
decisions**, **action items** with an @owner, and **3–5 key points**. A meeting with only metadata is
still listed, as "No Gemini notes or transcript available."

> ⚠️ **VERIFY THE NOTE BELONGS TO THE MEETING BEFORE SUMMARISING IT.** This is where a misfiled
> artifact becomes a wrong *fact*: it flows into the daily digest, the rollups, and the `L2/` memory
> those feed, carrying a `verified:`/`source:` trail that looks perfectly healthy. A 2026-08-06 audit
> found **128 of 758 `notes.md` (16.9%)** holding another meeting's notes, including 3 one-to-one leaks.
>
> The folder name, date and `# H1` come from Calendar and are **always** right, so they prove nothing.
> **Read the line just under the `📝` marker** — the title Gemini wrote *inside* the doc. If it names a
> different meeting (folder `ged-deep-dive`, body `SAIAN DeepDive`), **discard the artifact and treat
> the meeting as having no notes.** Do not salvage it; do not attribute its decisions to either meeting.
>
> **Not misfiles:** a body title that is a longer or reworded form of the event name, and an
> organiser's alternate name for a recurring series (`FE Alignment` bodies titled `GED Design
> Sharing/Alignment`). Only a *mutual* contradiction — each side naming something the other never
> mentions — disqualifies.
>
> `metadata.json` → `dataQuality.notesTitleSuspect` means the extractor kept a disagreeing note
> deliberately: usable, but state the uncertainty.
>
> `gmeet_to_md` discards the provable cases itself, so this should be rare — but it only sees one
> day's calendar and this bug has been fixed three times, so check rather than assume. Prefer live
> systems of record (Linear, Personio, Slack) over meeting notes for anything load-bearing, and never
> repeat a note's content to the people who were in the room without this check.

**Pass 2 — daily rollup.** Save as `src/gmeet/YYYY/WNN/MM-DD/MM-DD-digest.md`.

```markdown
# Meeting Digest: YYYY-MM-DD

## Summary
- N meetings, Xh Ym total meeting time
- N had Gemini notes, M had recordings, K had transcripts

## Meetings

### 1. Meeting Title (HH:MM–HH:MM)
**Attendees:** names
**Key decisions:**
- Decision 1

**Action items:**
- [ ] @person: action description

**Key points:**
- Point 1

[Full notes](meeting-slug/notes.md)

## Cross-Meeting Action Items
- [ ] @simone: action from meeting 1

## Brain Updates
- L2/teams.md: UPDATE <team changes discussed today>
```

**Brain Updates rules.** Only when a meeting produced a clear, actionable decision that changes the
state of the world. Format `- L2/<file>.md: <ACTION> <description>`, where `<ACTION>` is `ADD` (new
fact), `UPDATE` (refresh existing) or `REMOVE` (mark superseded). Map each decision to the right L2
file by topic. **If no meeting produced an L2-worthy decision, omit the section entirely.**

**Linear project links.** When notes or transcripts name a Linear project, resolve its URL via
`get_project` / `list_projects` and link it — `[Project Name](url)` — in summaries, Brain Updates and
action items.

### Weekly digest

After every day in the week is processed, roll the daily digests up. Save as
`src/gmeet/YYYY/WNN/WNN-weekly-digest.md`. **Aggregate and deduplicate Brain Updates** — if several
days touch one L2 file, combine into a single update carrying the latest state.

```markdown
# Weekly Meeting Digest: YYYY WNN

## Week Summary
- N meetings across M days · Xh Ym total · N had notes, M had recordings

## Major Decisions This Week
- [Mon] Decision from meeting X

## Key Action Items
- [ ] @person: action (from Meeting Name, Day)

## Daily Breakdown

### Monday MM-DD
- Meeting 1: key point
[Full digest](MM-DD/MM-DD-digest.md)

## Brain Updates
- L2/file.md: ACTION description (aggregated from daily digests)
```

### Monthly digest

After every week in the month is processed, roll the weekly digests up. Save as
`src/gmeet/YYYY/MM-monthly-digest.md`. This is the executive summary — readable in 2 minutes,
carrying what someone who missed the whole month needs to know.

```markdown
# Monthly Meeting Digest: YYYY-MM (Month Name)

## Month at a Glance
- N meetings across M days · Xh total · N had notes, M had recordings

## Strategic Decisions
The 5–10 decisions that changed direction, launched initiatives or committed resources.
Group by theme, not by date.

### Theme 1: [e.g., US Launch Preparation]
- Decision A (Week WNN)

## Key Action Items (Still Open)
Strategic or cross-team only; skip the tactical.
- [ ] @person: action (from WNN)

## Week-by-Week Summary

### WNN (MM-DD to MM-DD)
2–3 sentences on the week's focus.
[Full weekly digest](WNN/WNN-weekly-digest.md)

## Themes & Patterns
Which topics dominated, and what shifted from last month. 2–3 paragraphs.

## Brain Updates
- L2/file.md: ACTION description (aggregated from weekly digests, deduplicated)
```

### Year-to-date digest

A living document, updated after the monthly digests. Read all monthly digests **and the previous YTD
digest**. Save as `src/gmeet/YYYY/YYYY-ytd-digest.md`. **Cumulative:** each run preserves and updates
the prior trackers — marking items resolved when later meetings show completion, and superseded when
direction changed.

```markdown
# Year-to-Date Meeting Digest: YYYY

## YTD Stats
- N meetings across M months · N had notes, M had recordings

## Decision Tracker

### Active Decisions (still in effect)
| Decision | Made | Week | Status |
|----------|------|------|--------|
| Google Login as primary auth | Jan | W02 | Active |

### Resolved / Completed
| Decision | Made | Resolved | Outcome |
|----------|------|----------|---------|
| Zero deposit launch for DE/.COM | Jan W03 | Jan W03 | Launched Jan 19 |

### Superseded / Changed
| Original Decision | Made | Changed | New Direction |
|-------------------|------|---------|---------------|

## Action Item Tracker

### Open (still pending)
- [ ] @person: action (from Month/Week) — status if known

### Completed
- [x] @person: action (from Month/Week) — completed Month/Week

### Dropped / Deprioritized
- [~] @person: action (from Month/Week) — reason

## Monthly Arc
One paragraph per month: focus, what shifted, what carried forward.

## Emerging Themes
Threads spanning multiple months. What's accelerating? What stalled?
```

---

## ⚠️ OUTPUT BYTE BUDGETS — the run's own artifacts are the token cost

**Measured 2026-09-14. Three workers spent 684,444 tokens before the memory rebuild started, and
the memory rebuild then hit the account spend limit.** The work was small. The FILES were large.

**A worker must READ the file it rewrites, then WRITE it back. So a file's size is paid TWICE,
every run it changes.**

| Artifact | Measured 2026-09-14 | Budget |
|---|---|---|
| a daily meeting digest | **59,920 B** for 10 meetings | **≤ 12,000 B** |
| a weekly meeting digest | **145,394 B** | **≤ 30,000 B** |
| a monthly digest | — | **≤ 30,000 B** |
| `AGENTS.md` | **89,718 B** (~22,400 tok × EVERY worker) | ≤ 61,440 B |

### Rules

1. **A daily digest is a SUMMARY, not a transcript.** 59,920 B across 10 meetings is 6 KB per
   meeting. That is an expansion of the source, not a digest of it. **Target ≤ 1,200 B per
   meeting.**
2. **NEVER restate a transcript, a notes body or a quote longer than one sentence.** Link to the
   artifact. The raw file is already on disk and already indexed.
3. **A weekly digest aggregates the dailies. It does NOT re-narrate them.** If the weekly is
   larger than the sum of its dailies' Summary sections, it is wrong.
4. ⚠️ **THE BUDGET NEVER OUTRANKS THE CARRY-THROUGH RULE.** Do not drop a caveat, a scope
   qualifier, a date or a number to hit a byte count. **Cut NARRATION, never EVIDENCE.** If a
   digest cannot fit its budget on evidence alone, write it and REPORT THE OVERAGE with the
   reason. An honest overage is correct. A silent one is not.
5. **Print the byte size of every artifact you write, in your return message.** A number nobody
   prints is a number nobody notices moving.

### Worker fan-out is the other multiplier

**Every worker pays the always-loaded floor before it does anything**: `AGENTS.md` +
`memory/L3/MEMORY.md` measured **111,309 B ≈ 27,800 tokens** on 2026-09-14. Twelve workers is
~334,000 tokens of identical re-reading.

- **Dispatch the fewest workers that can do the job.** Two small targets belong in ONE worker,
  not two.
- **Gate every phase on a deterministic signal first.** A phase that reports "nothing to do" for
  zero model cost is the goal.
- ⚠️ **Do NOT dispatch a worker for a target whose inputs did not change.**
