---
name: brain-morning-start
description: >
  Daily bootstrap: update tools, sync brain sources, rebuild memory and service docs,
  harvest meeting notes since the last harvest, and prepare today's agendas for deep dives and 1:1s.
  Use when the user says "morning start", "start my day", "daily bootstrap", "morning routine", or
  "prepare my day".
---

# Morning Start

Daily bootstrap: update tools, sync brain sources, rebuild memory + service docs, harvest every meeting since the last harvested day, prepare today's deep-dive and 1:1 agendas, then refresh the gbrain index in one pass.

## How to run this (keep the orchestrator lean)

**Delegate each heavy phase to a subagent and keep only its summary.** Parts 2, 3, 4d/4e, and 5 each do bulky work (exporting thousands of files, rewriting ~46 memory files, querying Linear). Spawn an `Agent` per phase that invokes the named skill and returns a **concise summary only** (counts + errors, not file dumps). This is what keeps the morning run cheap in tokens — the verbose output stays in the subagent. The meeting-prep parts already use this pattern; apply it to the rest.

Each sub-skill carries its own detailed instructions — do **not** restate them here; just dispatch and collect.

**Cost discipline: gate every phase on a deterministic signal before spending a model on it.**
Measured over 2026-07-06→08-05 the routine averaged **464 model requests per morning** and
peaked at 1,034, and the split says exactly where it goes:

| Phase | 30d requests | Share |
|---|---:|---:|
| `brain-rebuild-services` | 6,881 | 55% |
| this orchestrator | 2,335 | 19% |
| `gstack-upgrade` | 1,589 | 13% |
| `brain-rebuild-memory` | 1,327 | 11% |
| `brain-git-sync` | 309 | 2% |
| **`brain-pull-sources`** | **7** | **~0%** |

`brain-pull-sources` moves thousands of files across 113 sources for ~zero requests, because
it is a deterministic script. Everything expensive is an LLM re-deriving what a `git rev-parse`,
a `wc -l` or a cached version check answers for free. Before any heavy phase, run the cheap
check and skip on a negative: `.github-changed-repos.tsv` for services (Part 2b),
`gstack-update-check` for tools (Part 1). A phase that reports "nothing to do" for zero cost is
the goal, not a sign the routine misfired.

**Never trust a subagent's "done" — verify by filesystem state.** The sub-skills (`brain-pull-sources`, `brain-rebuild-services`, `brain-rebuild-memory`) spawn their own worker processes, and wrapper subagents routinely return *before* those workers finish (observed 3× on 2026-07-14: pull_sources still exporting, service regen mid-batch, memory "Wave 1 dispatched" with 0 files written). Rules:

1. Tell every phase subagent explicitly: *do the work inline/sequentially in your own context; do NOT dispatch detached background workers and return — orphaned workers write nothing.* If it must spawn helpers, it must block on them and verify their file writes before returning.
2. On any ambiguous/early return, check ground truth before re-dispatching: output-file **mtimes** (`find <outdir> -newermt 'today 00:00' | wc -l`) and live worker processes. Match workers by **command + start time**, never by generic name — long-`etime` `claude` processes are unrelated pre-existing sessions.
3. ⚠️⚠️ **ONE BLOCKING WAIT PER PHASE. NEVER POLL.** This is the single largest
   self-inflicted cost in the routine, and it is the orchestrator's own doing.
   Measured 2026-08-18: **219 orchestrator requests, of which ~40 were substantive** —
   the rest were wait-loops and wake-ups, each one re-sending the **full ~198K-token
   orchestrator context**. Cutting ~100 avoidable requests is worth **~20M tokens, ~15%
   of the morning.**

   A wait must happen **inside one shell call**, where blocking is free, not by
   re-invoking the model to look again. One `Bash` call costs one request whether it
   returns in 1 second or 20 minutes:

   ```bash
   # ONE request. Blocks until the phase is genuinely done, then exits.
   until <completion-predicate>; do sleep 20; done; echo PHASE-DONE
   ```

   Use `run_in_background: true` only when you have other *substantive* work to do
   meanwhile — never as a way to check back repeatedly. **Do not** write a `sleep N`
   then re-check as a separate call; that is the anti-pattern this rule exists to kill.
   If a phase can hang, put a deadline in the same call
   (`timeout 3000 bash -c 'until …; do sleep 20; done'`) so one request still bounds it.

