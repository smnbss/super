---
name: super-setup
description: Interactive setup wizard for super + brain skills. Walks the user through the knobs in ~/.super/brain.config.yml and generates $BRAIN/sources.md. Use when the user says "super setup", "setup super", "configure brain", "configure super", "run setup", or right after first-time super install.
---

# /super-setup

Interactive configuration wizard for super's brain skills. Walks the user through `~/.super/brain.config.yml` and, optionally, generates `$BRAIN/sources.md` from the template.

## When to use

- Right after `super install` (install.sh prints a banner pointing here)
- When the user changes orgs, Linear slug, Medium handle, brain location
- When re-onboarding a teammate
- When the user says "reconfigure", "update my config", "change org"

## Prerequisites

- `~/.super/brain.config.yml` exists (super install drops the sample there; bail with a hint if missing)
- The user's `$BRAIN` path exists or will be created during the flow

## What this skill writes

1. `~/.super/brain.config.yml` — the config consumed by every `brain-*` skill
2. `$BRAIN/sources.md` — the working copy of the sources manifest, generated from `~/.super/skills/brain-pull-sources/references/sources.md` (only if the file doesn't already exist)

## Flow

Use the `AskUserQuestion` tool for every user-facing question — it gives structured choices. After each answer, do a targeted `Edit` on `~/.super/brain.config.yml` so the user can see what changed. **Never rewrite the whole file** — preserve comments and layout.

### Step 0 — Read current state

Read `~/.super/brain.config.yml`. Capture the current values for every scalar you're about to ask about. Show the user a 1-line "current → proposed" diff before each write.

If the file is missing, tell the user to re-run `super install` and stop.

### Step 1 — Brain path

Ask: *"Where should your brain repo live?"* — default = current `brain.path`, pre-expanded.

- Resolve `~` to `$HOME`
- `mkdir -p` the result if missing
- Edit `brain.path` in the config

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

1. **Keep current** — leave the `teams:` block untouched (useful for re-runs or if the WeRoad defaults fit)
2. **Paste YAML** — user pastes a full `teams:` block; replace the existing block verbatim
3. **Clear** — set `teams: []`; user will edit later

For option 2: read the existing `teams:` block span (from `^teams:` to either the next top-level key or EOF), then replace. Validate the pasted YAML parses as a list before writing.

### Step 8 — sources.md

Ask: *"Generate a starter `sources.md` at `$BRAIN/sources.md`?"* (Yes/No).

- If `$BRAIN/sources.md` already exists → tell the user and skip regardless of their answer.
- If Yes and missing:
  1. Read `~/.super/skills/brain-pull-sources/references/sources.md`
  2. Substitute placeholders using the collected answers:
     - `<your-org>` → the Linear slug (or ask separately for Confluence/Atlassian subdomain if different)
     - `<org>` in github lines → the first GitHub org from Step 5
     - `<your-folder-id>` → ask the user for a top-level GDrive folder ID (skip the line if they don't have one)
     - `<SPACE_KEY>` → ask for the Confluence space key (skip the line if Confluence disabled)
     - `<TEAM_KEY>` → leave as-is (per-team; user fills in manually)
     - `<your-domain>` → ask for the Metabase hostname (skip if Metabase disabled)
  3. Write to `$BRAIN/sources.md`

### Step 9 — Recap + next steps

Print a concise summary:

- Config file: `~/.super/brain.config.yml` — N values changed
- Sources file: `$BRAIN/sources.md` — created / skipped / existing

Then suggest:

```
Next steps:
  1. Edit $BRAIN/sources.md to add your actual source URLs and repos
  2. Run /brain-pull-sources to populate src/
  3. Run /brain-rebuild-services to generate service docs
  4. Run /brain-rebuild-memory to build L1/L2 navigation
  5. Run /brain-reindex to build the qmd hybrid search index
```

## Rules

- **Never clobber silently** — every write must show the user what's changing. Use the Edit tool's diff output.
- **Preserve comments and layout** — targeted Edits only; no whole-file rewrites.
- **Defaults are current values** — if a key already has a non-sample value, show it and ask "keep?" first.
- **`$BRAIN/sources.md` is write-once** — never overwrite if it exists; note and move on.
- **Source toggles cascade** — disabling a source should skip its follow-up questions, not leave dead keys. Leave the source block in the YAML but set `enabled: false`.
- **Short questions** — one decision per `AskUserQuestion` call. No walls of text.
- **Abortable** — at any step the user can say "stop" / "skip" / "I'll edit by hand" and the skill should exit cleanly, reporting what was written so far.
