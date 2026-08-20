---
name: brain-prepare-my-deep-dives
description: >
  Prepare deep-dive meeting agendas by fetching calendar events and active Linear projects
  for each team. Use when the user says "prep deep dive", "prepare deep dives", "deep dive agenda",
  or asks to prepare for a specific team's deep dive. Also triggered by /prepare-my-day for
  calendar events containing "Deep Dive".
---

# Deep Dive Prep Agent

Prepare deep-dive meeting files by fetching upcoming calendar events and active Linear projects for each team. Output: one file per team in `outputs/agents/my-deep-dives/`.

## Configuration

```
TIMEZONE: Europe/Rome
OUTPUT_DIR: outputs/agents/my-deep-dives
LOOKAHEAD_DAYS: 5
TODAY: (compute dynamically)
```

Calendar-pattern → file-slug → Linear-team mapping originates in `$BRAIN_CONFIG` (default `<project>/.super/brain.config.yml`) → `teams[]`. `brain-rebuild-memory` projects that into `memory/L1/teams.md`, which this skill reads at runtime. To add/rename a team, edit the config and re-run `brain-rebuild-memory`.

### Calendar-to-Linear team mapping

Read `memory/L1/teams.md` at the start of every run. Extract the **machine-readable mapping table** (columns: Team name, Calendar patterns, File slug, Linear teams, Members).

The calendar event summary contains "Deep Dive" plus a team name. Extract the team slug and map it to one or more Linear team names using that table.

**If the team cannot be found in `memory/L1/teams.md`:**
Stop and ask the user: *"I found a Deep Dive for '<team>' but it's not mapped in memory/L1/teams.md. What Linear team(s) should I map it to?"*
Do NOT skip the event silently — ask for clarification so `brain-rebuild-memory` can be run later to update the mapping.

---

## Step 1 — Fetch upcoming deep-dive events

Compute the time window: from now to +LOOKAHEAD_DAYS (midnight Europe/Rome, converted to UTC).

```bash
gws calendar events list --params '{
  "calendarId": "primary",
  "timeMin": "<NOW_UTC>",
  "timeMax": "<END_UTC>",
  "singleEvents": true,
  "orderBy": "startTime",
  "q": "deep dive"
}'
```

Filter results:
1. Keep only events whose `summary` contains "Deep Dive" (case-insensitive)
2. Skip cancelled events (`status: "cancelled"`)
3. Extract for each event:
   - `summary` (to derive team slug)
   - `start.dateTime` (meeting date and time)
   - `attendees[]` (names/emails)
   - `description` (contains ODG/Roadmap/Deck links — preserve these)

**Team slug extraction:** Strip "Deep Dive", " - ", leading/trailing whitespace from the summary. Lowercase the remainder. Match against the Calendar patterns column in `memory/L1/teams.md`. Examples:
- `"SAITAMA - Deep Dive"` → `saitama`
- `"DEVOPS & IT - Deep Dive"` → `devops-it`
- `"Deep Dive Tech"` → `tech`
- `"DATA - Deep Dive"` → `data`

Use the **File slug** from the matching row for the output filename (`outputs/agents/my-deep-dives/<slug>.md`).

---

## Step 2 — Fetch Linear projects for each team

For each Linear team listed in the `Linear teams` column of the matching row, query Linear for active projects (not completed, not cancelled):

Use the `list_projects` Linear MCP tool:
- `team`: the Linear team name
- `limit`: 50

If the `Linear teams` column is `—` (none), skip the Linear queries and build the agenda from brain
context only — **but say so in the output.** Put this banner under the agenda's header, and repeat
the reason in place of the `## Linear Projects` table rather than dropping the section:

```markdown
> ⚠️ **Linear sections skipped for <TEAM>** — no Linear teams recorded for this team in
> `memory/L1/teams.md`. This agenda is INCOMPLETE, not empty. Fix: run `brain-rebuild-memory`
> (or add the team's Linear team names to `$BRAIN_CONFIG` `teams[]`), then re-run.
```

Also print `⚠️ Linear coverage: SKIPPED for <TEAM> — <reason>` in the run summary. An omitted
section that announces itself is recoverable; one that just isn't there reads as "nothing to
report". ⚠️ And note `mcp__linear__list_projects` **pages at 50 and truncates silently** — paginate
on `cursor` before counting anything.

