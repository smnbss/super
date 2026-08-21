---
name: brain-work-on
description: >
  Bootstrap a working session on a specific project or capability by loading all
  relevant context — DEVELOPER.md, matching repos in github, service docs in
  outputs/services, and prior project workspace notes in outputs/projects. Use
  when the user says "work on <name>", "/brain-work-on <name>", "start working on",
  "I want to build <x>", "let's build <x>", or passes a project/capability name
  and asks to set up context before coding. Also use when the user wants a working
  session tracked in Linear, or names a Linear project or issue to work under. Run
  this BEFORE writing code so the session has the full picture.
---

# Brain — Work On

Prepare to build a new capability on a specific project. Gather developer context,
find the relevant repos, pull in existing architecture docs, and read any prior
workspace notes — then summarize what was found and wait for the user's direction.

This skill does **not** write code. It loads context, agrees a plan, and opens the
Linear record the session is tracked in.

**Superpowers is active by default.** Steps 1–7 are the read phase; Step 8 hands
off to `superpowers:brainstorming` and then `superpowers:writing-plans`. Do not
skip to implementation because the context looked sufficient — the plan file is
what Step 9 projects into Linear, so there is nothing to track without it.

## Input

One or more project / capability names, passed as the skill argument.
Accept space-separated or comma-separated lists. Examples:

```
/brain-work-on ask-weroad
/brain-work-on wemeet
/brain-work-on catalog api-catalog
/brain-work-on website, catalog, api-catalog
```

Parse the argument into a list of names. Run Steps 1–5 **once per name** to
produce a per-name briefing, then in Step 6 print all briefings back-to-back
and — if there is more than one name — add a final **"How these fit together"**
section that calls out relationships between them (paired frontend/backend,
shared DB, RabbitMQ producer↔consumer, API client↔server). This matters because
multi-project requests almost always mean "I'm working across a seam" — making
the seam explicit up front saves the model from re-deriving it mid-task.

Each name may match:
- A repo under `github/<org>/<name>` (exact match preferred, then substring)
- A service doc at `outputs/services/<name>.agent.md` or `*<name>*.agent.md`
- A project workspace at `outputs/projects/<name>/`

If no name is provided, stop and ask:
> "Which project(s) should I set up context for? Example: `/brain-work-on ask-weroad` or `/brain-work-on catalog api-catalog`"

## Step 1 — Load developer context

Check for `DEVELOPER.md` at the repo root (`$BRAIN_ROOT/DEVELOPER.md`, typically
`/Users/simone.basso/code/weroad/weroad_brain/DEVELOPER.md`).

- If it exists → read it in full. It contains prerequisites, local setup, and
  pointers to cross-cutting architecture docs (jungle, terraform, dev guidelines).
- If it does not exist → note this and continue.

This is the baseline: how WeRoad code runs locally and which shared resources
matter. Without it the session may miss tooling expectations.

## Step 2 — Find matching repos in `github`

The GitHub export is organized by org: `github/<org>/<repo>`.

Run both passes and **classify each hit** — the exact/substring distinction
matters because substring matches on short names (like `catalog`) can pull in
3–4 repos, and the user needs to see which one is the real target.

1. **Exact match pass:**
   ```
   github/*/<name>
   ```
   (e.g., `github/weroad/ask-weroad`, `github/smnbss/ask-weroad`).
   Tag these as `exact`.

2. **Substring pass:** list any directory whose name **contains** the input as
   a substring (case-insensitive), excluding anything already in the exact set.
   Tag these as `substring`. Include near-misses like `ask-linear` when the
   user types `ask-weroad` — they often signal the closest existing reference
   implementation.

