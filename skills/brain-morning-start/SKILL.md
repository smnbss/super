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
   | 1b `brain-rebuild-services` | `outputs/services/` quiet AND every repo in `.github-changed-repos.tsv` has a doc with today's mtime or is gated SKIP |
   | 2 meeting harvest | `src/gmeet/` quiet AND a per-day `index.md` exists for every day since the last harvest |
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

## Part 0 — First-run bootstrap

If `agents/morning-start-additional/SKILL.md` (relative to the brain root) does not exist, seed it
once from `resources/morning-start-additional.template.md` (relative to this skill).

## Part 1 — Brain sync & rebuild (sequential chain, subagent per phase)

- **1a `brain-pull-sources`** — export all external sources → `src/`. Heavy. **Run Part 2 in parallel
  with this.**
- **1b `brain-rebuild-services`** — regenerate `.agent.md` docs → `outputs/services/`. *After 1a.*

  **Read the work-list before dispatching anything.** `.github-changed-repos.tsv` is written by 1a,
  one line per repo whose HEAD moved.

  ```bash
  wc -l < .github-changed-repos.tsv
  cut -f1 .github-changed-repos.tsv
  ```

  **Zero lines → skip the phase entirely.** Report `Services: 0 docs (no repos moved)` and go to
  1b.5. Do not dispatch a subagent "just to check" — that check *is* the ledger.

  ⚠️ **Pass the CHANGED FILE LIST, not just the repo name.** A repo name invites a full working-tree
  read; a file list does not. It is one `git -C` per repo and zero model requests:

  ```bash
  while IFS=$'\t' read -r repo path; do
    rec=$(grep -oE 'head: [0-9a-f]+' "outputs/services/**/$repo.agent.md" 2>/dev/null | head -1 | cut -d' ' -f2)
    [ -n "$rec" ] && printf '=== %s\n%s\n' "$repo" \
      "$(git -C "$path" diff --name-only "$rec..HEAD" 2>/dev/null)"
  done < .github-changed-repos.tsv
  ```

  A repo whose list comes back **empty is inert — do not dispatch it at all.** The worker is
  instructed to stop rather than fall back to a full read if the list is missing, so omitting the
  list does not fail safe: it fails expensive.
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

## Part 2 — Harvest meetings since last harvest (parallel with Part 1a)

**2a — Harvest raw artifacts (deterministic, no LLM).** Run the `gmeet_to_md` extractor from
`skills/brain-pull-sources/bin/`. It walks Calendar, discovers Drive artifacts (Gemini notes,
agendas, recordings, attachments, transcripts) and writes per-meeting folders plus a static per-day
`index.md` under `src/gmeet/YYYY/WNN/MM-DD/`. Idempotent — it re-runs the last day safely, the
full-span re-harvest self-heals gaps, and it **preserves existing `*-digest.md` and `transcript.md`**:

```bash
bin/gmeet_to_md <gws-email> --since "$LAST_HARVESTED"
```

**2b — Generate digests (LLM synthesis).** For each harvested day generate the daily digest, then
roll up weekly / monthly / YTD per the [digest appendix](#meeting-digest-generation). These are the
rollups `gmeet_to_md` deliberately does not produce. ⚠️ Weekly rollups target the **ISO week each
harvested day actually belongs to** — a Monday opens a new `WNN` folder, so don't assume the span
stays in `LAST_HARVESTED`'s week.

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

Sources:  <N> exported (X ok, Y failed)
Clones:   <N> repos with local work — <merged | skipped | CONFLICT> (else "all clean mirrors")
Changed:  <N> repos moved HEAD (from .github-changed-repos.tsv)
Services: <N> docs refreshed, <M> repos skipped (HEAD unchanged)
Memory:   L2 <N> files, L1 <N> MOCs · gbrain graph: <N> edges, <N> timeline
Context:  AGENTS.md <N> B (<±N> B) · layout block <N> B · budget 61,440 B <ok | OVER>
Meetings: <LAST_HARVESTED> → yesterday (<D> days), <N> processed → src/gmeet/
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
Part 1a pull-sources ──┬──→ 1b services ──→ 1b.5 additional ──→ 1c memory (markdown only)
Part 2  harvest ───────┘  (2 runs parallel to 1a)                        ↓
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
| `brain-rebuild-services` | `outputs/services/` |
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