4. ⚠️ **Use the phase's OWN completion predicate — a narrower one silently truncates the
   phase.** "Expected outputs exist" is not specific enough to be safe. On 2026-08-18 the
   memory phase was waited on with `memory/**/*.md`, which **does not match `AGENTS.md`
   at the repo root** — the phase was declared complete before the generator had rewritten
   it, and `AGENTS.md` **missed the commit entirely** and had to be regenerated and
   committed in a follow-up run. Watch the **whole tree** a phase writes, not the
   directory you happen to be thinking about:

   | Phase | Completion predicate (the whole set it writes) |
   |---|---|
   | 2a `brain-pull-sources` | `src/` **and** `github/` quiet — `[ -z "$(find src github -newermt '-90 seconds' -type f 2>/dev/null | head -1)" ]` |
   | 2b `brain-rebuild-services` | `outputs/services/` quiet AND every repo in `.github-changed-repos.tsv` either has a doc with today's mtime or is gated SKIP |
   | 3 meeting harvest | `src/gmeet/` quiet AND a per-day `index.md` exists for every day since the last harvest |
   | 4 `brain-rebuild-memory` | **`memory/` AND `AGENTS.md` AND `DEVELOPER.md`** quiet — the generator writes all three. `[ -z "$(find memory AGENTS.md DEVELOPER.md -newermt '-90 seconds' 2>/dev/null | head -1)" ]` |
   | 4d/4e agendas | one file per dispatched meeting under `outputs/agents/my-{deep-dives,one-on-one}/` |

   **Before Part 5's commit, run `git status --porcelain` and read it.** It is the only
   check that cannot miss a file by construction, and it costs one request. An unexpected
   *absence* there — a phase that wrote nothing — is as informative as a presence.

5. Never launch a duplicate export/rebuild while the previous one is still running.

## Part 0 — First-run bootstrap

Check whether `agents/morning-start-additional/SKILL.md` exists (relative to the brain repo root). If it does, continue. If not, copy `resources/morning-start-additional.template.md` (relative to this skill's directory) to that path first — a one-time seed for extra per-morning agent runs.

## Part 1 — Update tools (parallel) & pull

Run the independent updaters **concurrently in the background**, then collect:

- `brew update && brew upgrade` (background)
- `npm update -g` (background)
- `uv sync --upgrade` (background)
- **gstack — check first, invoke the skill only if there's something to install.** Run the
  purpose-built version check; **empty output means up to date, and then this phase is
  done at zero model cost:**

  ```bash
  ~/.claude/skills/gstack/bin/gstack-update-check   # prints UPGRADE_AVAILABLE <old> <new>, or nothing
  ```

  Only on `UPGRADE_AVAILABLE` (or `JUST_UPGRADED`, which wants the migration steps) invoke
  `/gstack-upgrade`. Do **not** invoke it unconditionally: measured over 2026-07-06→08-05 it
  cost **1,589 model requests (13% of the whole morning routine)** — ~72 per run with spikes
  of 217 and 420 — because the skill re-runs install-type detection and an interactive
  `AskUserQuestion` every single morning, almost always to conclude nothing needed doing.
  Consider `gstack-config set auto_upgrade true` so the real upgrades don't stop to ask.

- **Vendored-skill drift — run the script, do not do this with a model.** super's canonical
  `skills/` is copied into several vendored trees, and they drift. On 2026-08-18 fixing one
  version bump plus one drifted copy cost **4.3M tokens**, and the same drift had appeared
  **four mornings running**. It is a diff and a copy:

  ```bash
  github/smnbss/super/bin/resync-vendored-skills --check   # exit 1 = drift; prints which copies
  github/smnbss/super/bin/resync-vendored-skills           # fix, then re-verify
  ```

  It syncs **per skill directory and never deletes**, because two of the copies are combined
  trees holding other people's skills (the Drive `.agents/skills` had 196 against super's 19) —
  a tree-level `rsync --delete` or a symlink would destroy them. It also **skips any tree that
  does not already contain super's skills** (`~/.claude/skills`, `~/.agents/skills` and
  `~/.codex/skills` all exist and hold *other* skills; syncing into them would be a new global
  install, not a resync), and it **refuses to overwrite a copy whose file is newer** than
  canonical rather than silently clobbering a local edit.

  ⚠️ Drift is not cosmetic — it silently corrupts data. On 2026-08-14 Outline exported **stale
  content for a full day with a clean exit status** because the installed copy had drifted.
  Treat a non-zero `--check` as a real finding, not housekeeping.
