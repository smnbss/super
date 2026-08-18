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
ROSTER: memory/L1/team-members.md
```

### Person resolution → canonical slug

**The filename is derived from the resolved person, never from the calendar text.** Resolve identity FIRST; pick the filename LAST, from the roster. A calendar invite can say `Mattia`, `Mattia Riva`, `Simone / Mattia 1:1`, or `Mattia / Simone 1:1` for the same human — all four must land on the same file.

**Canonical slug = the `File slug` column of `memory/L1/team-members.md`.** That column is the single source of truth. It is full-name based (`mattia-riva`, `elena-giombelli`, `matteo-risso`) because first names collide badly in this roster — 27 first names are shared by 2+ people (6 Alessandros, 5 Lucas, 5 Francescas, 4 Simones, 3 Elenas, 2 Mattias, 2 Matteos). Never invent a slug, never shorten one, never slugify the calendar summary.

For every 1:1 calendar event:

1. **Extract the identifier** from the summary: strip "1:1", "Simone Basso", "Simone", "/", " - ", separators. The remaining text is the raw identifier (e.g. `Bera`, `Alex`, `Cass`). Collect `attendees[]` emails and display names too — **the attendee email is the strongest signal and outranks the summary text**.

2. **Read `memory/L1/team-members.md`** and match, in this priority order:
   1. **Attendee email** exactly equals the row's **Email** column → unambiguous, use it.
   2. **Full name** (2+ tokens, from the summary or an attendee display name) matches a full-name variant in the **Name patterns** column → use it.
   3. **Single-token identifier** matches the **Name patterns** column → only accept if **exactly one row matches**.

3. **Ambiguity guard.** If a single-token identifier matches 2+ rows (e.g. `Elena` → De Giuseppe / Giombelli / Solinas; `Mattia` → Frigerio / Riva), do NOT guess and do NOT fall back to the first-name slug. Disambiguate by attendee email, then by attendee display name. If still ambiguous, stop and ask the user which person it is. Picking wrong writes one person's agenda over another's file.

4. From the matched row take:
   - `slug`: the **File slug** column ← **this is the output filename, full stop**
   - `full_name`: the full-name variant in **Name patterns**
   - `role`: **Role** column
   - `team` / `department`: **Team / Department** column
   - `email`: **Email** column, or the calendar attendee email. **This is the Linear join key** — see Step 3.
   - `linear_teams`: **Linear teams** column. ⚠️ **Do not read a blank here as "does not use Linear."**
     The generated values are explicit — `none (no Linear account)`, `none (Linear account, no team)`,
     `— (not in Personio; join not possible)` — and only the first of those means "no Linear".
     A **bare `—`** means the row predates the 2026-08-18 fix or the rebuild failed to join, i.e.
     **unknown, not empty**: treat it as missing data, fall through to the email-keyed queries in
     Step 3, and flag it in the run summary (Step 6).

5. **If not found in the roster**, search the brain with `mcp__gbrain__query` for `"<identifier> role position team"` and `"<identifier> people hr"`. If that yields a confident full name, derive the slug as `lowercase(full name)` with spaces → hyphens and accents preserved (matching the roster's existing style, e.g. `abel-hernández-martín`) — i.e. **still a full-name slug**, never a first name.

**Non-roster and multi-person cases:**
- **Externals / candidates** (board members, advisors, interviewees) won't be in the roster. Use a full-name slug derived as in step 5 (`andy-owen-jones`, `paolo-ferretti`). Same rule, just no roster row.
- **Joint 1:1s** with two attendees besides Simone are not one person and must not be written to either person's canonical file — that would clobber an individual history. Use a combined slug of both full names (`andrea-damico-mattia-riva`) and skip legacy-slug recovery for it.

**If identity still cannot be resolved:**
Stop and ask the user: *"I found a 1:1 with '<identifier>' but couldn't resolve who they are. Who is this person? (full name, role, team/department, email, Linear team names if any). Tip: update memory/L1/team-members.md or run brain-rebuild-memory so next time the lookup works automatically."*
Do NOT skip the event silently, and do NOT write a file under a provisional first-name slug — that is exactly how history gets split.

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

**Person slug:** Do NOT slugify the summary. Run the identifier and the attendee emails through **Person resolution → canonical slug** above and use the roster's **File slug** for `outputs/agents/my-one-on-one/<slug>.md`. Example: summary `Simone / Mattia 1:1` + attendee `mattia.riva@weroad.com` → roster row `Mattia | Mattia Riva` → slug `mattia-riva` → `outputs/agents/my-one-on-one/mattia-riva.md`. The slug depends only on who the person is, so the same person always resolves to the same file no matter how the invite is worded.

---

## Step 2 — Read the previous agenda

For each person, check if a previous agenda exists at `outputs/agents/my-one-on-one/<slug>.md`.

If it exists:
1. Read the file
2. Extract all items — these are potential follow-ups
3. Mark items that look like they need a status check (questions asked, deadlines set, actions requested)

This previous agenda is KEY context. Many items will carry forward with an updated status check.

### Legacy-slug recovery (run before writing)

Historically this skill sometimes slugged on the first name instead of the full name, so a person's history may sit in a file under a different convention. **Before generating, look for that file** — otherwise the old history is silently orphaned and its open follow-ups vanish from every future agenda.

For each resolved person, `ls outputs/agents/my-one-on-one/` and check for any of these variants beyond the canonical `<slug>.md`:
- **First-name slug** — the first token of the full name (`mattia.md` for `mattia-riva`)
- **Last-name / nickname slug** — the last token, or a nickname in the roster's **Name patterns** (`risso.md` for `matteo-risso`, `lampe.md` for `andrea-lamperini`, `cass.md` for `cassiano-vailati-canta`)

Confirm the match by reading the candidate file's `# 1:1 <Full Name>` H1 — **match on the H1 name, not the filename**. `matteo.md` held Matteo *Diana*, not Matteo *Risso*; a filename guess would have merged the wrong person.