Do this for **each Linear team** in the row. If a row has multiple teams (e.g., `DEVOPS, IT`), query each and merge results, deduplicating by project ID.

**Collect for each project** — pass `fields: ["name","status","lead","targetDate","priority","updatedAt","startDate","labels","createdAt","url","teams"]`:
- `name`, `url`
- `status.name` (Backlog, Planned, In Progress, Discovery, Paused, Completed, Cancelled) — **record it verbatim; it becomes the `Status` column**
- **`teams[]` — EVERY team on the project. This is mandatory: it becomes the `Teams` column AND drives the exclusion rule below.** Use the `key` (`TIUM`, `BUK`, `STO`, `AI`, `STM`, `CYC`, `RKT`, `DVO`, `IT`, `BI`, `DE`, `CNT`, `TIUX`, `DES`, `CRM`, `MAR`, and the guilds `BEG`, `FEG`, `GUI`, `AIG`, `STF`, `MOL`).
- `lead.name` (or **`— no lead`** if null), `targetDate` (or **`— none`** if null)
- `priority.name`, `updatedAt`, `startDate`, `labels`, `createdAt`

**Also fetch, for every project you will list:** its most recent **status update** (`get_status_updates`) — the date *and* any percentage. ⚠️ **`updatedAt` is NOT a status update: it moves on any field edit and does not move when a status update is posted.** Use `updatedAt` only for "untouched Nd"; use `get_status_updates` for everything you call progress.

### ⚠️⚠️ MANDATORY — milestones override issue counts

**Fetch every project's milestones in one workspace-wide GraphQL call before writing any Progress cell:**

```bash
set -a && source .env.local && set +a
# POST https://api.linear.app/graphql  (Authorization: $LINEAR_API_KEY)
# query { projects(first:100, after:$c) { pageInfo{hasNextPage endCursor}
#   nodes { name url state projectMilestones(first:30){ nodes{ id name progress targetDate } } } } }
```

Then per milestoned project, get issue-to-milestone assignment:
`project(id:$slugId){ issues(first:250){ nodes{ state{type} projectMilestone{id} } } }`

**Every progress measure is blind to something, and they fail in opposite directions:**

| Measure | Blind to | Fails |
|---|---|---|
| issues closed / issues existing | **scope with no tickets written** | **over-reports — 100% on a half-built project** |
| milestone roll-up | issues assigned to no milestone | under-reports |

**Rules:**
1. **Project has milestones -> report `N of M milestones` + the current milestone's %.** Never a project-wide issue percentage.
2. **A milestone with zero issues is `scope not written`** — a distinct state from "0% with open issues". Never render either as progress.
3. **"100%" / "close it" requires ALL milestones at 100% AND none without issues.** Never conclude "close it" from an issue count.
4. **Current milestone unwritten + past target -> the row is red**, however complete the earlier milestones.
5. **Report issues belonging to no milestone** when there are any — the milestone model is then incomplete.

WHY THIS IS MANDATORY: on 2026-08-20 *Digest email — what's new on your departures* was written up as
**`100% (24 issues)` in the green bucket with a "close it" talking point.** All 24 issues were in **M1**
(shipped Aug 4); **M2 was 0% with no issues written**, its scope had been **reversed on Aug 19**, and the
project was **restarted that morning**. **16 of 84 milestoned rows were wrong the same way, two of them
recommending closure of live work.** Do not skip this step.

**Filter out:** projects with status `Completed` or `Cancelled` — **except** those completed or cancelled since the previous agenda, which go in the ✅ bucket.

### ⚠️ MANDATORY — the >2-team exclusion rule

**A project whose `teams[]` has MORE THAN TWO entries appears in this agenda ONLY if this team has open issues in it.**

For every such project, get **every** issue — not the first page:

```bash
set -a && source .env.local && set +a          # brain's LINEAR_API_KEY
wr-linear issues list --project "<exact name>" --all
```

