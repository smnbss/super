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

### Step 2 — Run `super install` (first pass)

Run install BEFORE asking questions so the brain has its full toolchain available regardless of which sources the user ends up enabling. `super install` is fully idempotent — MCP configuration will be re-run implicitly at Step 11 if the user populates new env vars during Q&A.

Before running, verify you're in the brain root (the path discovered in Step 0, not a subdirectory or `$HOME`). Then:

```bash
super install --all
```

This installs (or refreshes) **everything** in one pass:

1. **super itself + system prereqs** — `git pull --rebase --autostash` in `~/.super`, `uv`, `markitdown`, `ollama`, `gws`, `gcloud`
2. **CLI binaries** — `claude`, `gemini`, `codex` (via each catalog entry's install command)
3. **Hooks** — `.claude/settings.json`, `.gemini/settings.json`, `.codex/hooks.json`
4. **Built-in super skills** — copied from `$SUPER_HOME/skills/` into `<project>/.agents/skills/` + symlinked into each CLI's project skill dir
5. **Global super-skill symlinks** — `~/.<cli>/skills/<super-skill>` → `$SUPER_HOME/skills/<super-skill>` so skills invoked outside this project always use the latest shipped version
6. **External catalog skills** — every entry under `skills:` in `<project>/.super/super.config.yaml` with `enabled: true`
7. **Plugins** — Claude marketplaces, their discovered skills + commands
8. **MCPs** — writes `<project>/.claude/settings.local.json`, `.gemini/settings.json`, `.codex/config.json`. Warns when `$env:VAR` references resolve to empty (because `.env.local` isn't filled yet) — expected on the first pass and not an error.
9. **Context files** — `AGENTS.md` created, `CLAUDE.md` and `GEMINI.md` symlinked to it

Stream the output so the user sees what ran. If `super install` fails, report the error and stop — the remaining steps assume a working install.

> `super configure` still works as an alias for `super install` (older docs and muscle memory). Both commands do the same thing now.

### Step 3 — Ensure `.env.local` exists

`super install` scaffolds `<project>/.env.local` from `<SUPER_HOME>/references/env.example` when it's missing. Verify it's there now.

- If `<project>/.env.local` is missing: run the scaffold (`cp ~/.super/references/env.example <project>/.env.local`) and tell the user you created it from the template.
- If present: move on silently.

You will not ask for token values here — secrets belong in the user's editor. The Q&A steps further down collect only non-secret config (org name, source toggles, etc.), plus the gws/bq OAuth client ID/secret pairs (which flow straight into targeted `Edit` calls without echoing to the transcript).

### Step 4 — Organization

Two questions:

1. *"What's your organization called?"* → `organization.name` (free text, one line)
2. *"What's your role?"* → `organization.role` (free text, e.g. "CTO of Acme"). Used in qmd `globalContext` and report templates.

### Step 5 — Linear

Ask: *"What's your Linear org slug?"* — the `<slug>` in `linear.app/<slug>/...`. Show the current value as default. Write to `linear.org`.

### Step 6 — Medium

Ask: *"Do you publish on Medium?"* (Yes/No).

- Yes → *"What's your Medium handle?"* (without the `@`). Write to `medium.handle`. Set `sources.medium.enabled: true`.
- No → Set `sources.medium.enabled: false`.

### Step 7 — GitHub

Ask: *"Which GitHub orgs should be synced?"* — comma-separated. Write to `sources.github.orgs` as a YAML inline list (e.g. `[acme, acme-labs]`).

### Step 8 — Source toggles

For each source below, ask: *"Do you use `<source>`?"* (Yes/No). Set `sources.<name>.enabled`. For each `Yes`, ask the source-specific follow-ups.

| Source | Follow-ups if enabled |
|--------|------------------------|
| `clickup` | `monkeys_wiki_path` (string — main wiki folder name, or leave default), `team_docs_prefix` (string — e.g. `"Docs "`) |
| `confluence` | `intranet_path`, `wiki_path` |
| `gdrive` | `exco_folder`, `projects_folder`, `one_pagers_folder` |
| `gws` | Run the **gws auth block** below. |
| `bigquery` | Run the **bq auth block** below. |
| `linear` | none (covered by Step 5) |
| `medium` | (covered by Step 6) |
| `metabase` | none |
| `personio` | `roster_file` (default `staff-roster.tsv`). If the user doesn't use Personio, just disable it. |

For each follow-up, show the current value and ask "keep / change". Edit only if changed.

#### gws auth block (run when `sources.gws.enabled: true`)

Run this whenever the user enables `gws` in Step 8. It's idempotent — each step short-circuits when its condition is already satisfied, so a re-run on an already-configured machine is cheap.

1. **Binary check.** Verify `gws` is on PATH (`command -v gws`). If missing, tell the user to re-run `super install` (the `googleworkspace-cli` system entry installs it via Homebrew on macOS and from the prebuilt tarball on Linux) and skip the rest of this block.

2. **Credentials in `.env.local`.** Read `<project>/.env.local`. If both `GOOGLE_WORKSPACE_CLI_CLIENT_ID` and `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET` are non-empty, say *"Credentials already in `.env.local`. Skipping to auth check."* and jump to step 4.

   Otherwise ask: *"No OAuth credentials in `.env.local`. Walk you through creating an OAuth 2.0 Client ID in Google Cloud Console? — yes / have credentials already / skip."*

   - **yes** → show the walkthrough below, then collect each value via a dedicated `AskUserQuestion`
   - **have credentials already** → skip the walkthrough, collect the two values directly
   - **skip** → tell the user to fill the keys in `.env.local` manually and jump to step 4 (which will fail the auth check and tell them to come back)

   Walkthrough (show verbatim):

   ```
   1. Open https://console.cloud.google.com/apis/credentials
   2. Select (or create) a project — any project works
   3. Create credentials → OAuth client ID
   4. If prompted to configure the consent screen:
      - User Type: External
      - App name: anything (e.g. "super-brain")
      - User support email: your email
      - Scopes: leave empty for now (gws asks at login time)
      - Test users: add your own Google account
   5. Back at "Create OAuth client ID":
      - Application type: Desktop app
      - Name: anything (e.g. "super-brain-desktop")
   6. Click Create → copy the Client ID and Client Secret
   ```

   Collect each value with its own `AskUserQuestion` call (so nothing is echoed to the transcript), then `Edit` `<project>/.env.local` to replace the two empty `GOOGLE_WORKSPACE_CLI_CLIENT_ID=` / `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET=` lines. **Never print the secret back.**

3. **Enable required Google APIs.** Before the first `gws auth login`, the OAuth project needs these APIs enabled or login fails with `PERMISSION_DENIED`. Tell the user once:

   *"In the same Google Cloud project, open 'APIs & Services → Library' and enable: Gmail API, Google Calendar API, Google Drive API. Takes ~30 seconds. Say `done` when ready, or `skip` to try anyway."*

4. **`gws auth login`.** Probe current state with a cheap call: `gws calendar calendarList list --params '{"maxResults": 1}'`. Exit 0 → already authenticated, jump to step 5. Otherwise tell the user:

   *"Run `! gws auth login` in this session — the `!` executes it in your shell so the browser opens. Consent to the scopes Google shows (Gmail/Calendar/Drive). Reply `done` when the CLI says 'Login successful', or `skip` to defer."*

   Do **not** run `gws auth login` yourself — it needs the user's shell for the browser, not a tool call.

5. **Verify.** Re-run `gws calendar calendarList list --params '{"maxResults": 1}'`.

   - Exit 0 → ✅ *"`gws` is authenticated. You're ready to run `/brain-morning-start`, `/brain-pull-my-meeting-notes`, `/brain-prepare-my-deep-dives`, `/brain-prepare-my-one-on-one`."*
   - Exit 2 (auth error) → ❌ *"Auth looks broken. Re-run `! gws auth login`. If it fails citing a missing API, go back to step 3."*
   - Other exit → print the stderr and tell the user what went wrong.

#### bq auth block (run when `sources.bigquery.enabled: true`)

The `gcloud-cli` system entry (installed by `super install`) provides both `gcloud` and `bq`. This block handles project selection and ADC login.

1. Verify both binaries on PATH (`command -v gcloud && command -v bq`). If missing, tell the user to run `super install` again and skip the rest.
2. Read `<project>/.env.local` and check `GCP_PROJECT_ID`. If it's empty or still `<your-gcp-project>`, ask: *"Which GCP project should `bq` default to?"* and `Edit` the value in `.env.local`.
3. Check ADC status with `gcloud auth application-default print-access-token` (exit 0 = authed). If not authed, prompt: *"Run `! gcloud auth application-default login` in this session — it opens a browser. Say 'done' when finished, or 'skip' to defer."*
4. Verify with `bq ls --project_id=<value> --max_results=1`. Exit 0 → report ✅. Non-zero → report the stderr and suggest re-running the ADC login.

### Step 9 — Teams

The `teams[]` list is awkward to collect question-by-question. Offer three choices via `AskUserQuestion`:

1. **Keep current** — leave the `teams:` block untouched
2. **Paste YAML** — user pastes a full `teams:` block; replace the existing block verbatim
3. **Clear** — set `teams: []`; user will edit later

For option 2: read the existing `teams:` block span (from `^teams:` to either the next top-level key or EOF), then replace. Validate the pasted YAML parses as a list before writing.

### Step 10 — sources.md

Ask: *"Generate a starter `sources.md` at `<project>/sources.md`?"* (Yes/No).

- If `<project>/sources.md` already exists → tell the user and skip regardless of their answer.
- If Yes and missing:
  1. Read `~/.super/skills/brain-pull-sources/references/sources.md`
  2. Substitute placeholders using the collected answers:
     - `<your-org>` → the Linear slug (or ask separately for the Confluence/Atlassian subdomain if different)
     - `<org>` in github lines → the first GitHub org from Step 7
     - `<your-folder-id>` → ask the user for a top-level GDrive folder ID (skip the line if they don't have one)
     - `<SPACE_KEY>` → ask for the Confluence space key (skip the line if Confluence disabled)
     - `<TEAM_KEY>` → leave as-is (per-team; user fills in manually)
     - `<your-domain>` → ask for the Metabase hostname (skip if Metabase disabled)
  3. Write to `<project>/sources.md`

### Step 11 — `super install` (second pass, only if new env vars landed)

If the Q&A wrote new values to `<project>/.env.local` (gws / bq credentials, Linear token if the user pasted it, etc.), the MCP entries configured in Step 2 still have the old empty-string values. Re-run `super install` so MCPs pick up the new env vars:

```bash
super install --all
```

Skip this step if nothing in `.env.local` changed since Step 2 (e.g. the user only toggled source flags but didn't paste any new secrets). When in doubt, run it — it's idempotent.

Also suggest at this point: substitute any `<your-org>` / `<your-gcp-project>` / `<your-domain>` placeholders still in `.env.local` using the values already collected in Steps 4–7 where unambiguous, via targeted `Edit` calls. Leave placeholders alone when in doubt.

### Step 12 — Recap + next steps

Print a concise summary:

- Brain root: `<project>`
- Config file: `<project>/.super/brain.config.yml` — N values changed
- Dirs scaffolded: <list>
- Sources file: `<project>/sources.md` — created / skipped / existing
- Env file: `<project>/.env.local` — created / skipped / existing
- `super install` — ran (N times)

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