3. **For each matched repo** (both tiers):
   - Read `README.md` if present (first 200 lines is enough for context).
   - Read `package.json` / `pyproject.toml` / `go.mod` to identify the stack.
   - Read `CLAUDE.md`, `AGENTS.md`, and any `.claude/rules/*.md` if present —
     these are the repo's own conventions and gates (lint/typecheck/test
     commands, naming rules, architecture invariants). They carry more signal
     per line than almost anything else in the repo, and missing them is the
     most common cause of "the AI did the wrong thing the WeRoad way."
   - Note the directory structure at one level deep.

4. **Ranking in the briefing:** show exact matches first, substring matches
   second, and mark each with its tag so the user sees immediately which repo
   the skill thinks is the target vs. which are siblings worth knowing about.

### No exact match — disambiguate before declaring greenfield

If there is **no exact match**, do not immediately call this a greenfield build.
Ambiguous or common names (`website`, `catalog`, `admin`) often refer to an
existing surface that just isn't named literally. Instead:

1. If there are substring matches, name the most plausible one as the likely
   target and list the rest as siblings.
2. If there are **zero matches of any kind**, call `mcp__gbrain__query` with
   `"<name>"` and look at the top 5–10 hits. Propose up to 3 candidate
   repos/surfaces the user might mean, based on where the name shows up
   (service docs, project notes, memory files).
3. Ask the user:
   > "No repo named `<name>` in `github`. Did you mean one of these:
   > <A>, <B>, <C>? Or is this a new capability to build from scratch?"
4. Only after the user confirms "new capability" (or the gbrain pass truly
   returns nothing related) should the skill frame this as greenfield.

Greenfield framing changes the next step's work significantly — it shifts from
"understand existing code" to "pick a reference implementation to mirror" — so
it's worth one disambiguation question to avoid starting the wrong way.

## Step 3 — Find service documentation

Look in `outputs/services/` for architecture docs:

1. Exact match: `outputs/services/<name>.agent.md` or
   `outputs/services/weroad-<name>.agent.md`.
2. Fuzzy match: any `*.agent.md` whose filename contains the input.
3. If the repo includes a database, also look for `*.db.agent.md`.
4. Check `outputs/services/cross/` for cross-cutting docs that mention the
   capability (RabbitMQ topology, event flows, etc.) — use `mcp__gbrain__query`
   if scanning filenames is not enough.

Read each matched doc. These are the source of truth for how existing services
are built and what conventions to follow.

## Step 4 — Find prior project notes

Look in `outputs/projects/<name>/` — this is the ad-hoc workspace layer where
prior brainstorming, spikes, and scratch work live.

- If `outputs/projects/<name>/` exists → list its contents and read any top-level
  `.md` files. These capture decisions, rejected approaches, and open questions
  from earlier sessions.
- If it does not exist → note it. You may create it later when work begins, but
  do not create it in this skill.

## Step 5 — Pull cross-source mentions (optional, run if Steps 2–4 were thin)

If the first three steps produced little context, run a hybrid search to surface
mentions across the brain:

- Call `mcp__gbrain__query` with the query `"<name>"`.

Scan the top 10 results for references in `memory/`, ClickUp exports, meeting
notes, or Linear issues. Read the 2–3 most relevant hits. This catches cases
where a capability is discussed in planning docs before any code exists.

## Step 6 — Summarize the picture

Print a compact context briefing so the user can confirm you've loaded the right
things before proposing an approach. Use this exact per-name structure, then
add the cross-project synthesis section if more than one name was given.

### Per-name briefing (repeat for each input name)

```
## Context loaded for: <name>

**Developer guide:** <loaded | missing>

**Matching repos** (github):
- [exact] <org>/<repo> — <one-line stack + purpose>
- [substring] <org>/<repo> — <one-line stack + purpose>
- ...
(or: "none — awaiting disambiguation" / "none — confirmed greenfield")

**Service docs** (outputs/services):
- <filename> — <one-line summary>
- ...
(or: "none")

**Prior workspace** (outputs/projects/<name>):
- <file or note>
(or: "none — fresh workspace")

**Cross-source mentions** (if Step 5 ran):
- <source>: <one-line>
- ...

**Stack & conventions I'll follow:**
- <language / framework>
- <lint/test/build gates from CLAUDE.md / AGENTS.md>
- <any repo-specific patterns worth flagging>

**Tracking (proposed — confirm in Step 7):**
- Linear team: <KEY> (from IDP owning team `<owner>` | SIM — no owning team)
- Project: <best-matching active project | none found>
- Existing record: <STM-412 from .linear.json — will reattach | none, will create>

**Open questions before we start:**
1. <question about scope / surface area>
2. <question about integration points>
3. ...
```