- `git pull --rebase --autostash` — `--autostash` is required: leftover working-tree WIP from prior sessions otherwise aborts the pull ("cannot pull with rebase: You have unstaged changes")

Note: `brew upgrade` may fail on casks that need interactive sudo (e.g. `windows-app`) — non-fatal in a scheduled run; report and move on.

There is **no gbrain step here.** The reindex happens once at the very end (Part 5), after all new content has been written — running it now would index nothing new.

Report what was updated; flag errors or notable version bumps.

## Part 2 — Brain sync & rebuild (sequential chain, subagent per phase)

Dispatch each as a subagent invoking the named skill; collect a short summary.

- **2a `brain-pull-sources`** — export all external sources → `src/`. Heavy. **Run Part 3 in parallel with this.**
- **2b `brain-rebuild-services`** — regenerate `.agent.md` service docs → `outputs/services/`. *After 2a.*
  **Read the work-list before dispatching anything:**

  ```bash
  wc -l < .github-changed-repos.tsv   # written by 2a; one line per repo whose HEAD moved
  cut -f1 .github-changed-repos.tsv
  ```

  **Zero lines → skip the phase entirely.** Report `Services: 0 docs (no repos moved)` and go
  straight to 2b.5. Do not dispatch a subagent "just to check" — that check is what the ledger
  already is. Otherwise dispatch with the explicit repo list; the skill's own Step 0 gate
  re-confirms each one's recorded `head:` before reading source.

  ⚠️ **Pass the CHANGED FILE LIST, not just the repo name — this is the same lever as the
  repo-level gate, one level down.** The repo gate above took the phase from 55% of the
  morning to near-free on a quiet day; on a busy day the remaining cost is workers reading
  whole working trees for repos that legitimately moved (2026-08-18: 18 repos, ~24M tokens).
  A repo name invites a full read; a file list does not. Compute it here — it is one
  `git -C` per repo, zero model requests — and put it in each dispatch prompt:

  ```bash
  while IFS=$'\t' read -r repo path; do
    rec=$(grep -oE 'head: [0-9a-f]+' "outputs/services/**/$repo.agent.md" 2>/dev/null | head -1 | cut -d' ' -f2)
    [ -n "$rec" ] && printf '=== %s\n%s\n' "$repo" \
      "$(git -C "$path" diff --name-only "$rec..HEAD" 2>/dev/null)"
  done < .github-changed-repos.tsv
  ```

  A repo whose list comes back **empty** is inert — do not dispatch it at all. The worker
  is instructed to stop rather than fall back to a full read if the list is missing, so
  omitting it does not fail safe: it fails expensive.

  This phase was **55% of the entire morning routine** (6,881 model requests over 30 days,
  peaking at 684 in one day) because nothing ever told it which repos to look at, so it
  re-derived that itself every morning across 136 clones.
