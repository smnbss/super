# \<TEAM\> Deep Dive — W\<NN\> · \<Day, Mon DD, HH:MM\> Europe/Rome
<!-- deep-dive-agenda: v1 | team: <slug> | linear: <TEAM-KEY[, TEAM-KEY]> | generated: YYYY-MM-DD HH:MM | freshness: LIVE -->

> **This file is the standard.** Every agenda in `outputs/agents/my-deep-dives/` follows it.
> It ships **with** its generator — `brain-prepare-my-deep-dives/reference.md`, beside the `SKILL.md`
> that reads it (→ Step 3) and the publisher that renders it (→ Step 4). Patch the skill, not the
> output — a hand-edited agenda is overwritten by the next morning-start run.

---

## The standard in one screen

**Section order is fixed.** Every agenda has exactly these sections, in this order. A section with
nothing in it stays, with `_none_` under it — an absent section reads as "nothing to report", which
is not the same thing.

| # | Section | Purpose |
|---|---|---|
| 0 | Title + metadata comment | Team, week, slot, when it was built, how fresh |
| 1 | Links + In the room | Meet / ODG / Roadmap / OKRs / Deck, and who actually accepted |
| 2 | `## 🚦 Health` | The 5-second scan: RAG counts + a one-line verdict |
| 3 | `## ⭐ Top 5 talking points` | Max 5, ordered by what to say first. Each ends in an ask |
| 4 | `## 📋 Projects by status` | Every active project, in RAG buckets, one table per bucket |
| 4b | `## ⏱ Due before the next deep dive` | *Optional.* Dated items — usually **issues**, not projects — landing before the next session |
| 5 | `## 👥 Ownership & load` | Lead concentration, unowned projects, capacity |
| 6 | `## 📝 Your topics` | Always present, always empty — Simone fills it in |
| 7 | `## 🗒️ Notes & caveats` | Scope notes, data-quality warnings, what this agenda can't see |

### RAG rules — mechanical, not vibes

| ● | Bucket | Assign when |
|---|---|---|
| 🔴 | **Overdue / blocked** | `targetDate` is in the past · or Urgent and not started · or **silent 60+ days** · or a hard external/commercial commitment with nothing tracked · or a named blocker / live production risk |
| 🟠 | **At risk / stale** | **Silent 14–59 days** · or target within 14 days and not started · or target has slipped · or In Progress with no target |
| 🟢 | **On track** | In Progress, status update within 14 days, target still ahead |
| 🔵 | **Planned / new** | Planned, or created in the last 14 days, nothing due yet. Informational — not a health state |
| ⚪ | **Dormant / unowned** | Backlog with no movement · no lead **and** no movement · **explicit archive/close candidate** |
| ⏸ | **Paused** | Linear status is `Paused`. **Always its own bucket**, whatever the target date or staleness |
| ✅ | **Shipped since last dive** | Completed or Cancelled since the previous agenda. Always show it — the credit side of the ledger |

A project appears in **exactly one** bucket — the worst one that applies, precedence
🔴 → 🟠 → 🟢 → 🔵 → ⚪ — with **two overrides that beat everything:**

1. **Linear status `Paused` → ⏸, always.** Paused is a decision someone took, not a health state.
   Reporting it as overdue punishes a team for a deliberate stop and buries the only question worth
   asking: *is it still deliberate?* Print its overdue days and staleness in the row regardless.
2. **Never started (no work ever recorded) → ⚪, however overdue.** That's inventory, not delivery
   risk, and a red list padded with zombies stops being read. Still print its overdue days.

A project that started and then stalled stays 🔴/🟠 — it is a real risk, even when the ask is
"kill it".

### The project table — same eight columns everywhere

```markdown
| ● | Project | Teams | Status | What's up | Owner | Target | Progress |
|---|---|---|---|---|---|---|---|
| 🔴 | [Product page 3.0](https://linear.app/weroad/project/…) | `TIUM` `DES` | In Progress | Last update Jul 28, which itself pushed the target. Diana back Aug 12 — new date? | Matteo Diana | **Aug 17** `3d late` | `████░░░░░░` 40% |
```

- **●** — the RAG chip. Same emoji as the bucket heading.
- **Project** — always a markdown link to Linear.
- **Teams** — **every Linear team on the project**, as code-span keys, **this dive's team first**,
  from `list_projects` `fields: ["teams"]`. Never abbreviate to "cross-team" — name them. A single
  key means the project is wholly this team's. Guild rows (`BEG`, `FEG`, `GUI`, `STF`) count as
  teams; list them too.