### Cross-project synthesis (only if more than one name was given)

After the last per-name briefing, add:

```
## How these fit together

- <relationship 1 — e.g., "catalog is the Nuxt frontend CMS that talks to
  api-catalog via $axios; GraphQL schema is split public/admin">
- <relationship 2 — e.g., "api-catalog publishes to RabbitMQ exchange X; N
  consumers include <other repo>">
- <shared infra — auth provider, DB connection, shared package>
- <the seam that matters for the likely task — API contract, event shape,
  shared module>
```

Derive relationships from the service docs (which name their siblings), shared
DB connections, shared packages in `package.json`/`composer.json`, and the
`outputs/services/cross/` RabbitMQ topology files. Keep it to the seams that
actually matter — don't enumerate every shared dependency. The goal is: when
the user names their first capability, neither of you has to re-learn how the
pieces connect.

## Step 7 — Resolve the Linear tracking target

Propose a specific target and have the user confirm it. Never open with a blank
"which Linear project?" — Steps 2–3 already found the repo, so the owning team is
derivable and the question should be a yes/no, not an interrogation.

If Step 2 ended in a disambiguation question ("did you mean…"), wait for that
answer first. Never stack the two questions.

### 7a — Derive the owning team from the repo

**First resolve the repo name to IDP service directories — they are not the same
thing.** A repo commonly maps to two prefixed services, and `src/idp/<repo>/` may
not exist at all:

```bash
ls -d src/idp/*<repo>* 2>/dev/null      # cashew -> admin-cashew AND api-cashew
```

- one hit → use it
- several hits, **owners agree** → use that owner
- several hits, **owners disagree** → ask which surface the work is on; don't pick
- no hits → the repo isn't an IDP service, go to 7b

⚠️ If you loop over the glob results in a shell, quote/array them — this shell is
**zsh**, which does not word-split unquoted variables, so `for d in $hits` iterates
once over the whole multi-line blob and silently yields an empty owner on exactly
the multi-hit repos that need it. Prefer a short Python block over shell here.

Then read the owner:

```bash
grep -iE "^\|\s*Owning team\s*\|" src/idp/<service>/service.md
```

All 84 IDP services carry this field (verified 2026-08-21: 84/84, no gaps). Map it
with the table below. **Read the table — do not infer the key from the name**, two
entries don't follow:

| IDP `Owning team` | Linear key | Linear team |
|---|---|---|
| `staff` | `STF` | STAFF |
| `buktu` | `BUK` | BUKTU |
| `saitama` | `STM` | SAITAMA |
| `stomp` | `STO` | STOMP |
| `devops` | `DVO` | DEVOPS |
| `data-engineers` | `DE` | Data Engineering |
| `tium` | `TIUM` | TIUM |
| `cyclops` | `CYC` | CYCLOPS |
| `saian` | **`AI`** | SAIAN |
| `rocket` | `RKT` | ROCKET |

⚠️ `saian` → **`AI`**, not `SAI`. `data-engineers` → **`DE`** (Data Engineering),
not `BI`.

### 7b — No owning team → SIM

`SIM` ("Simon", private, cycles disabled) is the fallback, **not the default**. Use
it only when no owning team resolves:

- the repo isn't an IDP service — `super`, this brain repo, `gstack`
- the service is deliberately absent from the IDP catalog — `wetracker`
  (marketing-owned) and `wemeet-hosted-ops` (ops-built)
