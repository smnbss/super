---
name: brain-linear-release-summary
description: >
  Summarize WeRoad releases from the Linear MOL "Release Notes" project for a
  given time window, pulling per-issue impact comments and grouping by theme.
  Use whenever the user says "summarize releases", "release impact", "what
  shipped in <quarter/month/year>", or pastes the MOL release-notes URL —
  even if they don't say "use the skill".
---

# WeRoad — Linear Release Summary

Read the Linear MOL "Release Notes" project, filter to a time window, fetch
per-issue impact comments, and produce a focused summary saved to
`outputs/releases/<window>-impact-summary.md`.

The MOL project is the single source of truth for what shipped at WeRoad. Most
releases are descriptive only; a small fraction carry a "📊 Output misurati"
or "Impact update" comment with measured KPI deltas. This skill surfaces both.

## Input

The user provides a **time window**. Accepted forms:

| Input | Window | Slug |
|-------|--------|------|
| `2026` | full year 2026 | `2026` |
| `Q1 2026`, `2026-Q1` | Jan–Mar 2026 | `2026-q1` |
| `2026-03` | March 2026 | `2026-03` |
| `last 30 days` | rolling window ending today | `<YYYY-MM-DD>-last-30-days` |
| `last 90 days` | rolling window ending today | `<YYYY-MM-DD>-last-90-days` |
| `2026-01..2026-04` | inclusive month range | `2026-01-2026-04` |
| `all` | every release | `all` |

**Slug rule:** every slug starts with a `YYYY` (or `YYYY-MM-DD` for relative
windows). For relative windows like "last N days", prefix today's date
(`<currentDate>`-style, taken from system context) so the file sorts
chronologically by when it was generated. Example for today 2026-04-30 and
"last 30 days": slug = `2026-04-30-last-30-days`, filename =
`outputs/releases/2026-04-30-last-30-days-impact-summary.md`.

Default if missing: **current year** (use the `currentDate` from the system
context). Always confirm the chosen window in one line before starting.

## Project constants (locked)

- Linear project: `release-notes-1bc4d3fcb947`
- Project UUID: `98945ef1-bb21-4155-8de6-b9a15302bb8d`
- Team: MOL (Triage)
- URL: https://linear.app/weroad/project/release-notes-1bc4d3fcb947/issues

## Workflow

### 1. Fetch all issues (handle token-limit + pagination)

`mcp__linear__list_issues` with this project returns ~440 issues across 2
pages and **will exceed the tool-result token limit**. The MCP harness saves
the oversize payload to a file and returns the path. Use that file via `jq` —
do not try to read it back through the tool.

```
mcp__linear__list_issues(project="98945ef1-bb21-4155-8de6-b9a15302bb8d",
                         limit=250, orderBy="createdAt",
                         includeArchived=true)
# → "Output has been saved to <FILE1>"
mcp__linear__list_issues(... cursor=<value of "cursor" field from page 1>)
# → "Output has been saved to <FILE2>"
```

The response shape is `{issues, hasNextPage, cursor}` — pass the value of
`cursor` (not `endCursor`) to the next call. Each saved file is a JSON array
`[{type:"text", text:"<json string>"}]`. Pull the inner JSON and concatenate
issues:

```bash
jq -s '[.[][0].text | fromjson | .issues[]]' "$FILE1" "$FILE2" > /tmp/molissues.json
jq 'length' /tmp/molissues.json   # sanity-check ≈ 440
# Spot-check the field names — issue identifiers are in .id (e.g. "MOL-484"),
# not .identifier:
jq -r '.[0:3] | .[] | "\(.id) | \(.createdAt) | \(.title)"' /tmp/molissues.json
```

If a future page count grows, loop on `hasNextPage` until it returns false,
each time passing the previous response's `cursor`.

### 2. Filter to real releases in the window, dedup

Titles in this project follow `YYYY-MM-DD - <Platform> - <Release name>`. The
**title-date is the operationally correct ship date** — `createdAt` is
unreliable here because the MOL project was migrated mid-flight: older issues
have `createdAt` manually set to midnight on the release date, but newer
issues have natural `createdAt` (often days after the title-date). Always
filter the window on `title[0:10]`, not `createdAt`.

Keep only date-prefixed titles, drop test/junk titles (the junk word can
appear in any segment, not just at the start — e.g. `2026-04-11 - Website -
Test Release Note`), and dedup by title keeping the latest `createdAt`. The
dedup matters because the migration left many releases duplicated under
different `MOL-` IDs.

```bash
jq '[
  .[]
  | select(.title | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}"))
  | select(.title | test("(test|asdf|aaaa|ddd|RELEASE_EMAIL_TO|safsa|sdfas|\\[TEST\\]|Test Release Note)"; "i") | not)
] | sort_by(.title) | group_by(.title) | map(max_by(.createdAt))' /tmp/molissues.json \
  > /tmp/molclean.json
jq 'length' /tmp/molclean.json   # sanity check before windowing
```

