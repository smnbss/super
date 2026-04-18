---
name: brain-pull-my-meeting-notes
description: >
  Harvest meeting notes, recordings, and transcripts from Google Calendar and Drive.
  Use when the user says "pull meetings", "get meeting notes", "harvest meetings",
  "sync meetings", or asks to backfill missing meeting digests. Produces daily, weekly,
  monthly, and YTD digests with decisions, action items, and brain updates.
---

# Daily Meeting Harvester

Collect all meeting artifacts from yesterday (or a date range) and organize them locally. Produce a daily digest with decisions, action items, and Brain Updates for brain-sync.

## Configuration

```
TIMEZONE: Europe/Rome
OUTPUT_DIR: src/gws/gmeet/YYYY/WNN/MM-DD
DEFAULT_RANGE: yesterday (single day)
CRON: 07:00 CET daily
```

**Exclude list** — skip meetings matching these patterns (case-insensitive):
- `^Lunch$`
- `^Out of Office`
- `^Focus Time`
- `^Birthday`

To exclude sensitive meetings (e.g., HR 1:1s), add patterns here.

---

## Step 1 — Fetch calendar events

Determine the date range. Default: yesterday. If `--since YYYY-MM-DD` is provided, process each day from that date through yesterday.

For each day, compute midnight-to-midnight boundaries in Europe/Rome timezone, converted to UTC for the API.

```bash
gws calendar events list --params '{
  "calendarId": "primary",
  "timeMin": "<START_UTC>",
  "timeMax": "<END_UTC>",
  "singleEvents": true,
  "orderBy": "startTime"
}'
```

**Filter the results (client-side):**
1. Remove events where `eventType` is `workingLocation`, `outOfOffice`, or `focusTime`
2. Remove events matching the exclude list patterns (match against `summary`)
3. Keep only events that have `conferenceData` (Google Meet link) OR `attachments` (linked docs)

Collect for each remaining event:
- `id` (calendar event ID)
- `summary` (title)
- `start.dateTime`, `end.dateTime`
- `organizer`
- `attendees[]` (name, email, responseStatus)
- `conferenceData.conferenceId` (Meet room code)
- `hangoutLink`
- `attachments[]` (fileId, title, mimeType)

## Step 2 — Discover artifacts for each meeting

For each meeting from Step 1, look for artifacts. **Only keep artifacts that match a meeting on the calendar** — silently discard anything that doesn't match. Never create `_unmatched/` folders or save unmatched files.

### 2a. Event attachments (with date validation)

If the event has `attachments[]`, these are explicitly linked docs. For each attachment with `mimeType: application/vnd.google-apps.document`, fetch the doc metadata (via `gws drive files get` with `fields: "id,name,createdTime,modifiedTime"`) and validate before accepting:

**Date guard:** Recurring events often carry stale attachments from previous occurrences. Before accepting an attached doc as notes for this meeting:
1. Check `modifiedTime` — if it was last modified **more than 7 days before** the meeting date, it is likely a stale leftover. Discard it and log: `"Skipping stale attachment <docName> (modified <date>, meeting <date>)"`.
2. After export (Step 3), scan the first 10 lines of the converted markdown for a date string (e.g. `**Date:** Feb 20, 2026` or `YYYY-MM-DD` or `Month DD, YYYY`). If a date is found and it does **not** match the meeting date (tolerance: ±1 day), discard the exported file and log: `"Discarding attachment <docName> — content date <found> does not match meeting date <expected>"`.

If the attachment passes validation, record its `fileId` as a notes source.

### 2b. Drive search for Gemini notes

Gemini notes are created in the **organizer's** Drive, not the attendee's. The doc name varies by locale:
- English: `"Meeting Title – YYYY/MM/DD HH:MM TZ – Notes by Gemini"`
- Italian: `"Meeting Title – YYYY/MM/DD HH:MM TZ – Appunti di Gemini"`
- Other locales may use other translations

Run a Drive search with shared drive support:

```bash
gws drive files list --params '{
  "q": "mimeType=\"application/vnd.google-apps.document\" and (name contains \"Notes by Gemini\" or name contains \"Appunti di Gemini\") and modifiedTime > \"<DAY_START_UTC>\" and modifiedTime < \"<DAY_END_UTC>\"",
  "fields": "files(id,name,createdTime,modifiedTime,webViewLink,owners)",
  "pageSize": 100,
  "includeItemsFromAllDrives": true,
  "supportsAllDrives": true,
  "corpora": "allDrives"
}'
```

Match results to meetings by comparing the doc name against the meeting title. Pick the doc whose name most closely matches the meeting title. If multiple matches, prefer the one whose creation time is closest to the meeting start.

**IMPORTANT:** Only keep matches to meetings from Step 1. Discard any Drive results that don't match a calendar event — do NOT save them anywhere.

### 2c. Drive search for recordings

```bash
gws drive files list --params '{
  "q": "mimeType contains \"video\" and modifiedTime > \"<DAY_START_UTC>\" and modifiedTime < \"<DAY_END_UTC>\"",
  "fields": "files(id,name,createdTime,modifiedTime,webViewLink,size)",
  "pageSize": 100,
  "includeItemsFromAllDrives": true,
  "supportsAllDrives": true,
  "corpora": "allDrives"
}'
```

Match recordings to meetings the same way (by name + time proximity). **Discard any that don't match a calendar event.**

## Step 3 — Export and convert artifacts

### Google Docs (notes, agendas)

Export as plain text via Drive:

```bash
gws drive files export --params '{"fileId": "<DOC_ID>", "mimeType": "text/plain"}' --output <path>/notes-raw.txt
```

Convert the exported text to markdown: add a `# Title` header, clean up any hard wraps, preserve the structure (Gemini notes have clean heading/bullet structure).

Save as `notes.md` in the meeting folder.

If the event has multiple document attachments (e.g., both an agenda and Gemini notes), export each one. Name the agenda `agenda.md`.

### Recordings

Do NOT download video files. Save a link file:

```markdown
# Recording: <meeting title>
- **Drive link:** <webViewLink>
- **File size:** <size in MB>
```

Save as `recording.md`.

### Transcripts (v1.1 Meet API only)

Format transcript entries as speaker-attributed markdown:

```markdown
# Transcript: <meeting title>

**Speaker Name** (HH:MM): text of what they said

**Another Speaker** (HH:MM): text of what they said
```

Save as `transcript.md`.

### Metadata

Write `metadata.json` for each meeting:

```json
{
  "eventId": "string",
  "title": "string (original calendar event title)",
  "slug": "string (folder name)",
  "date": "YYYY-MM-DD",
  "startTime": "ISO 8601 with timezone",
  "endTime": "ISO 8601 with timezone",
  "durationMinutes": 30,
  "organizer": {"name": "string", "email": "string"},
  "attendees": [{"name": "string", "email": "string", "responseStatus": "accepted|declined|tentative|needsAction"}],
  "conferenceId": "string (Meet room code)",
  "meetLink": "https://meet.google.com/...",
  "artifacts": {
    "notes": {"source": "event-attachment|drive-search|meet-api|null", "docId": "string|null", "driveLink": "string|null"},
    "transcript": {"source": "meet-api|drive-search|null", "docId": "string|null"},
    "recording": {"source": "drive-search|meet-api|null", "driveFileId": "string|null", "driveLink": "string|null"}
  }
}
```

## Step 4 — Organize into folders

**Idempotency: if the day folder already exists, delete it and recreate from scratch.**

**IMPORTANT: Only create a per-meeting folder if the meeting has at least one content artifact** (notes.md, transcript.md, recording.md, or agenda.md). Meetings with no artifacts should appear in the digest and index but NOT get their own folder. Do not create folders containing only metadata.json — this creates clutter with no value.

