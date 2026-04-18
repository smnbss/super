---
name: super-setup
description: Interactive project-scoped setup wizard for super + brain skills. Run from inside the project you want to use as your brain. Writes <project>/.super/brain.config.yml and creates agents/memory/outputs/src in that project. Use when the user says "super setup", "setup super", "configure brain", "configure super", "run setup", or right after first-time super install.
---

# /super-setup

Interactive configuration wizard for super's brain skills. **Project-scoped** — everything it writes lives inside the current project. No global state, no surprise dirs in `$HOME`.

## When to use

- Right after `super install` (install.sh prints a banner pointing here)
- After cloning a brain project to a new machine
- When source toggles, org details, or teams change
- When the user says "reconfigure", "update my config", "change org"

## Prerequisites

The current directory (or an ancestor) must contain a `.super/` directory — that marks the project root and **is** the brain. If no `.super/` is found walking up from cwd, tell the user to run `super install` first and stop.

## What this skill writes

1. `<project>/.super/brain.config.yml` — the project-scoped config consumed by every `brain-*` skill (org, role, Linear slug, Medium handle, source toggles, teams)
2. `<project>/{agents,memory,outputs,src}/` — scaffolded if missing
3. `<project>/sources.md` — generated from `~/.super/skills/brain-pull-sources/references/sources.md` (only if the file doesn't already exist)

## Flow

Use the `AskUserQuestion` tool for every user-facing question. After each answer, do a targeted `Edit` on `<project>/.super/brain.config.yml` so the user can see what changed. **Never rewrite the whole file** — preserve comments and layout.

### Step 0 — Discover project root

Walk up from cwd until you hit a `.super/` directory. That dir is the brain root. Show the user: *"Brain root: <path>. Continue here? Yes / No (cancel)."*

If they say cancel, exit cleanly.

If `.super/brain.config.yml` already exists, ask: *"Existing config found. Update it / Reset from sample / Skip."* For "Reset", copy `~/.super/references/brain-config.sample.yml` → `<project>/.super/brain.config.yml` (after confirming the destructive action) before continuing.

If `.super/brain.config.yml` doesn't exist, copy the sample to that path silently — that's the working file you'll Edit through the rest of the flow.

### Step 1 — Scaffold dirs

`mkdir -p` the four brain dirs in the project root if missing: `agents`, `memory`, `outputs`, `src`. Report what was created.

### Step 2 — Organization

Two questions:

1. *"What's your organization called?"* → `organization.name` (free text, one line)
2. *"What's your role?"* → `organization.role` (free text, e.g. "CTO of Acme"). Used in qmd `globalContext` and report templates.

### Step 3 — Linear

Ask: *"What's your Linear org slug?"* — the `<slug>` in `linear.app/<slug>/...`. Show the current value as default. Write to `linear.org`.

### Step 4 — Medium

Ask: *"Do you publish on Medium?"* (Yes/No).

- Yes → *"What's your Medium handle?"* (without the `@`). Write to `medium.handle`. Set `sources.medium.enabled: true`.
- No → Set `sources.medium.enabled: false`.

### Step 5 — GitHub

Ask: *"Which GitHub orgs should be synced?"* — comma-separated. Write to `sources.github.orgs` as a YAML inline list (e.g. `[acme, acme-labs]`).

### Step 6 — Source toggles

For each source below, ask: *"Do you use `<source>`?"* (Yes/No). Set `sources.<name>.enabled`. For each `Yes`, ask the source-specific follow-ups.

| Source | Follow-ups if enabled |
|--------|------------------------|
| `clickup` | `monkeys_wiki_path` (string — main wiki folder name, or leave default), `team_docs_prefix` (string — e.g. `"Docs "`) |
| `confluence` | `intranet_path`, `wiki_path` |
| `gdrive` | `exco_folder`, `projects_folder`, `one_pagers_folder` |
| `gws` | none |
| `linear` | none (covered by Step 3) |
| `medium` | (covered by Step 4) |
| `metabase` | none |
| `personio` | `roster_file` (default `staff-roster.tsv`). If the user doesn't use Personio, just disable it. |

For each follow-up, show the current value and ask "keep / change". Edit only if changed.

### Step 7 — Teams

The `teams[]` list is awkward to collect question-by-question. Offer three choices via `AskUserQuestion`:

1. **Keep current** — leave the `teams:` block untouched
2. **Paste YAML** — user pastes a full `teams:` block; replace the existing block verbatim
3. **Clear** — set `teams: []`; user will edit later

For option 2: read the existing `teams:` block span (from `^teams:` to either the next top-level key or EOF), then replace. Validate the pasted YAML parses as a list before writing.

### Step 8 — sources.md

Ask: *"Generate a starter `sources.md` at `<project>/sources.md`?"* (Yes/No).

- If `<project>/sources.md` already exists → tell the user and skip regardless of their answer.
- If Yes and missing:
  1. Read `~/.super/skills/brain-pull-sources/references/sources.md`
  2. Substitute placeholders using the collected answers:
     - `<your-org>` → the Linear slug (or ask separately for the Confluence/Atlassian subdomain if different)
     - `<org>` in github lines → the first GitHub org from Step 5
     - `<your-folder-id>` → ask the user for a top-level GDrive folder ID (skip the line if they don't have one)
     - `<SPACE_KEY>` → ask for the Confluence space key (skip the line if Confluence disabled)
     - `<TEAM_KEY>` → leave as-is (per-team; user fills in manually)
     - `<your-domain>` → ask for the Metabase hostname (skip if Metabase disabled)
  3. Write to `<project>/sources.md`

### Step 9 — Recap + next steps

Print a concise summary:

- Brain root: `<project>`
- Config file: `<project>/.super/brain.config.yml` — N values changed
- Dirs scaffolded: <list>
- Sources file: `<project>/sources.md` — created / skipped / existing

Then suggest:

```
Next steps (run from inside the brain project):
  1. Edit sources.md to add your actual source URLs and repos
  2. /brain-pull-sources         → populate src/
  3. /brain-rebuild-services     → generate service docs
  4. /brain-rebuild-memory       → build L1/L2 navigation
  5. /brain-reindex              → build the qmd hybrid search index
```

## Rules

- **Project-scoped only** — never write to `~/.super/brain.config.yml`. The active config is always `<project>/.super/brain.config.yml`.
- **Never clobber silently** — every write must show the user what's changing. Use the Edit tool's diff output.
- **Preserve comments and layout** — targeted Edits only; no whole-file rewrites.
- **Defaults are current values** — if a key already has a non-sample value, show it and ask "keep?" first.
- **`<project>/sources.md` is write-once** — never overwrite if it exists; note and move on.
- **Source toggles cascade** — disabling a source should skip its follow-up questions, not leave dead keys. Leave the source block in the YAML but set `enabled: false`.
- **Short questions** — one decision per `AskUserQuestion` call. No walls of text.
- **Abortable** — at any step the user can say "stop" / "skip" / "I'll edit by hand" and the skill should exit cleanly, reporting what was written so far.