- the user picks it explicitly

SIM carries no `Idea:`/`Task:` prefix from this skill. Those prefixes belong to
other skills' conventions and this skill must not emit them anywhere.

### 7c — Pick the project, then propose

List the team's active projects with the **MCP** `list_projects` (resolve the tool
name as in Step 9), passing `team: "<KEY>"` and `state: "started"`.

⚠️ **Use the MCP for projects, not `wr-linear projects list` — but not for the
reason this skill used to give.** Re-measured 2026-08-21, and the earlier claim that
`--team` "returns 0 projects for every team" is **FALSIFIED**: the plain call works
and filters correctly (`--team TIUM` → 50 rows, all 50 genuinely carrying TIUM).
The real defect is narrower and worse — **every flag that would take you past 50
returns a silent zero, exit 0:**

| Invocation | Rows |
|---|---|
| `projects list --team TIUM` | 50 — correct, but capped at the default `--limit` |
| `projects list --team TIUM --all` | **0** |
| `projects list --team TIUM --limit 100` (or 250) | **0** |

So you cannot page past 50 projects on this CLI at all, and the attempt looks like
an empty board rather than an error. The MCP `list_projects` also caps at 50 but
**does** expose `cursor`, so it is the only path that can enumerate a full board —
which is why the recommendation stands even though its old justification did not.

⚠️ Do not generalise this to issues: `wr-linear issues list --project "<name>" --all`
auto-paginates correctly (verified 2026-08-21: 359 rows on Bugs Triage, where the MCP
silently caps at 250). `--all` is broken for **projects**, not for the CLI.

⚠️ `list_projects` caps `limit` at **50** and truncates silently — follow `cursor`
while `hasNextPage` is true before concluding a project doesn't exist. Note also
that a project can span many teams, so a hit on the owning team doesn't mean it's
that team's project alone.

Pick the best title match against the work, then propose one line and stop for
confirmation:

> Tracking under **STM** → project *Cashew Cost Approval*, new issue.
> Confirm, name a different project/issue, or say "no tracking".

Accept all three answers. **"No tracking" is first-class** — a session that only
reads code shouldn't open a ticket. Also accept a target given up front
(`/brain-work-on cashew --issue STM-412`) and skip this step entirely.

### 7d — Reattach, never duplicate

Before creating anything, read the pointer file:

```
outputs/projects/<name>/.linear.json
```

```json
{
  "team": "STM",
  "linearProject": "Cashew Cost Approval",
  "issue": "STM-412",
  "issueUrl": "https://linear.app/weroad/issue/STM-412",
  "planFile": "outputs/projects/cashew/plan-2026-08-20.md",
  "logThreadId": "<comment id>"
}
```

If it exists and the issue is still open, **reattach to that issue** — a re-run
continues the session, it does not start a second one. Write the file as soon as
the issue exists, before any sub-issue, so an interrupted run is resumable.

## Step 8 — Brainstorm, then write the plan

Hand off to `superpowers:brainstorming` to settle intent and scope, then
`superpowers:writing-plans` to write the plan to
`outputs/projects/<name>/plan-<YYYY-MM-DD>.md`.

**The plan file is authoritative. Linear is a projection of it.** Sync one
direction only: plan → Linear. Never read state back out of Linear and into the
plan — the moment both are authoritative they diverge on the first update that
lands in only one, and then neither can be trusted.

## Step 9 — Project the plan into Linear

### Resolving the Linear tools

The Linear MCP is a remotely-managed connector with an **opaque, unstable server
id**. Never hardcode a tool name. Resolve by suffix at run time:

```
ToolSearch  query: "+save_issue linear"        → mcp__<id>__save_issue
ToolSearch  query: "+save_comment linear"      → mcp__<id>__save_comment
ToolSearch  query: "+list_issues linear"       → mcp__<id>__list_issues
```

