---
name: brain-work-on
description: >
  Bootstrap a working session on a specific project or capability by loading all
  relevant context — DEVELOPER.md, matching repos in src/github, service docs in
  outputs/services, and prior project workspace notes in outputs/projects. Use
  when the user says "work on <name>", "/brain-work-on <name>", "start working on",
  "I want to build <x>", "let's build <x>", or passes a project/capability name
  and asks to set up context before coding. Run this BEFORE writing code so the
  session has the full picture.
---

# Brain — Work On

Prepare to build a new capability on a specific project. Gather developer context,
find the relevant repos, pull in existing architecture docs, and read any prior
workspace notes — then summarize what was found and wait for the user's direction.

This skill does **not** write code. It loads context and confirms readiness.

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
- A repo under `src/github/<org>/<name>` (exact match preferred, then substring)
- A service doc at `outputs/services/<name>.AGENT.MD` or `*<name>*.AGENT.MD`
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

## Step 2 — Find matching repos in `src/github`

The GitHub export is organized by org: `src/github/<org>/<repo>`.

Run both passes and **classify each hit** — the exact/substring distinction
matters because substring matches on short names (like `catalog`) can pull in
3–4 repos, and the user needs to see which one is the real target.

1. **Exact match pass:**
   ```
   src/github/*/<name>
   ```
   (e.g., `src/github/weroad/ask-weroad`, `src/github/smnbss/ask-weroad`).
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
2. If there are **zero matches of any kind**, run `qmd query "<name>"` and look
   at the top 5–10 hits. Propose up to 3 candidate repos/surfaces the user
   might mean, based on where the name shows up (service docs, project notes,
   memory files).
3. Ask the user:
   > "No repo named `<name>` in `src/github`. Did you mean one of these:
   > <A>, <B>, <C>? Or is this a new capability to build from scratch?"
4. Only after the user confirms "new capability" (or the qmd pass truly
   returns nothing related) should the skill frame this as greenfield.

Greenfield framing changes the next step's work significantly — it shifts from
"understand existing code" to "pick a reference implementation to mirror" — so
it's worth one disambiguation question to avoid starting the wrong way.

## Step 3 — Find service documentation

Look in `outputs/services/` for architecture docs:

1. Exact match: `outputs/services/<name>.AGENT.MD` or
   `outputs/services/weroad-<name>.AGENT.MD`.
2. Fuzzy match: any `*.AGENT.MD` whose filename contains the input.
3. If the repo includes a database, also look for `*.DB.AGENT.MD`.
4. Check `outputs/services/cross/` for cross-cutting docs that mention the
   capability (RabbitMQ topology, event flows, etc.) — use `qmd query` if
   scanning filenames is not enough.

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

```bash
qmd query "<name>"
```

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

**Matching repos** (src/github):
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

## Step 7 — Stop and wait

Do **not** start implementing. Ask:

> "Ready to build. What's the first capability you want to add?"
> (For multi-project runs: "…and which surface does it start on?")

Then wait for the user's direction. The next step (brainstorming, planning, or
direct implementation) is the user's call — route into the appropriate skill
(`brainstorming`, `writing-plans`, `office-hours`, etc.) based on their reply.

If Step 2 ended in a disambiguation question ("did you mean…"), wait for that
answer first before asking the capability question — the two should not be
stacked.

## Why this shape

Starting a session without context is the single biggest source of wasted tokens
and wrong-headed first drafts. WeRoad has 60+ repos, deep service docs, and prior
project notes — a capability rarely exists in isolation. This skill front-loads
the read phase so the build phase has something to anchor to, and makes the
"what exists vs. what's greenfield" distinction explicit before a single line
of code is written.
