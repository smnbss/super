---
name: brain-prepare-my-one-on-one
description: >
  Prepare 1:1 meeting agendas by fetching calendar events, querying Linear for each person's
  projects/issues, checking previous agendas for follow-ups, and generating pointed agendas.
  Use when the user says "prep 1:1", "prepare 1:1", "1:1 agenda", or asks to prepare for
  a specific person's 1:1. Also triggered by /prepare-my-day for calendar events containing "1:1".
---

# 1:1 Prep Agent

Prepare 1:1 meeting agendas by fetching upcoming calendar events, querying Linear for each person's outputs/issues, checking previous agendas for follow-ups, and generating pointed agendas. Output: one file per person in `outputs/agents/my-one-on-one/`.

## Configuration

```
TIMEZONE: Europe/Rome
OUTPUT_DIR: outputs/agents/my-one-on-one
LOOKAHEAD_DAYS: 7
TODAY: (compute dynamically)
```

### Person resolution

Do NOT use a hardcoded mapping file. Resolve each person's identity from `memory/L1/team-members.md`, with brain search as a fallback.

For every 1:1 calendar event:
1. **Extract the identifier** from the summary: strip "1:1", "Simone Basso", "/", " - ", separators. The remaining text is the raw identifier (e.g., `Bera`, `Alex`, `Cass`). Also inspect `attendees[]` for email and full-name hints.
2. **Read `memory/L1/team-members.md`**. Look for a row where the **Name patterns** column matches the identifier (case-insensitive). If found, use that row for:
   - `full_name`: from the Name patterns (prefer the full-name variant)
   - `role`: from the **Role** column
   - `team` / `department`: from the **Team / Department** column
   - `email`: from the **Email** column, or fall back to calendar attendees
   - `linear_teams`: from the **Linear teams** column (`—` means the person does not use Linear)
3. **If not found in `memory/L1/team-members.md`**, search the brain using `qmd query "<identifier> role position team"`. Also try `qmd query "<identifier> people hr"`. Combine results to build the person's context.

**If identity still cannot be resolved** (neither `team-members.md` nor brain search returns a clear match):
Stop and ask the user: *"I found a 1:1 with '<identifier>' but couldn't resolve who they are. Who is this person? (full name, role, team/department, email, Linear team names if any). Tip: update memory/L1/team-members.md or run brain-rebuild-memory so next time the lookup works automatically."*
Do NOT skip the event silently — ask for clarification so the brain can be updated.

---

## Step 1 — Fetch upcoming 1:1 events

Compute the time window: from now to +LOOKAHEAD_DAYS (midnight Europe/Rome, converted to UTC).

```bash
gws calendar events list --params '{
  "calendarId": "primary",
  "timeMin": "<NOW_UTC>",
  "timeMax": "<END_UTC>",
  "singleEvents": true,
  "orderBy": "startTime",
  "q": "1:1"
}'
```