- **Status** — Linear's own **`status.name`**, verbatim and unedited: `In Progress` · `Planned` ·
  `Backlog` · `Paused` · `Completed` · `Cancelled`. **This is the board's claim, the RAG chip is
  yours** — and the gap between them is often the finding. Bold it when it contradicts the evidence
  (**`Backlog`** on a project with an Aug 17 status update, **`Planned`** on one whose design
  milestone reads 100%). Append `· Urgent` / `· High` only when priority is part of the story.
  ⚠️ **Verify it against `status.name`, never against the GraphQL `state` field.** `state` returns the
  *bucket* (`backlog`/`planned`/`started`/`completed`/`canceled`), so the custom statuses **`Paused`
  reads as `backlog`** and **`Discovery` as `planned`** — comparing buckets reports drift that isn't
  there and hides drift that is. ⚠️ **And re-verify at publish time, not only at build time:** on
  2026-08-20 five status cells drifted between the 09:30 build and the 12:00 publish, including a
  project written up as the board's **only Urgent item** that had been **cancelled outright** in
  between.
- **What's up** — the latest reported state *and* the ask, in one cell. Not a description of what
  the project is; the reader knows. Lead with the date of the last status update.
- **Owner** — Linear `lead.name`, or **`— no lead`** in bold. Never a bare dash.
- **Target** — `Mon DD`. Bold it when it's inside 14 days or past. Append `` `Nd late` `` when
  overdue, `` `Nd` `` when due soon, `— none` when there is no target.
- **Progress** — 10-cell bar + a figure. `— never reported` when no status update has ever been
  written. **Say which measure you used** in Notes & caveats. ⚠️⚠️ **If the project has milestones,
  MILESTONES ARE THE MEASURE — see the rule below. A project-wide issue percentage on a
  milestoned project is not a weaker number, it is a wrong one.**

Bar: `██████████` = 100%, one cell per 10%. Round to nearest cell.
`░░░░░░░░░░` 0% · `███░░░░░░░` 30% · `███████░░░` 70% · `██████████` 100%

**Column widths are pinned per table shape, so every register table on the page lines up.** The
publisher classifies each table by its header signature and emits a `<colgroup>` with
`table-layout: fixed`:

| Shape | Header | Widths |
|---|---|---|
| `t-reg8` | `● \| Project \| Teams \| Status \| What's up \| Owner \| Target \| Progress` | 34px · 15% · 10% · 9% · 30% · 8% · 8% · 20% |
| `t-health` | `● \| Bucket \| # \| Signal` | 34px · 22% · 6% · 72% |
| `t-due4` | `Item \| Owner \| Due \| Status` | 46% · 18% · 14% · 22% |

**Without this each `<table>` is laid out independently and the columns drift between buckets** — a
`Teams` cell holding six keys in the amber table pushes every later column out of line with the red
one above it. One-off content tables (a PR stack, a repo comparison) stay auto-layout on purpose:
aligning across tables means aligning tables *of the same kind*. **Keep the last column wide** — a
milestone-aware Progress cell is a sentence, not a number.

### ⚠️⚠️ Milestones override issue counts — the measure that was silently wrong

**Every progress measure has a denominator, and each one is blind to something different.**

| Measure | Blind to | Failure direction |
|---|---|---|
| issues closed ÷ issues existing | **scope nobody has written tickets for** | **over-reports — reads 100% when half the project doesn't exist yet** |
| milestone roll-up | **issues assigned to no milestone** | under-reports, and hides loose work |
| reported status-update % | everything the author didn't mention | arbitrary |

**So:**

1. **If a project has milestones, report milestones.** `N of M milestones` + the current milestone's
   own percentage. **Never a project-wide issue percentage** — its denominator excludes unwritten
   scope, so it is not a rough number, it is a wrong one.
2. **A milestone with ZERO issues is a named state: `scope not written`.** It is categorically
   different from "0% with issues open". Say which one it is; never render either as progress.
3. **"100%" and "close it" require EVERY milestone at 100% AND no milestone without issues.** Never
   derive a close recommendation from an issue count.
4. **A project whose *current* milestone is unwritten, with a past target, is 🔴** — however complete
   the earlier milestones are.
5. **Also report issues that belong to no milestone.** If a project has milestones *and* a pile of
   unassigned issues, the milestone model is incomplete and both numbers must appear.