When a legacy file is confirmed for this person:
1. Read it and fold its unresolved items into Section 1 (Follow-ups) of the new agenda, same as a normal previous agenda.
2. Append its full text to the bottom of the canonical file under `## Archive — <week> (generated <date>, from \`<old file>\`)`, with heading levels demoted one step (`#`/`##` → `###`) so the outline stays intact.
3. Delete the legacy file, so the split does not recur.
4. Report the merge in Step 7.

Never write two files for one person. If both a canonical and a legacy file exist, the canonical one wins and absorbs the other.

---

## Step 3 — Fetch Linear data for each person

### 3a. Projects led by this person

**STRICT PROJECT ATTRIBUTION RULE:** Only include projects where this person is explicitly the `lead` in Linear. Do NOT include projects just because:
- They are on the same team as the project
- They are a member of the project
- The project is in a team they manage (unless they are also the lead)

**Query by email first. The `linear_teams` column is a fallback, not the gate.**

⚠️ **Gating on `linear_teams` is what broke this skill.** On 2026-08-18, 188 of 199 roster rows read
`—` while 73 of those people had live Linear teams; Alberto Marinelli — lead of 9 active projects
with 27 open issues — got an agenda with every Linear section silently omitted. It read as complete.
Never let the roster's team cell decide whether Linear gets queried.

1. **If `email` is known (it should be for every roster row), query Linear by person, not by team:**
   - `mcp__linear__list_projects` with `member: <email>`, `limit: 50`, then **paginate on `cursor`
     until `hasNextPage` is false** — the tool caps at 50 and truncates *silently*, returning a
     valid page with no hint more exist.
   - `mcp__linear__list_issues` with `assignee: <email>`.

   This is both simpler and strictly more complete than the team fan-out: Alberto's assigned issues
   span `BI, DE, GRO, TIUM, AIG` while he is a *member* of only three of those teams, so a
   team-driven query would have missed TIUM and AIG even with a correctly populated column.

2. **Use `linear_teams` only to widen** — for team-level context (cycles, team boards, sibling
   projects) once the person-level queries have run. Query each named team with `list_projects`
   (`team: <name>`, `limit: 50`, paginate).

3. **Skip Linear entirely only when the roster explicitly says there is nothing to query** —
   `none (no Linear account)`. Even then, say so in the output (Step 6) rather than just omitting
   the sections.

4. **If `email` is unknown AND `linear_teams` is a bare `—`**, you have no join key and unknown
   membership. Do **not** treat that as "not on Linear": try `mcp__linear__list_users` with
   `query: <full name>` once to recover the email, and if that fails, emit the loud banner in Step 6.

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

Query `list_issues` with `assignee: <email>` (the person-keyed query from 3a). Only fan out per team
when the email is unavailable. If Linear is skipped, say so per Step 6 rather than omitting silently. Filters:
- Assignee: the person (match by email first, name only as fallback)
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

Search the brain for recent context about this person and their areas using the
gbrain MCP tools:

- `mcp__gbrain__query` with `"<person name> <team name> recent updates"`

Check:
- `src/gmeet/` — recent meeting notes mentioning this person
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

⚠️⚠️ **HARD SIZE CAP: ~8 KB and at most 5 discussion items in the whole agenda.**
This is a **30-minute meeting with a hard stop**, and the agenda has to be readable in the
two minutes before it starts. Measured 2026-08-18: Matteo's agenda came out at
**60,438 bytes and cost 12.2M tokens** — roughly 7.5× the cap, for a meeting that could
never consume it. Alberto's was **16 KB, cost half as much, and was if anything more
actionable.** Length actively made the artifact worse: the five things worth saying were
buried in fifty.

