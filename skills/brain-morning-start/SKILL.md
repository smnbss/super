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

## Part 0 — First-run bootstrap

Check whether `agents/morning-start-additional/SKILL.md` exists (relative to the brain repo root). If it does, continue. If not, copy `resources/morning-start-additional.template.md` (relative to this skill's directory) to that path first — a one-time seed for extra per-morning agent runs.

## Part 1 — Update tools (parallel) & pull

Run the independent updaters **concurrently in the background**, then collect:

- `brew update && brew upgrade` (background)
- `npm update -g` (background)
- `uv sync --upgrade` (background)
- `/gstack-upgrade`
- `git pull --rebase`

There is **no gbrain step here.** The reindex happens once at the very end (Part 5), after all new content has been written — running it now would index nothing new.

Report what was updated; flag errors or notable version bumps.

## Part 2 — Brain sync & rebuild (sequential chain, subagent per phase)

Dispatch each as a subagent invoking the named skill; collect a short summary.

- **2a `brain-pull-sources`** — export all external sources → `src/`. Heavy. **Run Part 3 in parallel with this.**
- **2b `brain-rebuild-services`** — regenerate `.AGENT.MD` service docs from changed repos → `outputs/services/`. *After 2a.*
- **2b.5 additional agents** — if `agents/morning-start-additional/SKILL.md` exists, run its `run <path>` directives in order. *After 2b, before 2c.*
- **2c `brain-rebuild-memory`** — rebuild L2 + L1 → `memory/`. It only **writes markdown**; the gbrain index (chunks, embeddings, wikilink edges, timeline) is refreshed by the single `gbrain sync` in Part 5. **No gbrain step inside 2c.** *After 2b.5.*

## Part 3 — Harvest meetings since last harvest (parallel with Part 2a)

Subagent invoking `brain-pull-my-meeting-notes` for every day since the last harvested day through yesterday (backfills weekends/holidays/travel).

**Detect `LAST_HARVESTED`** — the most recent `MM-DD` folder with a daily digest:

```bash
ls -1d src/gmeet/*/W*/??-?? 2>/dev/null \
  | while read d; do [ -f "$d/$(basename "$d")-digest.md" ] && echo "$d"; done \
  | sort | tail -1
```

Reconstruct `YYYY-MM-DD` from the `YYYY/WNN/MM-DD` path, then invoke with `--since LAST_HARVESTED` (the skill is idempotent and re-runs the last day safely). If none found, run the default (yesterday) and note it's a first run. Reads GWS/Calendar — independent of brain memory.

## Part 4 — Prepare today's meetings

**4a.** Fetch today's calendar (Europe/Rome day bounds → UTC):

```bash
gws calendar events list --params '{"calendarId":"primary","timeMin":"<TODAY_START_UTC>","timeMax":"<TODAY_END_UTC>","singleEvents":true,"orderBy":"startTime"}'
```

**4b. Classify** (skip `status:"cancelled"`):

| Type | Match rule |
|------|-----------|
| Deep Dive | `summary` contains "Deep Dive" (case-insensitive) |
| 1:1 | `summary` contains "1:1" (case-insensitive), excluding "Prepare for 1:1s" |

**4c.** Print the day's schedule. If none match, report "No deep dives or 1:1s today" and skip to Part 5.

**4d/4e.** Spawn one `Agent` per meeting, **all in parallel**, each invoking `brain-prepare-my-deep-dives` (→ `outputs/agents/my-deep-dives/<team>.md`) or `brain-prepare-my-one-on-one` (→ `outputs/agents/my-one-on-one/<person>.md`) with `LOOKAHEAD_DAYS: 1`. The skills carry their own logic; just pass the meeting and collect the output path.

## Part 5 — gbrain reindex (`gbrain sync`, LIVE, runs LAST)

Every file is now written — src exports, gmeet, service docs, memory, today's agendas. Refresh the index with **one incremental `gbrain sync`**: it git-diffs the repo, imports only changed files, embeds them, and extracts links/timeline — all in a single command. It runs live alongside the always-on server and the `io.weroad.gbrain.jobs` worker. The repo is the system of record (`gbrain.yml` at the root); pages are repo-relative-slugged (`memory/l1/hub`).

Delegate to a subagent (returns the sync delta):

```bash
cd <brain-root> && set -a && source .env.local && set +a            # OPENAI_API_KEY + OPENAI_BASE_URL
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

**Fire-and-forget option:** to avoid blocking Part 6 on embedding, run `gbrain sync --repo "$(pwd)" --no-embed --skip-failed --no-pull --yes` then `gbrain embed --stale --background` (the `io.weroad.gbrain.jobs` worker drains the embed). Still run the link-scoping `DELETE` after.

## Part 6 — Final report

```
Morning start complete:

Tools:    brew <N> upgraded · npm/gstack/python <status> · git <status>
Sources:  <N> exported (X ok, Y failed)
Services: <N> docs refreshed
Memory:   L2 <N> files, L1 <N> MOCs · gbrain graph: <N> edges, <N> timeline
Meetings: <LAST_HARVESTED> → yesterday (<D> days), <N> processed → src/gmeet/
Prep:
  ✓ Deep Dive SAITAMA → outputs/agents/my-deep-dives/saitama.md
  ✓ 1:1 Alex          → outputs/agents/my-one-on-one/alex.md
gbrain reindex: <N> chunks embedded
```

## Dependency chain

```
Part 1 tools (parallel) ─┐
                         ↓
Part 2a pull-sources ──┬──→ 2b services ──→ 2b.5 additional ──→ 2c memory (writes markdown only)
Part 3 harvest ────────┘  (3 runs parallel to 2a)                        ↓
                                                          Part 4 prep agents (parallel)
                                                                         ↓
                                       Part 5 gbrain reindex — single `gbrain sync` (server stays up)
                                                                         ↓
                                                                  Part 6 report
```

The reindex is intentionally **last**: it depends on every prior write (including the agendas). On Postgres it runs concurrently with the always-on server, so it never blocks — and the Part 4 agents' `mcp__gbrain__query` calls keep working throughout.

## Skill References

| Skill | Output |
|-------|--------|
| `brain-pull-sources` | `src/<source>/` |
| `brain-rebuild-services` | `outputs/services/` |
| `brain-rebuild-memory` | `memory/L1/`, `memory/L2/` |
| `brain-pull-my-meeting-notes` | `src/gmeet/` |
| `brain-prepare-my-deep-dives` | `outputs/agents/my-deep-dives/` |
| `brain-prepare-my-one-on-one` | `outputs/agents/my-one-on-one/` |

## When to Use

Run at the start of each working day to fully bootstrap the brain and prepare all meeting agendas at once.