**Detection is one call for the whole workspace** — Linear's GraphQL, `projects { projectMilestones
{ name progress } }`, paginated. The MCP `list_projects fields:["milestones"]` also works but returns
full milestone descriptions and is enormous.

> **What this caught on 2026-08-20.** *Digest email — what's new on your departures* showed
> **`100% (24 issues)` and a "CLOSE IT" recommendation in a talking point.** All 24 issues were in
> **M1**, shipped Aug 4. **M2 "Digest Email" was at 0% with no issues written**, its scope had been
> **reversed back to the full daily digest on Aug 19**, and the project was **restarted that
> morning.** Closing it in the meeting would have killed a half-built project. **16 of 84 milestoned
> rows were wrong the same way**, and two of them carried close recommendations.

### Rules that keep these honest

- **Never invent a field.** No owner recorded → `— no lead`. No target → `— none`. No status
  update ever → `— never reported`. A plausible guess in a table reads as measurement.
- **Date every claim of progress.** "Aug 19: QA done" beats "QA is done".
- **`updatedAt` is not a status update.** A field edit moves the timestamp and reports nothing.
  If you say a project is active, say which status update said so and when.
- **Every project link is a real Linear URL.** No bare project names in the register.
- **Counts in headings are live counts**, re-measured each run — never carried forward.
- ⚠️⚠️ **Wide cross-team programmes are filtered, not listed — and the filter has three parts that
  are all easy to get wrong.** A project spanning **more than two teams** appears in this agenda
  **only if this team has work in it.** Projects on **one or two** teams are always listed.

  1. **PAGINATE THE ISSUE QUERY.** `list_issues` caps at 250 and returns `hasNextPage: true` without
     saying what you missed. **Bugs Triage has 355 issues** — a single page reads as "STOMP has open
     work" when STOMP's 3 issues are all closed. Use `wr-linear issues list --project "<name>" --all`
     (needs the brain's `LINEAR_API_KEY`: `set -a && source .env.local && set +a`), which
     auto-paginates, and count by `state.type` not by `status` name.
  2. **THE TEST DIFFERS BY BUCKET.** For 🔴/🟠/🟢/🔵/⚪/⏸ the test is **open issues > 0** (`state.type`
     not `completed`/`canceled`). For **✅ Shipped the test is *any* issue ever > 0** — a completed
     project has zero open issues *by definition*, so the open-issue test would delete the entire
     credit ledger. A team that contributed even one closed issue keeps the credit; a team with zero
     issues never delivered it.
  3. **NEVER RETRO-APPLY IT TO AN `ARCHIVED` AGENDA.** Today's open/closed counts describe today. An
     April agenda that called something "on track" was right at the time; measuring it now says only
     that the work later finished. Leave archived registers as they were and say so in Notes.

  **Zero → remove the row entirely** (do not grey it out) and record it in Notes & caveats with the
  **evidence**: the team's open/ever counts, or "the project has no issues at all". A ten-team
  standards programme on every board is how a deep dive loses half its time to work the room does not
  own — and it hides real findings: measured 2026-08-20, **TIUM's 28 issues on Hightouch were all
  closed** while the agenda still called it a red 51-days-overdue item, and **GED's three "on track"
  projects had no Design issue at all.**
- **`list_projects` pages at 50 and truncates silently.** Paginate on `cursor` before counting.
- **Archived agendas keep their as-of date.** Set `freshness: ARCHIVED` in the metadata comment and
  add the stale banner; do not re-measure a past meeting against today's Linear.

---

## Skeleton — copy from here down

```markdown
# <TEAM> Deep Dive — W<NN> · <Day, Mon DD, HH:MM> Europe/Rome
<!-- deep-dive-agenda: v1 | team: <slug> | linear: <KEYS> | generated: YYYY-MM-DD HH:MM | freshness: LIVE -->