⚠️ **Do NOT use `list_issues(..., limit: 250)` for this.** It caps at 250 and returns
`hasNextPage: true` without telling you what it dropped. **Bugs Triage has 355 issues**: page one
reads as "STOMP has open work" when all 3 STOMP issues are closed. `wr-linear … --all`
auto-paginates. Count by **`state.type`**, not by the status name.

**The test differs by bucket — this is the part that gets missed:**

| Bucket | Test | Why |
|---|---|---|
| 🔴 🟠 🟢 🔵 ⚪ ⏸ | **open issues > 0** (`state.type` not `completed`/`canceled`) | active work the room owns |
| ✅ Shipped | **any issue ever > 0** | a completed project has zero *open* issues by definition; the open test would delete the whole credit ledger |

**Zero → drop the project from the agenda entirely** and record it in `Notes & caveats` under
**"Excluded — >2-team programmes with no open <TEAM> work"**, with the **evidence**: the team's
open/ever counts, or "the project has no issues at all".

⚠️ **NEVER retro-apply this to a file marked `freshness: ARCHIVED`.** Today's counts describe today;
an April agenda that called something on-track was right then. Leave archived registers as written
and say in Notes that the rule was not applied and why.

⚠️ **Apply it to EVERY >2-team project, not just the obvious standards ones.** On 2026-08-20 this
rule was first applied to 14 of 51 multi-team projects and the other 37 were asserted, not measured —
which left **TIUM carrying Hightouch as a red 51-days-overdue item when all 28 TIUM issues on it were
closed**, and **GED showing three "on track" projects with no Design issue at all.** Enumerate the
>2-team set from your own register, then measure all of it.

**Why this is not optional:** the same ten-team standards programmes (`Improve IDP score`,
`Database documentation`, `API Documentation`, `Audit blockers (SDLC)`, `Incidents & Post Mortem`,
`Bugs Triage`, …) sit on every board. Measured on 2026-08-20, **`Incidents & Post Mortem` had open
issues for only STAFF and BUKTU** — it was on the TIUM, STOMP, CYCLOPS, SAIAN and DEVOPS agendas
with **every one of their issues already Done.** A dive that spends its 30 minutes on work the room
does not own is the failure this rule exists to prevent.

**Projects on one or two teams are always listed** — no issue check needed.

**Compute flags for each project:**
- `OVERDUE`: targetDate is in the past AND status is not Completed/Cancelled
- `Silent Nd`: days since the last **status update** (not `updatedAt`)
- `Untouched Nd`: days since `updatedAt` — use this wording, never "no update", when the figure comes from `updatedAt`
- `No target`: targetDate is null AND status is In Progress / Planned / Discovery
- `NEW`: createdAt is within the last 14 days

**Sort within each bucket:** by targetDate ascending, nulls last.

---

## Step 3 — Generate the agenda

**The output format is defined by `reference.md`, beside this file. READ IT before writing
anything.** It is the single source of truth for section order, the RAG rules, the eight table
columns and the honesty rules. What follows summarises it; **where they differ, `reference.md` wins.**

### Section order — fixed, and a section with nothing in it stays (with `_none_`)

1. Title + `<!-- deep-dive-agenda: v1 | team: … | linear: … | generated: … | freshness: LIVE -->`
2. Links (Board / ODG / Roadmap / OKRs / Deck / Meet) + **In the room** (✅ accepted · ⏳ no reply · ❌ declined)
3. `## 🚦 Health` — the RAG count table + a one-line **Verdict**
4. `## ⭐ Top 5 talking points` — **max 5**, ordered by what to say first, each ending in an ask
5. `## 📋 Projects by status` — one table per RAG bucket
6. `## ⏱ Due before the next deep dive` — *optional*, for dated **issues**
7. `## 👥 Ownership & load`
8. `## 📝 Your topics` — **always present, always empty**
9. `## 🗒️ Notes & caveats`

### RAG buckets — mechanical, in this order

| ● | Bucket | Assign when |
|---|---|---|
| 🔴 | Overdue / blocked | past target · or Urgent and not started · or **silent 60+ days** · or a hard external commitment with nothing tracked · or a named blocker / live production risk |
| 🟠 | At risk / stale | **silent 14–59 days** · or target within 14 days and not started · or target slipped · or In Progress with no target |
| 🟢 | On track | In Progress, status update within 14 days, target still ahead |
| 🔵 | Planned / new | Planned, or created in the last 14 days |
| ⚪ | Dormant / unowned | Backlog with no movement · no lead **and** no movement · explicit archive candidate |
| ⏸ | Paused | **Linear status is `Paused`. Always its own bucket, whatever the target or staleness** |
| ✅ | Shipped since last dive | Completed or Cancelled since the previous agenda — **always show it** |