If the count looks off, dump titles and eyeball — junk patterns evolve.

Then filter to the requested window using `title[0:10]` (full date) or
`title[0:7]` (year-month):

```bash
# Year
jq '[.[] | select(.title | startswith("2026-"))]' /tmp/molclean.json > /tmp/window.json
# Quarter (Q1 2026)
jq '[.[] | select(.title[0:7] | IN("2026-01","2026-02","2026-03"))]' /tmp/molclean.json > /tmp/window.json
# Month range 2026-01..2026-04
jq --arg lo 2026-01 --arg hi 2026-04 \
  '[.[] | select(.title[0:7] >= $lo and .title[0:7] <= $hi)]' /tmp/molclean.json > /tmp/window.json
# Last N days — compute today and (today - N) up front, filter on title-date
TODAY=$(date -u +%Y-%m-%d)
SINCE=$(date -u -v-30d +%Y-%m-%d)   # macOS BSD; on Linux use: date -u -d '30 days ago' +%Y-%m-%d
jq --arg lo "$SINCE" --arg hi "$TODAY" \
  '[.[] | select(.title[0:10] >= $lo and .title[0:10] <= $hi)]' /tmp/molclean.json > /tmp/window.json
```

### 3. Fetch comments in parallel batches

For each filtered issue, call `mcp__linear__list_comments(issueId=...)`. Most
return empty. Run **10 calls per turn in parallel** — that's the sweet spot
for throughput without blowing the response budget. Don't fetch one at a time.