**Board:** [<KEY>](https://linear.app/weroad/team/<KEY>/projects/all) · **ODG:** <url> · **Roadmap:** <url> · **OKRs:** <url> · **Deck:** <url> · **Meet:** <url>

**In the room** — ✅ <accepted> · ⏳ <no reply> · ❌ <declined>

## 🚦 Health

| ● | Bucket | # | Signal |
|---|---|---:|---|
| 🔴 | Overdue / blocked | 0 | <what makes it red> |
| 🟠 | At risk / stale | 0 | <what makes it amber> |
| 🟢 | On track | 0 | <what's genuinely moving> |
| 🔵 | Planned / new | 0 | <what just landed on the board> |
| ⚪ | Dormant / unowned | 0 | <archive candidates> |
| ⏸ | Paused | 0 | <deliberately stopped — still deliberate?> |
| ✅ | Shipped since last dive | 0 | <the credit side> |

**Verdict:** <one sentence a CTO can act on>

## ⭐ Top 5 talking points

1. **<Headline>** — <evidence, dated>. → **<the ask>**
2. …

## 📋 Projects by status

### 🔴 Overdue / blocked (n)

| ● | Project | Teams | Status | What's up | Owner | Target | Progress |
|---|---|---|---|---|---|---|---|

### 🟠 At risk / stale (n)
### 🟢 On track (n)
### 🔵 Planned / new (n)
### ⚪ Dormant / unowned (n)
### ⏸ Paused (n)
### ✅ Shipped since the last dive (n)

## ⏱ Due before the next deep dive (~<date>)   <!-- optional -->

| Item | Owner | Due | Status |
|---|---|---|---|

## 👥 Ownership & load

- **Lead load:** Name **n** · Name **n** · …
- **No lead:** …
- **Concentration / capacity risk:** …

## 📝 Your topics


## 🗒️ Notes & caveats

- **Progress measure:** <reported status-update % | issues completed ÷ (total − cancelled − duplicate)>
- **Coverage:** <which Linear teams, paginated or not>
- **Excluded — >2-team programmes with no open issues for this team:** <list them, or "none">
- <scope notes, contradictions, what this agenda cannot see>
```

---

## Publishing to b-eye

Every agenda is also a **dashboard** in b-eye → *Tech: Product → Deep Dives*
(`beye.weroad.com/browse/a830ba29-0623-4019-aa2e-74eafa7faec7`), with the superseded ones under
its **Archive (superseded)** subfolder.

**Step 4 of the skill publishes automatically** — every generated agenda is pushed in the same run
that built it, so a dashboard cannot drift from the `.md` beside it. To publish by hand (run from the
brain root):

```bash
python3 .claude/skills/brain-prepare-my-deep-dives/publish-to-beye.py tium        # one agenda
python3 .claude/skills/brain-prepare-my-deep-dives/publish-to-beye.py --all       # everything
python3 .claude/skills/brain-prepare-my-deep-dives/publish-to-beye.py --all --render   # build only
```

The publisher takes **slugs, not paths**, and resolves agendas from `--agendas <dir>` →
`$DEEP_DIVES_DIR` → `outputs/agents/my-deep-dives`. It names no target by default: bare invocation
prints usage and exits rather than silently republishing all 20 or silently doing nothing. `--all`
also re-publishes this file itself, as the *"The standard (agenda template)"* dashboard.

The script converts each `.md` to a self-contained HTML page and appends a **new version** to the
existing dashboard (ids in `.beye-assets.json`, which stays in the agendas folder — **keep it
committed, or a re-run creates duplicates**). ⚠️ It merges that map and replaces it atomically,
because `brain-morning-start` publishes several agendas **in parallel** and a last-writer-wins
overwrite loses a sibling's new asset id — which shows up one run later as a duplicate dashboard.
Constraints it already handles, so don't hand-edit the HTML: b-eye's CSP is `default-src 'none'` with
`style-src 'unsafe-inline'`, so **everything is inlined** — no external CSS, JS, fonts or images; the
viewer chrome is **light-only**, so the page pins light rather than following `prefers-color-scheme`;
and the viewer iframe is `sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"`, so
**`target="_blank"` links to Linear do open** (verified on v1.23.1 — read the live `sandbox`
attribute before assuming, an older note claimed they were impossible).

---

## Variants

- **Cross-cutting forums** (`tech`) have no single Linear team. Keep every section; say in
  Notes & caveats which boards were merged and how, and note that the **>2-team exclusion rule
  cannot apply** — there is no single "this team" to filter against.
- **Superseded agendas move to `archive/`.** When a forum's next session produces a new file, the
  old one is **not** left beside it: give it `freshness: ARCHIVED`, add the stale banner naming its
  successor, and `git mv` it into `outputs/agents/my-deep-dives/archive/`. Only the **current**
  agenda per forum sits at the top level. Links out of `archive/` need a `../` prefix.
- **Nothing but team deep-dive agendas lives in this folder.** A vendor briefing, a one-off research
  note or any other meeting doc belongs somewhere else under `outputs/`. There is no
  "briefing variant" — if it has no Linear board and no room of engineers, it is not a deep dive.