**One bucket per project**, precedence 🔴 → 🟠 → 🟢 → 🔵 → ⚪, with **two overrides that beat
everything: `Paused` → ⏸ always** (it's a decision, not a health state), and **never started
(no work ever recorded) → ⚪ however overdue** (that's inventory, not risk). Print the overdue days
in the row regardless.

### The project table — eight columns, identical in every bucket

```markdown
| ● | Project | Teams | Status | What's up | Owner | Target | Progress |
|---|---|---|---|---|---|---|---|
| 🔴 | [Product page 3.0](url) | `TIUM` `DES` | In Progress | Jul 28 (23d): target pushed in that same update. Diana back Aug 12 — **new date?** | Matteo Diana | **Aug 17** `3d late` | `████░░░░░░` 40% |
```

- **Teams** — every team on the project, **this dive's team first**. Bold nothing; code-span each key.
- **Status** — Linear's own **`status.name`**, verbatim. **Bold it when it contradicts the evidence**
  (`**Backlog** ⚠️` on a project with an Aug 17 status update). The gap between the board's claim
  and the RAG chip is often the finding. ⚠️ **Check it against `status.name`, NOT the GraphQL `state`
  field** — `state` is the bucket, so `Paused` reads as `backlog` and `Discovery` as `planned`, which
  manufactures false drift. ⚠️ **Re-verify statuses immediately before publishing:** on 2026-08-20
  five cells drifted between the 09:30 build and the 12:00 publish, one of them a project written up
  as the board's only Urgent item that had been **cancelled** in between.
- **What's up** — latest reported state *and* the ask, in one cell. **Lead with the date of the last
  status update.** Not a description of what the project is.
- **Owner** — `lead.name`, or **`— no lead`** in bold. **Target** — bold when inside 14 days or past;
  append `` `Nd late` `` / `` `Nd` ``; **`— none`** when unset.
- **Progress** — 10-cell bar + percent (`██████░░░░` 60%). **`— never reported`** when no status
  update has ever been written. Say which measure you used in Notes & caveats and **never mix two
  measures in one column.**

### Honesty rules (all of them are in `reference.md`; these are the ones most often broken)

- **Never invent a field.** `— no lead` / `— none` / `— never reported`. A plausible guess in a table reads as measurement.
- **Date every claim of progress.** "Aug 19: QA done" beats "QA is done".
- **`updatedAt` is not a status update.**
- **Counts in headings are live counts**, re-measured every run — never carried forward.
- **`list_projects` pages at 50 and truncates silently.** Paginate before counting.
- **Tone:** direct, questioning, concise. No filler. Write like a CTO prepping for a 30-minute check-in.

### Regenerating an existing file

**If the file exists, overwrite it completely** — each run produces a fresh file. **But before you
do:** if the existing file's meeting date is in the past and you are not regenerating it for a new
meeting, **do not silently re-date it.** Set `freshness: ARCHIVED`, add the stale banner, and leave
its as-of figures alone. **Never re-measure a past meeting against today's Linear.**

### The folder holds ONE current agenda per forum

`OUTPUT_DIR` top level = **the current agenda for each forum, and nothing else.**

- **When a forum's meeting recurs under a NEW file slug** (a rename, a merge, a re-scope — e.g.
  `devops-it` → `devops`, `deep-dive-tech` → `tech`, `ai-sales` → `crm-sales-ai`), the old file is
  **superseded, not kept alongside.** Give it `freshness: ARCHIVED`, add a banner naming its
  successor, then **`git mv` it to `OUTPUT_DIR/archive/`** and fix its outward links to `../`.
- **Never write a new agenda into `archive/`**, and never resurrect a file from there — regenerate
  the live slug instead.
- **Nothing that is not a team deep-dive agenda belongs in this folder.** Vendor briefings, research
  notes and one-off meeting docs go elsewhere under `outputs/`. If it has no Linear board and no
  room of engineers, it is not a deep dive — **do not create it here.**

---

## Step 4 — Publish to b-eye

Every agenda is also a dashboard in b-eye → *Tech: Product → Deep Dives*
(`beye.weroad.com/browse/a830ba29-0623-4019-aa2e-74eafa7faec7`), archives under its
**Archive (superseded)** subfolder. **Publish in the same run that generated the file** — from the
brain root, naming only the slug you just wrote:

```bash
python3 .claude/skills/brain-prepare-my-deep-dives/publish-to-beye.py <slug>
```

**Publish every run.** The build→publish gap is where dashboards go wrong: on 2026-08-20 five status
cells drifted between the 09:30 build and the 12:00 publish, one of them a project written up as the
board's only Urgent item that had been **cancelled** in between. Same-run publishing is the only way
that window is actually zero. Skip it with `--no-publish` (or `--render`) when you deliberately want
the `.md` only.

**Name your slug and nothing else.** The publisher takes slugs, not paths, and errors on a bare
invocation rather than republishing all 20 dashboards or silently doing nothing. `--all` is for a
deliberate full pass and also republishes `reference.md` as the *"The standard"* dashboard; a per-team
run must never touch the archives or the template.

⚠️ **`.beye-assets.json` lives in the agendas folder and must stay committed.** It maps slug → asset
id, which is what makes a re-run append a *version* instead of creating a duplicate dashboard. The
publisher merges and atomically replaces it, because **`brain-morning-start` fans out one agent per
meeting in parallel** and a last-writer-wins overwrite drops a sibling's new id — surfacing one run
later as a duplicate.

⚠️ **Re-verify the `Status` column against live Linear immediately before publishing**, not only at
build time. See Step 3.

**Do not hand-edit the generated HTML.** The converter already satisfies every b-eye render
constraint: CSP `default-src 'none'` + `style-src 'unsafe-inline'` so everything is inlined (no
external CSS, JS, fonts or images); the viewer chrome is light-only so the page pins light rather
than following `prefers-color-scheme`; and the viewer iframe is `sandbox="allow-scripts allow-popups
allow-popups-to-escape-sandbox"`, so `target="_blank"` links to Linear **do** open (verified on
v1.23.1 — read the live attribute before assuming otherwise).

**If publishing fails, keep the agenda and say so.** The `.md` on disk is the primary output, so an
expired `wr-beye` login must not throw away a good agenda — but a stale dashboard has to announce
itself. The publisher exits non-zero and lists every failed slug with its reason; carry that into
Step 5 verbatim. An omission that announces itself is recoverable; one that doesn't reads as fresh.

⚠️ **A `WARN <file>:<line> — line claimed by no block rule` on stderr means the agenda is malformed**
— almost always a table row whose `|---|` separator line is missing. The row is emitted as a
paragraph and will look wrong in the dashboard, which is deliberate. **Fix Step 3's output and
regenerate; never hand-patch the `.md`.** Before this warning existed such a row hung the publisher
in an infinite loop with no error and no exit: on 2026-08-20 `buktu.md:133` stalled the 14:06 run and
left b-eye stale for 18 of 20 dashboards.

---

## Step 5 — Report results

Print a summary:
- How many deep dives found in the next LOOKAHEAD_DAYS
- For each: team name, date/time, **projects listed vs projects on the board**, the RAG counts, and
  **how many >2-team programmes were excluded for having no open issues on that team**
- Path to each generated file
- **b-eye: the dashboard version published per slug, or the failure reason.** Never report a run as
  clean when a publish failed — name the stale dashboards.
- **Any `WARN … claimed by no block rule` lines**, with the file and line, as a malformed-agenda
  defect to fix in Step 3

---

## Running

**Default (next 5 days):**
```
/my-deep-dives
```

**Custom lookahead:**
```
/my-deep-dives --days 10
```

**Single team:**
```
/my-deep-dives saitama
```

**Without publishing to b-eye** (writes the `.md` only):
```
/my-deep-dives --no-publish
```

Override LOOKAHEAD_DAYS or filter to a single team accordingly. Publishing is on by default — see
Step 4.