- **2b.5 additional agents** — if `agents/morning-start-additional/SKILL.md` exists, run its `run <path>` directives in order. *After 2b, before 2c.*
- **2c `brain-rebuild-memory`** — rebuild L2 + L1 → `memory/`. It only **writes markdown**; the gbrain index (chunks, embeddings, wikilink edges, timeline) is refreshed by the single `gbrain sync` in Part 5. **No gbrain step inside 2c.** *After 2b.5.*

## Part 3 — Harvest meetings since last harvest (parallel with Part 2a)

Two stages, dispatched to one subagent (collect a short summary): a **deterministic harvest** (the `gmeet_to_md` extractor) followed by **LLM digest generation** (the [Meeting digest generation](#meeting-digest-generation) appendix below). Backfills every day since the last harvested day through yesterday (weekends/holidays/travel). Reads GWS/Calendar — independent of brain memory.

**Detect `LAST_HARVESTED`** — the most recent `MM-DD` folder with a daily digest:

```bash
ls -1d src/gmeet/*/W*/??-?? 2>/dev/null \
  | while read d; do [ -f "$d/$(basename "$d")-digest.md" ] && echo "$d"; done \
  | sort | tail -1
```

Reconstruct `YYYY-MM-DD` from the `YYYY/WNN/MM-DD` path. If none found, use yesterday and note it's a first run.

**3a — Harvest raw artifacts (deterministic, no LLM).** Run the `gmeet_to_md` extractor (it lives in the `brain-pull-sources` skill's `bin/`) for the authenticated gws user. It walks Calendar, discovers Drive artifacts (Gemini notes, agendas, recordings, attachments, transcripts), and writes per-meeting folders + a static per-day `index.md` under `src/gmeet/YYYY/WNN/MM-DD/`. It is idempotent and re-runs the last day safely — the full-span re-harvest self-heals gaps and **preserves existing `*-digest.md` and `transcript.md`** files:

```bash
bin/gmeet_to_md <gws-email> --since "$LAST_HARVESTED"   # from skills/brain-pull-sources/
```

**3b — Generate digests (LLM synthesis).** For each harvested day, generate the daily digest, then roll up the weekly / monthly / YTD digests, following the [Meeting digest generation](#meeting-digest-generation) appendix. Weekly rollups target the **ISO week each harvested day actually belongs to** (a Monday opens a new `WNN` folder — don't assume the span stays in `LAST_HARVESTED`'s week). These are the LLM rollups `gmeet_to_md` deliberately does not produce.

## Part 4 — Prepare today's meetings

**4a.** Fetch today's calendar (Europe/Rome day bounds → UTC):

```bash
gws calendar events list --params '{"calendarId":"primary","timeMin":"<TODAY_START_UTC>","timeMax":"<TODAY_END_UTC>","singleEvents":true,"orderBy":"startTime"}'
```

`gws` prints a `Using keyring backend: …` line before the JSON — strip it (`grep -v '^Using keyring'`) before piping to a JSON parser.

**4b. Classify** (skip `status:"cancelled"`):

| Type | Match rule |
|------|-----------|
| Deep Dive | `summary` contains "Deep Dive" (case-insensitive) |
| 1:1 | `summary` contains "1:1" (case-insensitive), excluding "Prepare for 1:1s" |

**4c.** Print the day's schedule. If none match, report "No deep dives or 1:1s today" and skip to Part 5.

**4d/4e.** Spawn one `Agent` per meeting, **all in parallel**, each invoking `brain-prepare-my-deep-dives` (→ `outputs/agents/my-deep-dives/<team>.md`) or `brain-prepare-my-one-on-one` (→ `outputs/agents/my-one-on-one/<person>.md`) with `LOOKAHEAD_DAYS: 1`. The skills carry their own logic; just pass the meeting and collect the output path.

## Part 5 — commit, THEN gbrain reindex (`gbrain sync`, LIVE, runs LAST)

Every file is now written — src exports, gmeet, service docs, memory, today's agendas.

**Commit first — this ordering is mandatory.** `gbrain sync` is **commit-based**: it git-diffs the repo against its last bookmark and imports only *committed* changes. Everything Parts 2–4 wrote is still in the working tree, so if you sync before committing it indexes **nothing new**. Run `brain-git-sync` (stage + commit + push) *before* the sync command, never after.

Then refresh the index with **one incremental `gbrain sync`**: it git-diffs the repo, imports only changed files, embeds them, and extracts links/timeline — all in a single command. It runs live alongside the always-on server and the `io.weroad.gbrain.jobs` worker. The repo is the system of record (`gbrain.yml` at the root); pages are repo-relative-slugged (`memory/l1/hub`).

Delegate to a subagent (returns the sync delta):

```bash
cd <brain-root> && set -a && source .env.local && set +a            # OPENAI_API_KEY + OPENAI_BASE_URL
# 1) COMMIT FIRST — gbrain sync only indexes committed files (prefer brain-git-sync, or inline:)
git add -A && git commit -m "chore(brain): morning-start sync $(date +%F)" && git push
# 2) Then reindex the just-committed changes
gbrain sync --repo "$(pwd)" --skip-failed --no-pull --yes           # incremental: import changed + embed + extract
# Scope the link graph to curated pages: raw src/ exports are basename-resolved
# into a huge hairball by global_basename, so drop links ORIGINATING from non-
# curated pages (keep memory/ + outputs/). Idempotent; safe to run every sync.
psql "$(gbrain config show 2>/dev/null | sed -n 's/^ *database_url: *//p')" -c \
  "DELETE FROM links WHERE from_page_id NOT IN (SELECT id FROM pages WHERE slug LIKE 'memory/%' OR slug LIKE 'outputs/%');"
```

Notes:
- `--skip-failed` keeps a handful of oversized/binary `src/` exports (≈18 files: >5 MB markdown, null-byte PDF conversions) from blocking the sync; they auto-skip after 3 runs.
- A daily run is **incremental** — only files changed since the last sync are re-imported/embedded/extracted, so it's fast (the full re-embed only happens on a `--full` rebuild).
- `link_resolution.global_basename` must stay `true` (bare `[[hub]]`/`[[teams]]` wikilinks in the L1/L2 MOCs resolve by basename). That's also what inflates the src link graph — hence the cleanup above.

One chunk fails embedding with `Forbidden` (a permanently 403-filtered page) — that's expected; `embed --stale` still exits 0. Don't pipe it through `| tail`. The server stays up throughout.

**Large-sync deferral — read the sync output.** When the day's diff is big (hundreds of files), `gbrain sync` **defers embed and extract** and says so ("Large sync: deferring link/timeline extraction… Run 'gbrain embed --stale'"). In that case you must run both explicitly, in this order (extract before the link-scoping `DELETE`, since extract is what creates the edges):

```bash
gbrain extract links --source fs --repo "$(pwd)"     # full sweep — see why below
gbrain embed --stale                      # foreground — see caveat below
# then the link-scoping DELETE from above
```

⚠️ **Two extract forms are wrong here and one is right. Use `--source fs`.**

| form | what it does | verdict |
|---|---|---|
| `extract --stale` | stamps `links_extracted_at` while creating **zero** `wikilink_basename` edges (`extractStaleFromDB` passes `nullResolver` and no `globalBasename` opt, so bare `[[name]]` refs are dropped twice over). Pages look done. | **never** |
| `extract links --source db --since <today>` | creates real edges, but only for pages whose row it can date. On 2026-08-18 it **silently under-covered a large diff** — exactly the case the deferral path exists for. | **no** |
| `extract links --source fs --repo "$(pwd)"` | re-reads the working tree, so coverage does not depend on a DB timestamp being right. | **yes** |

The `--since` form was recommended here until 2026-08-18 on the strength of one good
measurement (153 edges over 314 pages on 08-05). It is a **date filter on a mutable column**,
and a large sync is precisely when those timestamps are least trustworthy — the failure is
silent and looks identical to success. The `fs` sweep costs more wall clock and is the only
form whose coverage is self-evident. Always follow it with the link-scoping `DELETE`, which is
what keeps the extra `src/` edges out of the curated graph.

⚠️ `gbrain embed --stale --background` returned a job id but the jobs worker **did not drain it** (2026-07-14: queue showed empty, chunks stayed unembedded). Until that's fixed, run the embed in the **foreground**.

**Verify, don't assume.** After embed, confirm coverage before writing the final report:

```bash
psql "$(gbrain config show 2>/dev/null | sed -n 's/^ *database_url: *//p')" -tAc \
  "SELECT count(*), count(embedding), count(*)-count(embedding) FROM content_chunks;"
```

Missing should be ~0 (a couple dozen permanently-unembeddable oversized/403 chunks are normal). Also sanity-check that a freshly-rewritten page has outgoing links (`gbrain backlinks memory/l1/hub` non-empty).

## Part 6 — Final report

```
Morning start complete:

Tools:    brew <N> upgraded · npm/python <status> · gstack <up to date | vA→vB> · git <status>
Sources:  <N> exported (X ok, Y failed)
Clones:   <N> repos with local work — <merged | skipped | CONFLICT> (else "all clean mirrors")
Changed:  <N> repos moved HEAD (from .github-changed-repos.tsv)
Services: <N> docs refreshed, <M> repos skipped (HEAD unchanged)
Memory:   L2 <N> files, L1 <N> MOCs · gbrain graph: <N> edges, <N> timeline
Meetings: <LAST_HARVESTED> → yesterday (<D> days), <N> processed → src/gmeet/
Prep:
  ✓ Deep Dive SAITAMA → outputs/agents/my-deep-dives/saitama.md
  ✓ 1:1 Alex          → outputs/agents/my-one-on-one/alex.md
gbrain reindex: <N> chunks embedded
```

**The `Clones:` and `Changed:` lines come from two files written by `github_clone` during Part 2a** (repo root), both truncated at the start of each run: `.github-clone-report.md` (anything that wasn't a clean mirror update) and `.github-changed-repos.tsv` (one line per repo whose HEAD moved). Read them directly rather than relying on the subagent's stdout — `pull_sources` sends the jungle loop's output to `/dev/null`, so the files are the only reliable record.

- File absent or empty → `all clean mirrors`.
- Otherwise list each repo and what happened, and **call out any line containing `merge conflict` explicitly** — that clone is stuck on a branch that could not take the remote's changes, and it stays stale until someone merges by hand.

This exists because a hard reset used to discard local commits in these clones silently. It no longer does, but a clone carrying local work is by definition **not** a faithful mirror of the remote, so anything reading it (service docs, `technologies.md`, freshness checks) may be describing your branch rather than `main`. That is worth one line a day.

## Dependency chain

```
Part 1 tools (parallel) ─┐
                         ↓
Part 2a pull-sources ──┬──→ 2b services ──→ 2b.5 additional ──→ 2c memory (writes markdown only)
Part 3 harvest ────────┘  (3 runs parallel to 2a)                        ↓
                                                          Part 4 prep agents (parallel)
                                                                         ↓
                                       Part 5 commit (brain-git-sync) → gbrain reindex — single `gbrain sync`
                                                                         ↓
                                                                  Part 6 report
```

The reindex is intentionally **last**: it depends on every prior write (including the agendas). Because `gbrain sync` only indexes *committed* files, the commit (`brain-git-sync`) must run immediately **before** it — commit-then-reindex, never the reverse. On Postgres the sync runs concurrently with the always-on server, so it never blocks — and the Part 4 agents' `mcp__gbrain__query` calls keep working throughout.

## Skill References

| Skill | Output |
|-------|--------|
| `brain-pull-sources` | `src/<source>/` |
| `brain-rebuild-services` | `outputs/services/` |
| `brain-rebuild-memory` | `memory/L1/`, `memory/L2/` |
| `gmeet_to_md` (in `brain-pull-sources`) + [digest appendix](#meeting-digest-generation) | `src/gmeet/` |
| `brain-prepare-my-deep-dives` | `outputs/agents/my-deep-dives/` |
| `brain-prepare-my-one-on-one` | `outputs/agents/my-one-on-one/` |

## When to Use

Run at the start of each working day to fully bootstrap the brain and prepare all meeting agendas at once.

---

## Meeting digest generation

Used by **Part 3b**. The raw per-meeting artifacts and the static per-day `index.md` are produced deterministically by `gmeet_to_md` (Part 3a) — these steps are the **LLM synthesis** on top of them: a daily digest per harvested day, then weekly → monthly → YTD rollups. (Formerly Steps 6–9 of the retired `brain-pull-my-meeting-notes` skill.)

Process each harvested day, then roll up at week / month / year boundaries as they complete.

### Daily digest (LLM synthesis, per-meeting then rollup)

A two-pass synthesis. The agent reads the artifacts in each day's meeting folders and produces the digest.

**Pass 1 — per-meeting summary.** For each meeting that has notes or a transcript, read the artifact and produce a structured summary:
- **Key decisions** made in the meeting
- **Action items** with owner (@ mention)
- **Key points** (3–5 bullets of what was discussed)

If a meeting has no artifacts (just metadata), include it with: "No Gemini notes or transcript available."

> **VERIFY THE NOTE BELONGS TO THE MEETING before summarising it.** This is the step where a
> misfiled artifact becomes a wrong *fact* — it flows into the daily digest, the weekly/monthly/YTD
> rollups, and the `L2/` memory those feed, with a `verified:`/`source:` trail that looks perfectly
> healthy. A 2026-08-06 audit found **128 of 758 `notes.md` (16.9%)** holding another meeting's
> notes, including 3 one-to-one leaks.
>
> The folder name, date and `# H1` come from Calendar and are **always** right, so they prove
> nothing. Read the line just under the `📝` marker — that is the title Gemini wrote *inside* the
> doc. If it names a different meeting (e.g. folder `ged-deep-dive`, body `SAIAN DeepDive`),
> **discard the artifact and treat the meeting as having no notes.** Do not try to salvage it, and
> do not attribute its decisions to either meeting.
>
> Two things that are NOT misfiles: a body title that is merely a longer or reworded form of the
> event name, and an organiser's alternate name for the same recurring series (`FE Alignment`
> bodies titled `GED Design Sharing/Alignment`). Only a *mutual* contradiction — each side naming
> something the other never mentions — is disqualifying.
>
> A folder may also carry `metadata.json` → `dataQuality.notesTitleSuspect`, written by the
> extractor when it kept a disagreeing note deliberately. Treat that as "usable but state the
> uncertainty", not as grounds to drop it.
>
> `gmeet_to_md` now discards the provable cases itself, so this should be rare — but the extractor
> only sees one day's calendar, and this bug has been fixed three times, so check rather than
> assume. Prefer live systems of record (Linear, Personio, Slack) over meeting notes for anything
> load-bearing, and never repeat a note's content to the people who were in the room without this
> check.

**Pass 2 — daily rollup.** Aggregate all per-meeting summaries into the daily digest:

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
- Decision 2

**Action items:**
- [ ] @person: action description

**Key points:**
- Point 1
- Point 2

[Full notes](meeting-slug/notes.md)

### 2. Next Meeting (HH:MM–HH:MM)
...

## Cross-Meeting Action Items
- [ ] @simone: action from meeting 1
- [ ] @cass: action from meeting 3

## Brain Updates
- L2/teams.md: UPDATE <team changes discussed today>
```

**Brain Updates rules:**
- Only include updates when a meeting produced a clear, actionable decision that changes the state of the world.
- Format: `- L2/<file>.md: <ACTION> <description>` where `<ACTION>` is `ADD` (new fact), `UPDATE` (refresh existing), or `REMOVE` (mark superseded).
- Map decisions to the right L2 file by topic (releases, teams, data, product areas, etc.).
- If no meetings produced L2-worthy decisions, omit the Brain Updates section entirely.

**Linear project links:** if notes/transcripts mention specific Linear projects, resolve each project's URL via `get_project` / `list_projects` and format the name as a markdown link `[Project Name](url)` in summaries, Brain Updates, and action items.

Save as `src/gmeet/YYYY/WNN/MM-DD/MM-DD-digest.md`.

### Weekly digest

After all days in a week are processed, read all daily digests for the week and produce a rollup:

```markdown
# Weekly Meeting Digest: YYYY WNN

## Week Summary
- N meetings across M days
- Xh Ym total meeting time
- N had notes, M had recordings

## Major Decisions This Week
- [Mon] Decision from meeting X
- [Tue] Decision from meeting Y

## Key Action Items
- [ ] @person: action (from Meeting Name, Day)

## Daily Breakdown

### Monday MM-DD
- Meeting 1: key point
[Full digest](MM-DD/MM-DD-digest.md)

### Tuesday MM-DD
...

## Brain Updates
- L2/file.md: ACTION description (aggregated from daily digests)
```

Save as `src/gmeet/YYYY/WNN/WNN-weekly-digest.md`. Aggregate and deduplicate Brain Updates from the daily digests — if multiple days update the same L2 file, combine into one update with the latest state.

### Monthly digest

After all weeks in a month are processed, read all weekly digests and produce a year-level rollup:

```markdown
# Monthly Meeting Digest: YYYY-MM (Month Name)

## Month at a Glance
- N meetings across M days
- Xh total meeting time
- N had notes, M had recordings

## Strategic Decisions
Highlight the 5–10 most important decisions made this month — ones that change direction, launch initiatives, or commit resources. Group by theme, not by date.

### Theme 1: [e.g., US Launch Preparation]
- Decision A (Week WNN)
- Decision B (Week WNN)

### Theme 2: [e.g., AI/ML Initiatives]
- Decision C (Week WNN)

## Key Action Items (Still Open)
Only strategic or cross-team items; skip small/tactical ones.
- [ ] @person: action (from WNN)

## Week-by-Week Summary

### WNN (MM-DD to MM-DD)
2–3 sentence summary of the week's focus.
[Full weekly digest](WNN/WNN-weekly-digest.md)

## Themes & Patterns
What recurring topics dominated meetings this month? What shifted from last month? 2–3 paragraphs of high-level synthesis.

## Brain Updates
- L2/file.md: ACTION description (aggregated from weekly digests, deduplicated)
```

Save as `src/gmeet/YYYY/MM-monthly-digest.md`. This is the executive summary — readable in 2 minutes, capturing what someone who missed the whole month needs to know.

### Year-to-date digest

After monthly digests are complete, update the YTD digest — a living document tracking the full year's trajectory. Read all monthly digests and the previous YTD digest (if it exists):

```markdown
# Year-to-Date Meeting Digest: YYYY

## YTD Stats
- N meetings across M months
- N had notes, M had recordings

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
| (decisions that were reversed or modified) |

## Action Item Tracker

### Open (still pending)
- [ ] @person: action (from Month/Week) — status update if known

### Completed
- [x] @person: action (from Month/Week) — completed Month/Week

### Dropped / Deprioritized
- [~] @person: action (from Month/Week) — reason

## Monthly Arc
One paragraph per month describing the narrative arc: focus, what shifted, what carried forward.

## Emerging Themes
Threads that span multiple months. What's accelerating? What stalled?
```

Save as `src/gmeet/YYYY/YYYY-ytd-digest.md`. Cumulative: each run preserves and updates the decision/action trackers from prior runs — marking items resolved when later meetings show completion, and superseded when direction changed.
