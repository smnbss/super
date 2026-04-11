# supercli

A cross-CLI session bridge for **Claude Code**, **Gemini CLI**, **Codex CLI**, and **Kimi Code CLI**.

Each CLI runs its hooks, writes turns to a shared `.supercli/session.md`, and when you switch to a different CLI the session history gets injected into its context file automatically.

---

## How it works

```
┌─────────────────────────────────────────────────────────┐
│  supercli launch claude                                  │
│                                                          │
│  1. Injects .supercli/session.md → CLAUDE.md             │
│  2. Launches claude                                      │
│  3. Hooks fire on every turn:                            │
│       UserPromptSubmit → append user msg to session.md  │
│       PostToolUse      → append tool calls              │
│       Stop             → append AI response             │
└─────────────────────────────────────────────────────────┘
         ↓ switch ↓
┌─────────────────────────────────────────────────────────┐
│  supercli launch gemini                                  │
│                                                          │
│  1. Injects .supercli/session.md → GEMINI.md             │
│  2. Launches gemini                                      │
│  3. Gemini sees full prior conversation in its context  │
└─────────────────────────────────────────────────────────┘
```

---

## Requirements

- **bash** 4+  (macOS ships bash 3 — use `brew install bash`)
- **python3** in PATH (for JSON parsing in hooks)
- **envsubst** (part of `gettext` — `brew install gettext` on macOS)
- At least one of: `claude`, `gemini`, `codex`, `kimi`

---

## Installation

### 1. Clone / place supercli

```bash
git clone https://github.com/you/supercli ~/.supercli
# or just put the supercli/ folder anywhere you like
```

### 2. Set SUPERCLI_HOME and add to PATH

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
export SUPERCLI_HOME="$HOME/.supercli"
export PATH="$SUPERCLI_HOME:$PATH"
```

### 3. Make scripts executable

```bash
chmod +x ~/.supercli/supercli
chmod +x ~/.supercli/hooks/**/*.sh
```

### 4. Install hooks in your project

```bash
cd ~/my-project
supercli install
```

This writes hooks into:
- `.claude/settings.json`  (Claude Code)
- `.gemini/settings.json`  (Gemini CLI)
- `.codex/hooks.json`      (Codex CLI)
- `.kimi/config.toml`      (Kimi Code CLI)

If those files already exist, supercli merges the hooks without overwriting your existing config.

---

## Usage

```bash
# Start with Claude Code
supercli launch claude

# or shorthand
supercli claude

# When you want to switch to Gemini
supercli switch claude gemini

# Check what's been logged
supercli log

# Last 5 turns only
supercli log 5

# See installed CLIs and session info
supercli status
```

---

## Session file format

`.supercli/session.md` is plain Markdown, readable by any AI:

```markdown
# SuperCLI Session

**Project:** my-project
**Started:** 2026-04-11 14:32:00

---

## 🟠 `[Claude Code 14:32:15]` 👤 User

How do I refactor this auth module?

### 🟠 `[Claude Code 14:32:18]` 🤖 Assistant

I'd suggest splitting it into three concerns...

> **Tool** `Claude Code` `[14:32:19]`
> ```
> Bash: grep -r "authMiddleware" src/
> ```

---

## 🔵 `[Gemini CLI 14:45:02]` 👤 User

Continue the auth refactor, focus on the token validation part
```

---

## Hooks coverage per CLI

| Event | Claude Code | Gemini CLI | Codex CLI | Kimi Code |
|---|:---:|:---:|:---:|:---:|
| Session start | ✅ | ✅ | ✅ | ✅ |
| User prompt | ✅ | ✅ | ✅ | ✅ |
| AI response | ✅ Stop hook | ✅ AfterAgent | ⚠️ partial | ✅ Stop hook |
| Shell commands | ✅ | ✅ | ✅ Bash only | ✅ |
| File writes | ✅ | ✅ | ❌ not yet | ✅ |
| Session end | ✅ | ✅ | ❌ | ✅ |

**Codex CLI limitation:** As of April 2026, `PreToolUse`/`PostToolUse` only fire for Bash calls, not file writes via `apply_patch`. This is a known upstream issue (#16732). The session will still capture prompts, AI responses, and shell commands.

---

## Context injection

When you run `supercli launch <cli>`, the last ~80 lines of `.supercli/session.md` are injected into the CLI's context file between special markers:

```
<!-- supercli:session-context -->
## 📋 SuperCLI Cross-Session Context
...history...
<!-- /supercli:session-context -->
```

On the next launch, the old block is replaced with a fresh one. Run `supercli clean` to remove injection blocks without uninstalling hooks.

---

## Global install for all projects

If you want hooks active in every new project automatically, install at user scope too:

```bash
# Claude Code - user scope
supercli install claude  # then copy .claude/settings.json to ~/.claude/settings.json

# Gemini CLI - user scope
supercli install gemini  # then copy .gemini/settings.json to ~/.gemini/settings.json
```

---

## Uninstall

```bash
# Remove from one CLI
supercli uninstall claude

# Remove from all
supercli uninstall

# The session.md file is kept - you don't lose history
```

---

## Extending

All hook scripts are plain bash in `hooks/<cli>/`. To add a new event:

1. Write `hooks/<cli>/your_event.sh` — read JSON from stdin, call `session_append_turn`
2. Add the event to the corresponding config template
3. Re-run `supercli install`

The `lib/session.sh` library is the only shared dependency.