Enforce it while writing, not by trimming afterwards:

- **Five items total across Sections 1–4**, not five per section. If a sixth is a
  candidate, it replaces a weaker one — the ranking is the work.
- **One fact + one question per item, two lines.** No paragraph of context. If the fact
  needs a paragraph to matter, it is not a 1:1 item.
- **No exhaustive lists.** `## Linear Projects — <Person> Active` is a reference appendix,
  not a discussion section; keep it to the projects that carry one of the five items.
- **Nothing without a concrete data point.** A theme with no date, ticket or number is
  the first thing cut.
- **Check before writing the file**: `wc -c` the draft. Over ~8 KB means cut items, not
  shorten sentences — trimming prose keeps the wrong five things.

An agenda that omits something important must say so via the coverage banner (Step 6) —
that is the pressure valve, not a longer document.

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

Write **exactly one file per person**, to `outputs/agents/my-one-on-one/<slug>.md`, where `<slug>` is the roster **File slug** resolved in Person resolution. Never write to a slug derived from the calendar summary.

**If the file already exists, overwrite it completely** — each run produces a fresh agenda. Two exceptions, both additive:
- Any `## Archive — …` sections already at the bottom of the file are **preserved verbatim**; re-append them below the fresh agenda. They are the only long-term history this directory keeps.
- A legacy-slug file found in Step 2 is archived into this file and then deleted.

### Coverage banner — an omitted section must announce itself

⚠️ **Never let a skipped data source look like an empty one.** If any Linear section is thin or
absent because the *lookup* did not run — not because the person genuinely has nothing — the agenda
MUST carry a banner directly under the `<!-- canonical-slug -->` line, and the reason must be
restated in place of each section it suppressed:

```markdown
> ⚠️ **Linear sections skipped for <Full Name>** — <reason>. This agenda is INCOMPLETE, not empty:
> the person may have active projects and issues that were never queried.
> Fix: <fix>, then re-run.
```

Reason / fix pairs, in the order you should prefer them:

| Condition | Reason text | Fix text |
|---|---|---|
| Roster `Linear teams` is a bare `—` **and** no email | `no Linear teams recorded and no email in memory/L1/team-members.md, so no Linear query could be keyed` | `add the Email cell (it exists on every Personio row) or run brain-rebuild-memory` |
| Email known but every Linear query returned nothing | *(no banner — this is a true empty; say "No active projects." explicitly)* | — |
| Roster says `none (no Linear account)` | `roster records no Linear account for this person` | — *(state it, no fix needed)* |
| Person not in the roster at all (external, candidate, founder/ExCo) | `not in memory/L1/team-members.md — Personio omits founders, ExCo and externals, so the Personio→Linear join cannot cover them` | `confirm the person's Linear email with the user` |
| A Linear call errored or hit an unpaginated cap | `Linear query failed/truncated: <detail>` | `re-run; if it persists, check the MCP server` |

Also write `<!-- linear-coverage: full | partial | skipped (<reason slug>) -->` next to the
`canonical-slug` comment on **every** agenda, so a later run can tell a genuinely quiet person from
an unqueried one.

Format:

```markdown
# 1:1 <Full Name> — W<NN> (<Day>, <Mon DD>, <HH:MM>)
<!-- generated: YYYY-MM-DD -->
<!-- canonical-slug: <slug> (memory/L1/team-members.md) -->
<!-- linear-coverage: full -->

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
- For each: person name, resolved canonical slug, date/time, number of active projects, number of follow-ups from last agenda, number of flags
- Path to each generated file
- **Any legacy-slug file merged and deleted** (`merged mattia.md → mattia-riva.md`), and **any identifier that needed disambiguation** — both are signals the roster or the calendar invite wording could be tidied up.
- ⚠️ **A `Linear coverage` line for every person, always printed, even when everything worked** —
  `full` / `partial` / `skipped`. For anything other than `full`, print the banner reason verbatim,
  e.g.:

  ```
  ⚠️ Linear coverage: SKIPPED for Alberto Marinelli — no Linear teams recorded in
     memory/L1/team-members.md and no email to key the query on. Agenda has no project or
     issue context. Fix: run brain-rebuild-memory (or add the Email cell) and re-run.
  ```

  **Silence is not a pass.** A run that queried nobody and a run that found nothing must not print
  the same summary. If ≥1 person came back `skipped`, end the summary with a single explicit line —
  `N of M agendas are missing Linear context` — so the omission survives being skimmed.

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

A person argument is an *identifier*, not a filename — push it through **Person resolution → canonical slug** exactly like a calendar identifier, ambiguity guard included. `/my-one-on-one alex` resolves to Alex Gibertoni and writes `alex-gibertoni.md`; `/my-one-on-one elena` matches three people and must ask which one rather than writing `elena.md`.