```
src/gws/gmeet/
  YYYY/
    WNN/                  (ISO week number, e.g. W14)
      MM-DD/
        meeting-slug/       (ONLY if artifacts exist)
          metadata.json
          notes.md          (if found)
          agenda.md          (if separate agenda doc attached)
          transcript.md      (if found)
          recording.md       (if found)
        another-meeting/    (ONLY if artifacts exist)
          metadata.json
          notes.md
        index.md             (static table of all meetings, including those without folders)
        MM-DD-digest.md      (daily digest: per-meeting summaries, decisions, actions)
      WNN-weekly-digest.md   (weekly rollup: major decisions, actions across the week)
    MM-monthly-digest.md     (monthly rollup: themes, strategic decisions, key metrics)
  YYYY-ytd-digest.md         (year-to-date: decisions tracker, action items, resolved items)
```

Compute the week number with ISO week numbering (Monday start). Example: `2026-03-31` is week 14 → `src/gws/gmeet/2026/W14/03-31/`.

**Slug convention:** lowercase, spaces to hyphens, strip special chars (`/`, `:`, `(`, `)`, `'`, `"`), collapse multiple hyphens. Example: `"Simone / Cass 1:1"` → `simone-cass-1on1`.

**Collision resolution:** if two meetings produce the same slug, append start time as `-HHMM`. Example: `sync-0900/` and `sync-1400/`.

## Step 5 — Generate index.md (static, deterministic)

This is a quick-reference table. No LLM needed, just format the data:

```markdown
# YYYY-MM-DD (Day of week) — Meeting Index

| Time | Meeting | Attendees | Artifacts |
|------|---------|-----------|-----------|
| 10:00–10:30 | Simone / Cass 1:1 | Simone, Cass | [notes](simone-cass-1on1/notes.md) |
| 11:00–12:00 | All Hands | 12 attendees | [notes](all-hands/notes.md), [recording](all-hands/recording.md) |

**Total:** N meetings, Xh Ym total meeting time
**Artifacts found:** N notes, M recordings, K transcripts
```

## Step 6 — Generate daily digest (LLM synthesis, per-meeting then rollup)

This is a two-pass synthesis. The agent (you, Claude) reads the artifacts and produces the digest.

### Pass 1: Per-meeting summary

For each meeting that has notes or transcript, read the artifact and produce a structured summary:
- **Key decisions** made in the meeting
- **Action items** with owner (@ mention)
- **Key points** (3-5 bullets of what was discussed)

If a meeting has no artifacts (just metadata), include it in the digest with: "No Gemini notes or transcript available."

### Pass 2: Daily rollup

Aggregate all per-meeting summaries into the daily digest:

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
- [ ] @roberto: action from meeting 5

## Brain Updates
- L2/teams.md: UPDATE <team changes discussed today>
```

**Brain Updates rules:**
- Only include updates when a meeting produced a clear, actionable decision that changes the state of the world
- Use the format: `- L2/<file>.md: <ACTION> <description>`
- Actions: `ADD` (new fact), `UPDATE` (refresh existing), `REMOVE` (mark superseded)
- Map decisions to the right L2 file based on topic (releases, teams, data, product areas, etc.)
- If no meetings produced L2-worthy decisions, omit the Brain Updates section entirely

**Linear project links:**
- If meeting notes or transcripts mention specific Linear projects, resolve each project's URL via `get_project` or `list_projects`.
- Format the project name as a markdown link: `[Project Name](url)` in the digest output (meeting summaries, Brain Updates, and action items).

Save as `src/gws/gmeet/YYYY/WNN/MM-DD/MM-DD-digest.md`.

## Step 7 — Generate weekly digest

After all days in the week are processed, generate a weekly rollup at the week level.

Read all daily digests for the week and produce:

```markdown
# Weekly Meeting Digest: YYYY WNN

## Week Summary
- N meetings across M days
- Xh Ym total meeting time
- N had notes, M had recordings

## Major Decisions This Week
- [Mon] Decision from meeting X
- [Tue] Decision from meeting Y
- [Wed] Decision from meeting Z

## Key Action Items
- [ ] @person: action (from Meeting Name, Day)
- [ ] @person: action (from Meeting Name, Day)

## Daily Breakdown

### Monday MM-DD
- Meeting 1: key point
- Meeting 2: key point
[Full digest](MM-DD/MM-DD-digest.md)

### Tuesday MM-DD
...

