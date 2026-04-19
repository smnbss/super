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

The current directory (or an ancestor **strictly between cwd and `$HOME`**) must contain a **real** `.super/` directory — that marks the project root and **is** the brain. If no real `.super/` is found, tell the user to run `super install` first and stop.

> ⚠️ `$HOME/.super` is the **global super install**, not a project. Never treat `$HOME` as a brain root, even though `ls -ld $HOME/.super` reports a real directory. Stop the walk-up **before** reaching `$HOME`, and additionally skip any `.super/` whose realpath equals `$HOME/.super`.
>
> ⚠️ super install creates four debug-only symlinks inside each CLI's project dir:
>
> - `<project>/.claude/.claude → ~/.claude`
> - `<project>/.codex/.codex → ~/.codex`
> - `<project>/.gemini/.gemini → ~/.gemini`
> - `<project>/.super/.super → ~/.super`
>
> These exist for `cd`-convenience only. **Never read, write, or walk into any of them.** The brain's `.super/` is always the REAL directory at `<project>/.super/` — never `<project>/.super/.super/` (which resolves to `~/.super`). Writing `brain.config.yml` through the symlink corrupts the global super install.

## What this skill writes

1. `<project>/.super/brain.config.yml` — the project-scoped config consumed by every `brain-*` skill (org, role, Linear slug, Medium handle, source toggles, teams)
2. `<project>/{agents,memory,outputs,src}/` — scaffolded if missing
3. `<project>/.env.local` — copied from `~/.super/references/env.example` (only if the file doesn't already exist). The brain pull/rebuild skills read this for tokens. The user fills in the secrets after setup.
4. `<project>/sources.md` — generated from `~/.super/skills/brain-pull-sources/references/sources.md` (only if the file doesn't already exist)

## Flow

Use the `AskUserQuestion` tool for every user-facing question. After each answer, do a targeted `Edit` on `<project>/.super/brain.config.yml` so the user can see what changed. **Never rewrite the whole file** — preserve comments and layout.

### Step 0 — Discover project root

Walk up from cwd looking for the nearest `.super/` that is a **real directory** (`ls -ld <candidate>/.super` → leading `d` = real, `l` = symlink, skip). The same rule applies to `.claude/.claude`, `.codex/.codex`, `.gemini/.gemini` — never step through those.

Apply these guardrails during the walk:

1. **Stop before `$HOME`.** If `dir === $HOME`, do not check `$HOME/.super` — treat the walk as having found nothing. `$HOME/.super` is the global install, not a project root. This is the **most common failure mode**: running `/super-setup` from a fresh directory walks up past its own parents into `$HOME`, finds the global install, and misdetects `$HOME` as the brain root.
2. **Realpath-skip the global install.** Even if `$HOME` is unset or the layout is unusual, if the candidate `.super/` resolves (`realpath`) to the same path as `$HOME/.super`, skip it and keep walking.
3. **Never ask "continue in `$HOME`?"** If the walk returns `$HOME`, that's a bug — bail out with: *"No project `.super/` found. Run `super install` from inside your project directory first, then re-run `/super-setup`."* Do not offer to write anything in `$HOME`.

For the happy path, show the user: *"Brain root: <path>. Continue here? Yes / No (cancel)."*

To verify quickly before asking the user: `readlink -f <path>/.super` must not equal `readlink -f $HOME/.super`, and `<path>` must not equal `$HOME`.

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

### Step 9 — .env.local

Ensure the brain project has a `<project>/.env.local` scaffold so the pull/rebuild skills can read tokens.

- If `<project>/.env.local` already exists → note it and skip (write-once, never overwrite).
- Otherwise, prefer a project-shipped template in this order and copy the first one that exists:
  1. `<project>/.env.example` (e.g. a template committed to the brain repo)
  2. `~/.super/references/env.example` (the super default)
- After copying, tell the user: *".env.local created from <template path>. Fill in secrets before running /brain-pull-sources or /brain-rebuild-*."*
- Never print secrets to the transcript. Do not ask the user for token values here — that belongs in their own editor.

Suggest at the end: substitute any `<your-org>` / `<your-gcp-project>` / `<your-domain>` placeholders copied from the template using the values already collected in Steps 2–5 where unambiguous, via targeted `Edit` calls on `<project>/.env.local`. Leave placeholders alone when in doubt.

### Step 10 — Run `super configure`

`super install` only installs super itself, hooks, CLIs, and the skills shipped
inside `$SUPER_HOME/skills/`. External catalog skills, plugins, MCPs, and the
context files (`AGENTS.md` + `CLAUDE.md`/`GEMINI.md` symlinks) are installed
here, **after** the user has filled in `.env.local`.

Before proceeding, confirm the required tokens in `.env.local` are non-empty
(at minimum the ones for the sources the user just enabled — `LINEAR_TOKEN`,
`CLICKUP_TOKEN`, `CONFLUENCE_TOKEN`, etc.). If any required token is still
blank, stop and ask the user to fill them in first.

Then run:

```bash
super configure
```

from the project root. It will install external skills/plugins/MCPs listed in
`.super/super.config.yaml`, sync skills into each CLI's skill directory, and
create `AGENTS.md` + `CLAUDE.md`/`GEMINI.md` symlinks.

### Step 11 — Recap + next steps

Print a concise summary:

- Brain root: `<project>`
- Config file: `<project>/.super/brain.config.yml` — N values changed
- Dirs scaffolded: <list>
- Sources file: `<project>/sources.md` — created / skipped / existing
- Env file: `<project>/.env.local` — created / skipped / existing
- `super configure` — ran / skipped

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

- **Never treat `$HOME` as a brain root.** `$HOME/.super` is the global super install. If your walk-up reaches `$HOME`, that means no project was found — refuse and direct the user to run `super install` from inside a project directory first. Never write `brain.config.yml`, `agents/`, `memory/`, `outputs/`, `src/`, `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` at the top of `$HOME` under any circumstance.
- **Project-scoped only** — never write to `~/.super/brain.config.yml`. The active config is always `<project>/.super/brain.config.yml`, where `.super` is the real directory.
- **Ignore all debug symlinks** — `<project>/.claude/.claude`, `<project>/.codex/.codex`, `<project>/.gemini/.gemini`, and `<project>/.super/.super` are `cd`-convenience links to `~/.CLI`. Never read, write, enumerate, or walk through them from skills.
- **Never clobber silently** — every write must show the user what's changing. Use the Edit tool's diff output.
- **Preserve comments and layout** — targeted Edits only; no whole-file rewrites.
- **Defaults are current values** — if a key already has a non-sample value, show it and ask "keep?" first.
- **`<project>/sources.md` is write-once** — never overwrite if it exists; note and move on.
- **Source toggles cascade** — disabling a source should skip its follow-up questions, not leave dead keys. Leave the source block in the YAML but set `enabled: false`.
- **Short questions** — one decision per `AskUserQuestion` call. No walls of text.
- **Abortable** — at any step the user can say "stop" / "skip" / "I'll edit by hand" and the skill should exit cleanly, reporting what was written so far.