Hardcoded Linear tool names are the known failure mode here: other skills in this
repo still reference bare `list_issues` / `update_issue` that no longer resolve.

Bulk reads stay on `wr-linear` (roughly 95% smaller payloads). Writes go through
the MCP.

### The three tiers

| Tier | Linear object | Holds |
|---|---|---|
| Session | one issue | the goal, the plan file path + commit sha |
| Phase | sub-issue per plan phase (`parentId`) | one top-level plan task each |
| Request log | one comment thread on the session issue | every request, chronologically |

Create the session issue with `save_issue`: `title`, `team`, `project`,
`description` (goal + `planFile` path + commit sha so the projection is
auditable). Then one sub-issue per plan phase with `parentId` set.

**Leave `estimate` and `cycle` unset — always.** That is what keeps this work off
the owning team's burndown while still showing on their board, which is correct:
it's their codebase. Do not set a label unless the user names one that already
exists on that team — **never create a label**, labels are per-team board
configuration and heterogeneous across teams.

Use the `patch` array for later description edits rather than rewriting the whole
description. Anchors must match exactly once and the whole patch aborts if one
fails, so it either applies cleanly or changes nothing.

## Step 10 — Log requests as the session runs

Every request the user makes gets appended as a **reply in the single log thread**
on the session issue (`save_comment` with `parentId` = the thread's root comment,
id stored as `logThreadId`).

One issue per request is wrong — a session is dozens of conversational turns, and
issue-per-request makes the board untriageable and distorts every count. The
thread is the log; issues are the structure.

As each plan phase completes, move its sub-issue's `state` forward. That is the
only Linear write driven by progress rather than by a user request.

## Why this shape

Starting a session without context is the single biggest source of wasted tokens
and wrong-headed first drafts. WeRoad has 60+ repos, deep service docs, and prior
project notes — a capability rarely exists in isolation. This skill front-loads
the read phase so the build phase has something to anchor to, and makes the
"what exists vs. what's greenfield" distinction explicit before a single line
of code is written.

The Linear projection exists because that read phase used to evaporate at session
end. The plan file persists the thinking; the Linear record puts it where the work
actually lives, on the board of the team that owns the code — without inventing a
second source of truth for what the plan says.

## Common mistakes

| Mistake | Why it breaks |
|---|---|
| Asking "which Linear project?" cold | The owning team is derivable from the repo. Propose; don't interrogate. |
| `grep`ing `src/idp/<repo>/service.md` directly | Repo ≠ service dir. `cashew` is `admin-cashew` + `api-cashew`. Glob first. |
| `wr-linear projects list --team` | Returns a silent 0 for every team. Use the MCP `list_projects`. |
| Trusting the first page of `list_projects` | Caps at 50 and truncates silently. Follow `cursor`. |
| Hardcoding `mcp__<uuid>__save_issue` | The connector id is unstable. Resolve by suffix via ToolSearch. |
| Inferring `SAI` from `saian` | The Linear key is `AI`. Read the mapping table. |
| Creating an issue per request | Untriageable board, distorted counts. Comments in one thread. |
| Setting `estimate` or `cycle` | Pulls the session into the owning team's burndown. |
| Creating a label to tag the work | Labels are per-team board config. Only use one that exists. |
| Reading state back from Linear into the plan | Two sources of truth diverge. Plan → Linear, one direction. |
| Creating a second issue on re-run | Read `.linear.json` first and reattach. |
| Emitting `Idea:`/`Task:` titles | Those belong to other skills' conventions. Plain titles here. |

Starting a session without context is the single biggest source of wasted tokens
and wrong-headed first drafts. WeRoad has 60+ repos, deep service docs, and prior
project notes — a capability rarely exists in isolation. This skill front-loads
the read phase so the build phase has something to anchor to, and makes the
"what exists vs. what's greenfield" distinction explicit before a single line
of code is written.