Filter results:
1. Keep only events whose `summary` contains "1:1" (case-insensitive)
2. Skip events titled "Prepare for 1:1s" (that's a prep block, not a meeting)
3. Skip cancelled events (`status: "cancelled"`)
4. Extract for each event:
   - `summary` (to derive person slug)
   - `start.dateTime` (meeting date and time)
   - `attendees[]` (names/emails — use to confirm person identity)
   - `description` (may contain WorkFlowy or other links)

**Person slug extraction:** From the summary, strip "1:1", "Simone Basso", "/", " - ", separators. The remaining identifier becomes the file slug (lowercased, spaces → hyphens). Example: `Bera` → `bera`, `Alex` → `alex`. Use this slug for `outputs/agents/my-one-on-one/<slug>.md`.

---

## Step 2 — Read the previous agenda

For each person, check if a previous agenda exists at `outputs/agents/my-one-on-one/<slug>.md`.

If it exists:
1. Read the file
2. Extract all items — these are potential follow-ups
3. Mark items that look like they need a status check (questions asked, deadlines set, actions requested)

This previous agenda is KEY context. Many items will carry forward with an updated status check.

---

## Step 3 — Fetch Linear data for each person

### 3a. Projects led by this person

**STRICT PROJECT ATTRIBUTION RULE:** Only include projects where this person is explicitly the `lead` in Linear. Do NOT include projects just because:
- They are on the same team as the project
- They are a member of the project
- The project is in a team they manage (unless they are also the lead)

Only fetch Linear data if brain search indicates the person uses Linear (e.g., they are listed as a member/lead of Linear teams, or `qmd query "<full_name> Linear"` returns relevant hits).

If Linear teams are known, query each with `list_projects`:
- `team`: each known Linear team name
- `limit`: 50

If no Linear context is found, **skip all Linear sections entirely** (Sections 2–4 of the agenda can be populated from brain context and previous agendas only). Do not issue blanket cross-team Linear queries for people who are not on Linear.

Filter to active projects (not Completed, not Cancelled). **CRITICAL:** Only keep projects where `lead.name` matches the person's name (case-insensitive) OR `lead.email` matches the person's email.

**If a project appears in the person's team but is led by someone else:**
- DO NOT include it in their agenda
- If it's a project they depend on or care about, it may appear in "Strategic Topics" if brain search reveals relevance
- DO NOT attribute other people's projects to this person

Collect:
- `name`, `status.name`, `lead.name`, `targetDate`, `priority.name`, `updatedAt`, `startDate`, `labels`, `url`

**Compute flags** (same as deep-dives agent):
- `OVERDUE`: targetDate in the past, status not Completed/Cancelled
- `At Risk`: priority Urgent and not In Progress, OR overdue
- `No update Nd`: updatedAt > 14 days ago
- `No target`: targetDate null AND status In Progress or Planned
- `NEW`: createdAt within last 14 days

### 3b. Issues assigned to this person (high priority / overdue)

If the person has known Linear teams, query `list_issues` for each team. If no Linear context is found, skip this step entirely. Filters:
- Assignee: the person (match by name or email)
- Priority: Urgent or High
- Status: not Done, not Cancelled
- Limit: 20

Also query for bugs assigned to this person:
- Label: "Bug" or type "Bug"
- Status: not Done, not Cancelled

### 3c. Project attribution validation

Before including any project in the agenda, verify:
1. Person is the `lead` in Linear (name or email match)
2. OR person is explicitly assigned to key issues in that project
3. If project is led by someone else → exclude or flag as cross-team dependency

**Common misattribution to avoid:**
- Marina (CNT/Content) getting Design Team projects led by Alessandro Trezzi
- Engineering managers getting projects from adjacent teams they don't lead
- Cross-functional initiatives appearing under multiple people (should only appear under the actual lead)

### 3d. Recent incidents / post-mortems (if relevant)

If the person manages teams with active incidents, check for recent incident projects.

---

## Step 4 — Enrich with brain context

Search the brain for recent context about this person and their areas. Use qmd:

```bash
qmd query "<person name> <team name> recent updates"
```

Check:
- `src/gws/gmeet/` — recent meeting notes mentioning this person
- `outputs/agents/my-workflowy/` — recent WorkFlowy entries for their section
- `outputs/agents/tech-linear-project-updates/` — recent project update reports

Extract any relevant decisions, blockers, or action items from the last 1-2 weeks.

---

## Step 5 — Generate the agenda

Combine all data sources to produce a **fact-based 1:1 agenda**. The agenda should be ready to use in the meeting — a clear picture of where things stand so you can decide what to dig into.

### Fact-first principle

**Stick to what the data says.** Every bullet must trace back to a Linear status, a date, an update field, or a brain-search hit. Do NOT:
- Editorialize or assign blame ("zero visibility is a red flag", "this is concerning")
- Speculate about causes ("Is he stuck? Overloaded?")
- Inflate urgency beyond what the data shows
- Add rhetorical questions — if there's a question, make it a single concrete ask

If a project has no update text, say "No update text since <date>." — don't dramatize it.

### Agenda generation rules

**Section 1: Follow-ups from last 1:1**
- Review the previous agenda (`outputs/agents/my-one-on-one/<slug>.md`)
- For each item that had a question or action: check if the answer is now visible in Linear data, meeting notes, or project updates
- If resolved: state the resolution with the source (e.g. "Shipped — TIUM-774 moved to Done on Apr 5")
- If NOT resolved: restate the original item and note what changed (or "no change in Linear since <date>")
- If partially resolved: state what moved and what didn't

**Section 2: Delivery — deadlines in the next 2 weeks**
- Projects with targetDate <= today + 14 days AND status In Progress or Planned
- For each: state deadline, current Linear status, last update date, and update text (verbatim if short)
- Overdue: state by how many days and current status

**Section 3: At-risk / stale items**
- Projects or issues with no update in 14+ days — state the last update date
- Bugs flagged as High/Urgent — state assignee, status, created date
- For each: state the fact, then one specific question if needed

**Section 4: Strategic / cross-cutting topics**
- Items from brain search that are factually relevant (meeting decisions, project dependencies, data points)
- Cross-team dependencies with their current status
- Keep this short — only include items with a concrete data point, not general themes

**Section 5: Capacity & team health** (for managers only)
- Count of active projects per person (from Linear data)
- Any person with 5+ active projects — list them
- Open roles or onboarding in progress (from brain search)

**Final section: "Your topics"**
- Always include an empty `## Your topics` section at the end for them to add items

### Tone
Factual, concise, neutral. Present the data; you will decide what matters.

Examples:
- "Target: Apr 9. Status: On Track. Last update: Apr 7."
- "Overdue by 8 days. Status: In Progress. No update since Mar 30."
- "Not in Apr 3 or Apr 7 weekly report. Last Linear status: On Track (Mar 25)."
- "HIGH priority, unassigned, created Mar 15. Still in Todo."
- "5 active projects. 2 due in next 14 days."

---

## Step 6 — Write the output files

Write one file per person to `outputs/agents/my-one-on-one/<slug>.md`.

**If the file already exists, overwrite it completely** — each run produces a fresh file.

Format:

```markdown
# 1:1 <Full Name> — W<NN> (<Day>, <Mon DD>, <HH:MM>)
<!-- generated: YYYY-MM-DD -->

## Follow-ups from last 1:1
- **<Topic>** — <what changed since last agenda, with source>

## Delivery — Hard Deadlines
- **[<Project name>](url)** (<target date>) — Status: <status>. Last update: <date>. <update text or "no update text">

## At-risk / Stale
- **<Item>** — <fact + date>

## Strategic Topics
- **<Topic>** — <data point from brain search with source>

## Capacity & Team Health
- <person>: <N> active projects, <flags if any>

## Your topics


---

## Linear Projects — <Person> Active

| Project | Status | Lead | Target | Flag |
|---------|--------|------|--------|------|
| [Project name](url) | In Progress | Lead Name | Apr 30 | On Track |
```

---

## Step 7 — Report results

Print a summary:
- How many 1:1s found in the next LOOKAHEAD_DAYS
- For each: person name, date/time, number of active projects, number of follow-ups from last agenda, number of flags
- Path to each generated file

---

## Running

**Default (next 7 days):**
```
/my-one-on-one
```

**Custom lookahead:**
```
/my-one-on-one --days 3
```

**Single person:**
```
/my-one-on-one alex
```

Override LOOKAHEAD_DAYS or filter to a single person accordingly.