## Brain Updates
- L2/file.md: ACTION description (aggregated from daily digests)
```

Save as `src/gws/gmeet/YYYY/WNN/WNN-weekly-digest.md`.

The weekly digest aggregates and deduplicates Brain Updates from the daily digests. If multiple daily digests update the same L2 file, combine them into one update with the latest state.

## Step 8 — Generate monthly digest

After all weeks in the month are processed, generate a monthly rollup at the year level.

Read all weekly digests for the month and produce:

```markdown
# Monthly Meeting Digest: YYYY-MM (Month Name)

## Month at a Glance
- N meetings across M days
- Xh total meeting time
- N had notes, M had recordings

## Strategic Decisions
Highlight the 5-10 most important decisions made this month. These are decisions that
change direction, launch initiatives, or commit resources. Group by theme, not by date.

### Theme 1: [e.g., US Launch Preparation]
- Decision A (Week WNN)
- Decision B (Week WNN)

### Theme 2: [e.g., AI/ML Initiatives]
- Decision C (Week WNN)

## Key Action Items (Still Open)
Only include action items that are strategic or cross-team. Skip small/tactical items.
- [ ] @person: action (from WNN)

## Week-by-Week Summary

### WNN (MM-DD to MM-DD)
2-3 sentence summary of the week's focus.
[Full weekly digest](WNN/WNN-weekly-digest.md)

### WNN+1
...

## Themes & Patterns
What recurring topics dominated meetings this month? What shifted from last month?
2-3 paragraphs of high-level synthesis.

## Brain Updates
- L2/file.md: ACTION description (aggregated from weekly digests, deduplicated)
```

Save as `src/gws/gmeet/YYYY/MM-monthly-digest.md`.

The monthly digest is the executive summary. It should be readable in 2 minutes and
capture what someone who missed the entire month needs to know.

## Step 9 — Generate year-to-date digest

After monthly digests are complete, update the YTD digest. This is a living document
that tracks the full year's trajectory.

Read all monthly digests and the previous YTD digest (if it exists). Produce:

```markdown
# Year-to-Date Meeting Digest: YYYY

## YTD Stats
- N meetings across M months
- N had notes, M had recordings

## Decision Tracker

Track every strategic decision made in meetings this year. Group by status:

### Active Decisions (still in effect)
| Decision | Made | Week | Status |
|----------|------|------|--------|
| Google Login as primary auth | Jan | W02 | Active |
| Flights is #1 conversion priority | Feb | W06 | Active |

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
One paragraph per month describing the narrative arc: what the focus was,
what shifted, what carried forward.

## Emerging Themes
Threads that span multiple months. What's accelerating? What stalled?
```

Save as `src/gws/gmeet/YYYY/YYYY-ytd-digest.md`.

The YTD digest is cumulative. Each run should preserve and update the decision tracker
and action item tracker from prior runs, marking items as resolved when later meetings
show they were completed, and superseded when direction changed.

## Step 10 — Report results

Print a summary to the user:
- How many meetings processed
- How many artifacts found (notes, recordings, transcripts)
- Path to the digest file
- Any errors or skipped meetings (with reason)

---

## Error handling

- **Meet API 403** → fall back to Drive-based discovery (2a-2c). Log: "Meet API scope not available, using Drive fallback."
- **Drive export fails** (permission, deleted doc) → log warning, skip that artifact, continue with other meetings
- **No artifacts found for a meeting** → do NOT create a folder. Include the meeting in the daily digest and index (noted as "no artifacts") but skip folder creation. Only create a per-meeting folder (with metadata.json + content files) when at least one content file (notes.md, transcript.md, recording.md, or agenda.md) will be written.
- **Empty Google Doc** → skip notes.md for that meeting
- **API rate limit (429)** → exponential backoff, max 3 retries starting at 1s
- **API server error (5xx)** → retry once after 2s, then skip and log

## Running

**Yesterday only (default):**
```
/my-meetings
```

**Date range (backfill):**
```
/my-meetings --since 2026-03-30
```
This processes each day from March 30 through yesterday, producing separate folders and digests per day.

**Single specific day:**
```
/my-meetings 2026-04-01
```