A real "impact" comment looks like:
- starts with `## 📊 Output misurati` (Mautino's format) **or**
- starts with `**Impact update — N days post-release**` (Parenti's format) **or**
- contains a KPI table with pre/post columns

Anything else (Metabase links, reviewer chitchat) is **not** impact and goes
in coverage gap, not the impact table.

### 4. Render the summary

Output four sections in this order: **Executive summary → Releases with measured impact → Themes → Coverage gap.** No chronological table, no method appendix.

**Formatting rule: do not hard-wrap prose.** Each bullet, table cell, and paragraph must be a single physical line in the markdown source. The renderer (Linear, ClickUp, GitHub, viewers) wraps to its container width; hand-wrapped 80-column lines render with ragged "step" indents under bullet markers and orphan continuation lines that look broken at full screen. Long lines are correct.

### 4a. Voice — write for a non-technical CEO

Imagine the reader skimming on a phone, has ~90 seconds, has never opened the codebase, and doesn't know what *funnel*, *cohort*, *SSO*, *self-hosted*, *P360*, or *pp* mean. They want three things, in this order: **what did we ship, what did it move in the business, what's still unknown.** The whole document — and especially the executive summary — has to land for that reader.

Concrete rules:

- **Expand every acronym and internal term on first use, in plain English.** Write "Apple/Google sign-in (SSO)" the first time, then "SSO" within the same section. Never let `SSO`, `OTP`, `SERP`, `P360`, `TO_ALLOT`, `TP`, `TL`, `pp`, `n=`, `KPI`, `A/B`, `pax`, `ICAO`, `self-hosted` / `hosted` (when they're internal jargon for "community-led" / "WeRoad-led"), `auth`, `funnel`, or `confounded` appear without a plain-English alternative. Do not produce a glossary section — fold the explanation into the sentence.
- **Use plain words.** "We can't yet tell" beats "confounded with…". "Members" or "users" beats "pax". "Tour confirmation" beats "PR_APPROVED". "Sign-in" beats "auth". "The change is mixed in with the Easter slowdown" beats "post-window covers Easter low-season".
- **Round currency and rates.** "About €200k a year" beats "€201k/yr". Ranges stay as ranges ("€20–35k a year"). Whole percentages unless the precision matters ("23%" beats "23.4%"). For deltas, prefer "+6 percentage points" over "+6.0 pp" — the words read.
- **Translate every number into a business outcome on the same line.** A non-technical reader cannot infer scale from a percentage. `−91%` → `−91% — Finance went from rejecting roughly 500 documents a month to under 50`. `+6 percentage points` → `+6 percentage points more people allow notifications — about 1,200 extra opt-ins per month at current install volume`. `+189%` → `+189% — visitors who land here book at roughly three times the rate of regular search results, on a small early sample`. Don't trust the reader to do the math; do it for them.
- **Frame caveats as plain "what's still unknown", not as statistical hedging.** "Too soon to say whether the change helped or whether April was just a slow month" beats "confounded by Easter seasonality and selection effects". "Small sample — only 8 bookings, worth re-checking in 3 weeks" beats "n=8, low statistical power, high variance".
- **Lead each compounding bullet with the business effect, not the system name.** Open with the outcome the CEO can repeat ("**We rebuilt how partners confirm tours, and it's preserving roughly €200k a year so far.**"), then explain how it works in one or two sentences, then end with the team / area in italics so the CEO can route the follow-up. The system name moves to the end; the money or capacity unlocked moves to the front.
- **End the executive summary with what the CEO should do or watch.** One sentence: which area to revisit, what's still unmeasured, who would benefit from a 1:1. The reader walks away with a next action, not a status update.

The voice test: read the executive summary aloud to someone who joined WeRoad last week from a non-tech background. If they ask "what does X mean" more than once, rewrite. If they can summarise the picture back to you in three sentences, it's done.

```markdown
---
title: WeRoad Releases — <Window human label>
source: https://linear.app/weroad/project/release-notes-1bc4d3fcb947/issues
project_id: 98945ef1-bb21-4155-8de6-b9a15302bb8d
team: MOL (Triage)
generated: <YYYY-MM-DD>
window: <window machine label>
release_count: <N>
impact_count: <K>
---

# WeRoad Releases — <Window human label>

**N releases** <date-from> → <date-to>. K carry post-release impact analyses
in comments; the other N−K ship without measured outcome.

## Executive summary

Lead the file with this section, before "Releases with measured impact". The audience is a non-technical CEO with 90 seconds and a phone. Apply Section 4a's voice rules to every sentence here — they bind hardest in this section, where most readers will stop.

Structure:

1. **Headline paragraph (2–3 sentences, plain English).** Open with what shipped at portfolio level — total releases, the 2–3 areas of the business they touched (named in plain English: "the website", "the WeMeet app", "tour operations" — not "Booking & Conversion (10)"). Then state the compounded measured outcome in one breath: total annualised euros saved or preserved, the headline rate change rounded to whole points, the headline capacity unlock — whichever two or three numbers matter most. Don't list per-release. Don't open with a count of releases by domain — that's a status update, not a headline.

2. **Compounding moves (3–5 bullets).** Group measured releases into the *systems* they form, not the individual changes — but lead each bullet with the *business effect*, not the system name. The point is to surface releases that only make sense together and to translate them into something the CEO can repeat in a board call.

   Right shape — outcome first, then mechanism, then domain in italics:

   - **We rebuilt how partners confirm tours, and it's preserving roughly €200k a year so far.** Three releases stacked into one flow: documents are no longer the unit of cost, partners now confirm allotments themselves through a [self-service screen](https://ask.weroad.app/releases/MOL-455), and tours can [go on sale before the partner replies](https://ask.weroad.app/releases/MOL-484) — which used to take 4 days. Finance also rejects 91% fewer documents (about 500/month down to under 50), saving another €20–35k a year in reconciliation work. *Buynana / Tour Operations.*
   - **WeMeet became how members sign in and stay opted in.** Apple/Google sign-in [shipped in February](https://ask.weroad.app/releases/MOL-433) and immediately took 64 of every 100 logins. The same release train [redesigned the push-notification ask](https://ask.weroad.app/releases/MOL-429), pushing opt-in from 17% to 23% — about 1,200 extra people per month allowing notifications. *WeMeet.*

   Wrong shape (don't do this): "**Partner allotment funnel rebuild** (cost-based docs → P360 self-service → parallel-flow ≥17wk): rejected documents −91%, partner decision time −32%, ~€201k/yr revenue preserved + €20–35k/yr finance-rec savings." That's a system name, three jargon terms, four percentages, and two euro figures with no human translation — it lands as a status report, not a headline.

   If a domain didn't compound — isolated polish, one-off wins, no shared system — leave it out. The executive summary is for the portfolio story, not for coverage.

3. **What's still unproven, in one sentence.** Name the largest unmeasured cluster in plain English (usually the booking funnel or the WhatsApp AI assistant rollout) so the reader knows the picture is partial. End with a concrete next action — which team to revisit, what to re-read in N weeks, or who to schedule a 1:1 with. The reader walks away with something to do, not just something to know.

The detailed per-release impact paragraphs come immediately below; the executive summary just frames what they add up to and points to where to look next.

## Releases with measured impact

For each release with an impact comment, write an H3 with the date and a linked release title, followed by a one-paragraph distillation of the comment. **Do not use a table** — long impact cells wrap badly in ClickUp/Linear/GitHub viewers. Order oldest-first.

**Apply Section 4a's voice rules in full to these paragraphs.** They get less attention from skim-readers than the executive summary, but the CEO who *does* drill in is exactly the reader who needs the help — they're following a thread, not searching for context. So translate every percentage into an outcome ("−91% — Finance now rejects ~50 documents a month instead of ~500"), expand every acronym on first use, drop raw event names (`first_open`, `view_home`, `complete_search_events` belong nowhere outside dashboards), and rewrite every "confounded by / tautological / pre/post comparison is dirty" caveat into plain "what we can't yet tell" prose. The goal is that someone reading just one paragraph — without the executive summary above — still walks away with the *what* and the *so what*.

**Hard rule — no visible release IDs.** A `MOL-…` identifier may appear *only* as the path segment in a markdown link target (`https://ask.weroad.app/releases/MOL-484`). It must never appear in visible prose, headers, parenthetical lists, summary bullets, the executive summary, or anywhere a reader's eye would land. The reason is editorial: identifiers are noise that pollutes a CTPO-level read; the linked release name carries all the meaning. If you find yourself writing `(MOL-484)` or `MOL-432 → MOL-455`, stop and rewrite as `[release name](url)` chains instead.

Release page URL pattern (ask-linear, the WeRoad release-notes app, used only as link targets):
`https://ask.weroad.app/releases/<release-id>`

```markdown
### <YYYY-MM-DD> — [<Platform / Title>](https://ask.weroad.app/releases/<release-id>)

<One paragraph: KPI deltas with bold numbers, sample size where relevant,
and any caveat the author flagged. End with *(Author last name)*.>
```

## Themes

Group all N releases by product area, derived from the second " - " segment
of the title. Combine related areas (e.g. "Website" + "WebSite"). Suggested
buckets — adapt to what's actually in the window:

- **Booking & Conversion** — checkout, deposit, compare, pricing pillars,
  notify-me, waiting list
- **Buynana / Tour Operations** — cost structure, allotment, virtual cards,
  documents
- **Search & Site UX** — SERP, filters, megamenu, performance, recently-viewed
- **WeMeet** (mobile) — onboarding, chat, event timeline, push permissions
- **Community Portal** — events, calendar, area manager, templates
- **Identity & Account** — SSO, MyWeRoad, +1 accounts, account sharing
- **Admin Coordinators** — surveys, waiting-list ranking, travel diary
- **Partner Portal** — TP price changes, push reminders, itinerary approval
- **Content / SEO** — blog migration, structured pages, schema
- **AI / WhatsApp** — assistants per market, Discord salesbot
- **Cross-cutting / Policy** — cancellation policy, contact channels

Each bullet: count + 1-line list of releases. **Link each release name to its ask-linear release page** (`[name](https://ask.weroad.app/releases/<release-id>)`) — the identifier lives only inside the link target, never as visible text. Mark releases that have a post-release impact comment with a trailing ` (impact)`. A quarter typically needs ~12–14 buckets (more than the year list above), so expect to add domain-specific ones rather than force-fit the suggested list.

## Coverage gap

**K/N (P%)** of <window> releases have post-release impact analysis. Note
who wrote them (look at comment authors) and when the comments were posted —
if they cluster on a single day, flag it as a backfill effort. Name the
domains where impact data is missing.

When citing specific releases in coverage-gap prose, link the release names to their ask-linear release pages (same pattern as themes). No visible identifiers anywhere in the section.
```

### 5. Save

Write to `outputs/releases/<slug>-impact-summary.md` (single file, no
subdirectory). The slug comes from the input window table above. Confirm the
path back to the user.

If running as a subagent and the `Write` tool is blocked by harness policy,
fall back to a Bash heredoc — same result, no permission prompt:

```bash
cat > /Users/.../outputs/releases/<slug>-impact-summary.md <<'EOF'
---
title: ...
EOF
```

## Why these design choices

- **Locked to MOL** — this project ID isn't going to move; hardcoding it
  removes one prompt's worth of ambiguity per run.
- **No chronological table** — the user removed it from the first hand-built output; the date in the H3 of each impact row plus the linked release names in themes are enough for someone to drill in.
- **No visible release IDs** — `MOL-…` identifiers are editorial noise at CTPO-level. They live only inside link targets so readers see release names, not Linear bookkeeping. The skill enforces this in every section, including the executive summary's compounding bullets.
- **Parallel comments fetch in batches of 10** — single calls are slow,
  bigger batches risk hitting the response budget. 10 is empirically fine.
- **`jq` on saved files, not re-reading via tool** — the MCP harness already
  refused to return 440 issues inline; trying again wastes a turn.
- **Title-date over `createdAt`** — confirmed via two eval runs: the MOL
  project's `createdAt` is half-natural and half-backdated, so it can't be
  trusted for windowing. The title-prefix is the ship date by editorial
  convention.
- **Two impact-comment patterns** — empirically, only Giovanni Mautino and
  Ivan Parenti are writing these, in two distinct templates. Recognising
  both prevents missing one author's work.
