---
name: brain-morning-start
description: >
  Daily bootstrap: update tools, sync brain sources, rebuild memory and service docs,
  harvest meeting notes, and prepare today's agendas for deep dives and 1:1s. Use when the user says
  "morning start", "start my day", "daily bootstrap", "morning routine", or
  "prepare my day".
---

# Morning Start

Daily bootstrap: update tools (brew, npm, gstack, python), sync brain sources, rebuild memory and service docs, harvest yesterday's meeting notes, and prepare today's agendas for deep dives and 1:1s.

## Part 1 — Update tools & sync

1. **Brew update & upgrade** — run `brew update && brew upgrade` to update Homebrew and upgrade all installed formulae and casks.

2. **Global npm packages** — run `npm update -g` to update all globally installed npm packages (includes `qmd`).

3. **Gstack** — run `/gstack-upgrade` to update gstack to the latest version.

4. **Python packages** — run `uv sync --upgrade` to update the Python packages used by this repo.

5. **qmd reindex** — run `npx qmd update` (or `uv run qmd update` if using uv scripts) to rebuild the brain search index with any new content.

6. **Git pull** — run `git pull --rebase` to pull the latest brain changes.

7. **Report** — summarize what was updated, flag any errors or version bumps worth noting.

## Part 2 — Brain sync & rebuild (sequential with parallel start)

### 2a. Pull sources (`brain-pull-sources`)
Export all external sources (ClickUp, Confluence, GDrive, Linear, GitHub, Medium, Metabase) and refresh L2 memory files. This is the heavy lifting of fetching fresh data from all integrations.

**Run Part 3 in parallel with this** — meeting notes harvest is independent.

### 2b. Rebuild services (`brain-rebuild-services`)
Regenerate deep technical `.AGENT.MD` service documentation from cloned GitHub repos. Only runs when repos have changed since last sync. Updates cross-cutting RabbitMQ topology files when messaging configs change.

**Wait for:** Part 2a complete (needs `src/github/` updated with latest repos).

### 2c. Rebuild memory (`brain-rebuild-memory`)
Rebuild the memory layers L2 (domain knowledge) and L1 (navigation MOCs) from the latest source exports and service docs. This creates team files, releases tracking, entity index, and navigation MOCs like `hub.md` and `teams.md`.

**Wait for:** Part 2b complete (needs `outputs/services/` updated with latest service docs).

## Part 3 — Harvest yesterday's meeting notes (parallel with Part 2a)

Run the `brain-pull-my-meeting-notes` skill for **yesterday** (the default range). This fetches calendar events, grabs Gemini notes and recording transcripts from Google Drive attachments, and produces a daily digest with decisions and action items.

Output goes to `src/gws/gmeet/YYYY/WNN/MM-DD/`.

**Parallel:** This runs in parallel with Part 2a (pull-sources) — it reads from GWS/Calendar, not from brain memory.

## Part 4 — Prepare today's meetings

Fetch today's calendar, identify deep dives and 1:1s, and generate agendas for each meeting in parallel.

### Step 4a — Fetch today's calendar

Compute today's date boundaries in Europe/Rome (start of day → end of day), convert to UTC, and fetch events:

```bash
gws calendar events list --params '{
  "calendarId": "primary",
  "timeMin": "<TODAY_START_UTC>",
  "timeMax": "<TODAY_END_UTC>",
  "singleEvents": true,
  "orderBy": "startTime"
}'
```

### Step 4b — Classify events

Scan the results and sort into two buckets:

| Type | Match rule |
|------|-----------|
| Deep Dive | `summary` contains "Deep Dive" (case-insensitive) |
| 1:1 | `summary` contains "1:1" (case-insensitive), excluding "Prepare for 1:1s" |

Skip cancelled events (`status: "cancelled"`). Log any events that partially match but don't fit either bucket.

### Step 4c — Report the day's schedule

Print a quick summary of what was found before starting the agents:

```
Today's meetings to prepare:
- 11:00 — Deep Dive SAITAMA
- 14:00 — 1:1 Alex
- 16:00 — 1:1 Ryan
```

If no deep dives or 1:1s are found, report "No deep dives or 1:1s on the calendar today".

### Step 4d — Run deep-dive skill

For each deep dive found, spawn an Agent that invokes the `brain-prepare-my-deep-dives` skill with `LOOKAHEAD_DAYS: 1` (today only). If multiple deep dives exist, run them **in parallel** using concurrent Agent tool calls.

**Deep Dive Skill Details:**
- Reads `memory/L1/teams.md` to map calendar team names to Linear teams
- Queries Linear for active projects per team
- Computes flags: OVERDUE, At Risk, No update Nd, No target, NEW
- Generates agenda sections: items due before next deep dive, overdue, at-risk/stale, upcoming work, capacity gaps
- Output: `outputs/agents/my-deep-dives/<team-slug>.md`

