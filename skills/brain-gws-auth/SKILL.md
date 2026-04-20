---
name: brain-gws-auth
description: Walk the user through Google Workspace (`gws`) OAuth setup — creates or verifies the OAuth client ID/secret in `.env.local` and runs `gws auth login`. Use when the user says "set up gws", "gws auth", "authenticate gws", "google workspace auth", or right after `super install` on a machine that doesn't yet have Google Workspace credentials. Idempotent: skips steps already satisfied.
---

# /brain-gws-auth

Interactive Google Workspace OAuth setup for the `gws` CLI. Brain skills that touch Gmail, Calendar, and Drive (`brain-morning-start`, `brain-pull-my-meeting-notes`, `brain-prepare-my-deep-dives`, `brain-prepare-my-one-on-one`) all require a logged-in `gws` — this skill is the shortest path to getting there.

## When to use

- Right after `super install` on a fresh machine (the install banner points here)
- When a brain skill fails with "Access denied. No credentials provided." from `gws`
- When the user rotates their OAuth client or switches Google accounts

## Prerequisites

The current directory (or an ancestor **strictly between cwd and `$HOME`**) must contain a **real** `.super/` directory — same walk-up rules as `/super-setup`. Never treat `$HOME` as the brain root, never step through the `.claude/.claude` / `.codex/.codex` / `.gemini/.gemini` / `.super/.super` debug symlinks.

If no project root is found, tell the user to run `super install` from inside their brain project and stop.

## Flow

Use `AskUserQuestion` for every user-facing question. Do targeted `Edit` calls on `<project>/.env.local` so the user can see exactly what changes. Never print secrets back to the transcript.

### Step 1 — Binary

Verify `gws` is on PATH (`command -v gws`). If missing:

- Tell the user to run `super install` (the `googleworkspace-cli` system entry installs it via Homebrew on macOS and from the prebuilt tarball on Linux)
- Stop here. Re-run this skill after `super install` completes.

### Step 2 — Credentials in `.env.local`

Read `<project>/.env.local` and inspect the two keys:

- `GOOGLE_WORKSPACE_CLI_CLIENT_ID`
- `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET`

If **both** are non-empty, say *"Credentials present in `.env.local`. Skipping to auth check."* and jump to Step 4.

Otherwise ask: *"No OAuth credentials in `.env.local`. I'll walk you through creating an OAuth 2.0 Client ID in Google Cloud Console. Ready? — yes / have credentials already / skip."*

- **yes** → show the numbered walkthrough below, then prompt for each value with a dedicated `AskUserQuestion`
- **have credentials already** → skip the walkthrough, prompt for the two values directly
- **skip** → exit, telling the user to fill the keys in `.env.local` manually and re-run

Walkthrough (show verbatim, one screen at a time):

```
1. Open https://console.cloud.google.com/apis/credentials
2. Select (or create) a project — any project works; `gws` only uses the OAuth client
3. Click "Create credentials" → "OAuth client ID"
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

Ask for each value with a dedicated `AskUserQuestion` (so nothing is logged back to the transcript), then `Edit` `<project>/.env.local`:

- Replace `GOOGLE_WORKSPACE_CLI_CLIENT_ID=` with `GOOGLE_WORKSPACE_CLI_CLIENT_ID=<value>`
- Replace `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET=` with `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET=<value>`

Confirm the two lines are now populated (without echoing the values).

### Step 3 — Enable required Google APIs

Before the first `gws auth login`, the OAuth project must have the APIs enabled or login will fail with `PERMISSION_DENIED`. Tell the user once:

*"In the same Google Cloud project, open "APIs & Services → Library" and enable these APIs (click each, then Enable):*
- *Gmail API*
- *Google Calendar API*
- *Google Drive API*
- *Google Docs API (optional — only needed if you pull Docs content)*

*Takes ~30 seconds. Say `done` when ready, or `skip` to try anyway and enable later if login fails."*

### Step 4 — `gws auth login`

Check current auth state by running a cheap call: `gws calendar calendarList list --params '{"maxResults": 1}'`.

- Exit 0 → already authenticated. Tell the user *"`gws` is already authenticated. ✅"* and jump to Step 5.
- Non-zero / auth error → proceed.

Tell the user:

*"Run `! gws auth login` in this session — `!` executes the command here so the browser opens in your environment. Consent to the scopes Google shows (Gmail/Calendar/Drive read access). Reply `done` when the CLI says "Login successful", or `skip` to defer."*

Do NOT run `gws auth login` yourself — it needs to run in the user's shell (the `!` prefix), not inside a tool call, so the browser opens and the token lands in the right place.

### Step 5 — Verify

Re-run `gws calendar calendarList list --params '{"maxResults": 1}'`:

- Exit 0 → ✅ *"gws is authenticated and the Calendar API responds. You're ready to run `/brain-morning-start`, `/brain-pull-my-meeting-notes`, `/brain-prepare-my-deep-dives`, `/brain-prepare-my-one-on-one`."*
- Exit 2 (auth error) → ❌ *"Auth looks broken. Re-run `! gws auth login`. If login fails mentioning a missing API, go back to Step 3 and enable the API it names."*
- Other exit → print the stderr and suggest opening a GitHub issue with `gws --version` output.

### Step 6 — Recap

Summarize in 4 lines:

- `.env.local` — credentials written / already present / skipped
- APIs enabled — user confirmed / user skipped
- `gws auth login` — done / skipped
- Verification — ✅ / ❌ / skipped

Suggest the user test immediately: `/brain-pull-my-meeting-notes --since yesterday` is the cheapest end-to-end check.

## Rules

- **Project-scoped only** — all writes land in `<project>/.env.local`. Never touch `~/.super/` or any debug symlink.
- **Never print secrets** — client ID + secret go in via `AskUserQuestion` answers and flow straight into `Edit` calls. Never repeat their values in the transcript.
- **Idempotent** — re-running this skill should be cheap when everything is already set up. Use the Step 4 verification call as the fast-path exit.
- **Abortable** — at any step the user can say "stop" / "skip" / "I'll finish by hand" and the skill exits cleanly, reporting what's been done so far.
- **Don't auto-run `gws auth login`** — it must run in the user's shell (via `!`) so the browser opens and the credentials land in `~/.config/gws/` (or the platform equivalent).