### Step 4e — Run 1:1 skill

For each 1:1 found, spawn an Agent that invokes the `brain-prepare-my-one-on-one` skill with `LOOKAHEAD_DAYS: 1`. If multiple 1:1s exist, run them **in parallel** using concurrent Agent tool calls.

**1:1 Skill Details:**
- Reads `memory/L1/team-members.md` to resolve person identity from calendar
- Reads previous agenda from `outputs/agents/my-one-on-one/<slug>.md` for follow-ups
- Queries Linear for projects led by this person, high-priority issues, and bugs
- Enriches with brain context (recent meeting notes, WorkFlowy entries)
- Generates agenda sections: follow-ups from last 1:1, delivery deadlines, at-risk/stale items, strategic topics, capacity & team health
- Output: `outputs/agents/my-one-on-one/<person-slug>.md`

Steps 4d and 4e can run in parallel with each other — launch all agents at once.

## Part 5 — Final report

After all agents complete, print a combined summary:

```
Morning start complete:

Tools:
  - brew: <N> packages upgraded
  - npm/gstack/python: <status>

Brain sync & rebuild:
  - Sources: <N> exported (X succeeded, Y failed)
  - Services: <N> docs refreshed
  - Memory: L2 <N> files, L1 <N> MOCs updated

Yesterday's meetings harvested:
  - <N> meetings processed → src/gws/gmeet/...

Today's prep:
✓ Deep Dive SAITAMA → outputs/agents/my-deep-dives/saitama.md
✓ 1:1 Alex → outputs/agents/my-one-on-one/alex.md
✓ 1:1 Ryan → outputs/agents/my-one-on-one/ryan.md
```

## Skill References

| Skill | Purpose | Output Location |
|-------|---------|-----------------|
| `brain-pull-sources` | Export all external sources (ClickUp, Confluence, GDrive, Linear, GitHub, Medium, Metabase) | `src/<source>/` |
| `brain-rebuild-services` | Generate deep `.AGENT.MD` service docs from GitHub repos | `outputs/services/` |
| `brain-rebuild-memory` | Rebuild L2 domain knowledge and L1 navigation MOCs | `memory/L1/`, `memory/L2/` |
| `brain-pull-my-meeting-notes` | Harvest yesterday's meeting notes and transcripts | `src/gws/gmeet/` |
| `brain-prepare-my-deep-dives` | Prepare deep-dive agendas from Linear project data | `outputs/agents/my-deep-dives/` |
| `brain-prepare-my-one-on-one` | Prepare 1:1 agendas from Linear and brain context | `outputs/agents/my-one-on-one/` |

## When to Use

Run at the start of each working day to fully bootstrap your brain and prepare all meeting agendas at once.

## Execution Flow

```
Part 1: Tool updates (sequential)
  ├─ Brew update & upgrade
  ├─ npm update -g
  ├─ gstack upgrade
  ├─ uv sync --upgrade
  ├─ qmd reindex
  └─ git pull --rebase
  ↓
Part 2a + Part 3 (parallel start)
  ├─ brain-pull-sources ───────────────────────────────────┐
  │    └─ Export ClickUp, Confluence, GDrive, Linear,     │
  │       GitHub, Medium, Metabase → src/                │
  │                                                      ↓
  ├─ brain-pull-my-meeting-notes ────────────────────────┤
       └─ Harvest yesterday's meetings → src/gws/gmeet/   │
                                                         │
Part 2b: brain-rebuild-services ────────────────────────→┤
  └─ Generate service docs from repos → outputs/services/│
                                                         ↓
Part 2c: brain-rebuild-memory ────────────────────────────┘
  └─ Rebuild L2 domain knowledge + L1 MOCs → memory/
                                                         ↓
Part 4: Prepare today's meetings (after Part 2c complete)
  ├─ Fetch calendar → classify events
  ├─ brain-prepare-my-deep-dives (parallel per team)
  │    └─ Query Linear → outputs/agents/my-deep-dives/
  └─ brain-prepare-my-one-on-one (parallel per person)
       └─ Query Linear → outputs/agents/my-one-on-one/
  ↓
Part 5: Final report
```

**Dependency chain:**
1. `brain-pull-sources` exports all external sources to `src/`
2. `brain-rebuild-services` reads `src/github/`, writes `outputs/services/*.AGENT.MD`
3. `brain-rebuild-memory` reads `src/` + `outputs/services/`, writes `memory/L1/` + `memory/L2/`
4. Meeting prep skills read `memory/L1/teams.md` and `memory/L1/team-members.md`

**Independent/parallel:**
- `brain-pull-my-meeting-notes` can run parallel with Part 2a (GWS/Calendar is independent)
