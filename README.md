# super 🔀

A cross-CLI session bridge for **Claude Code**, **Gemini CLI**, **Codex CLI**, and **Kimi Code CLI**.

Each CLI runs its hooks, writes turns to a shared session log, and when you switch to a different CLI the session history gets injected into its context file automatically.

---

## What's New in v1.2

- **🔍 `super doctor`** — Health check for your super installation
- **⚡ Quick shortcuts** — `super @` (active), `super !` (new), `super ?` (search)
- **🎯 FZF integration** — Fuzzy session picker with preview (falls back gracefully)
- **✨ Beautiful UI** — Consistent colors, icons, and progress indicators
- **📊 Enhanced status** — Recent activity, session sizes, quick actions
- **⚠️ Health warnings** — Alerts for large/slow sessions

---

## Installation

### 1. Clone super

```bash
git clone https://github.com/smnbss/super ~/.super
```

### 2. Add to PATH

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
export SUPER_HOME="$HOME/.super"
export PATH="$SUPER_HOME:$PATH"
```

### 3. Install hooks in your project

```bash
cd ~/my-project
super install
```

This sets up:
- CLI hooks in `.claude/`, `.gemini/`, `.codex/`, `.kimi/`
- Context files: `AGENTS.md` (master), `CLAUDE.md` and `GEMINI.md` (symlinks)
- Sessions folder: `.super/sessions/`

### Ubuntu (Orb)

```bash
sudo apt-get install git
cd ~
sudo rm -r .super
rm -r ubuntu_brain
git clone https://github.com/smnbss/super ~/.super
export SUPER_HOME="$HOME/.super"
export PATH="$SUPER_HOME:$PATH"
mkdir ubuntu_brain
cd ubuntu_brain
super install
```

---

## Quick Start

```bash
# Launch with any CLI
super claude              # New session with Claude
super gemini              # New session with Gemini
super codex               # New session with Codex
super kimi                # New session with Kimi

# Resume work
super resume              # Fuzzy picker for sessions
super @                   # Jump to active session (fast!)

# Switch CLIs mid-stream
super switch gemini       # Continue in Gemini
super switch claude       # Back to Claude

# Session management
super status              # See active session + recent activity
super log                 # View full session
super log 5               # Last 5 turns only
super save "checkpoint"   # Save with note
super catchup             # Quick summary

# Health & maintenance
super doctor              # Check installation health
super cleanup 30          # Remove sessions older than 30 days
```

---

## Quick Shortcuts

| Shortcut | Action | When to use |
|----------|--------|-------------|
| `super @` | Jump to active session | "I want to continue where I left off" |
| `super !` | New session, pick CLI | "Start something new" |
| `super ?` | Fuzzy search sessions | "Find that session from last week" |

These are designed for muscle memory — no menus, just flow.

---

## FZF Integration

If you have [fzf](https://github.com/junegunn/fzf) installed, super uses it automatically:

```bash
# Session picker with preview
super resume
# Shows: fuzzy search + preview of last 3 turns

# CLI picker
super !
# Shows: interactive CLI selector
```

**Install fzf:**
```bash
brew install fzf
```

Without fzf, super falls back to clean text menus.

---

## The Flow

```
┌─────────────────────────────────────────────────────────┐
│  $ super claude                                         │
│  🔀  Starting session: auth-refactor.md                 │
│  🟠  Claude Code                                        │
│      24 turns                                           │
└─────────────────────────────────────────────────────────┘
                          │
                          │ work, work, work
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  $ super switch gemini                                  │
│  🔀  Crossing the bridge to Gemini CLI...               │
│      Session: auth-refactor.md                          │
│  🔵  Gemini CLI                                         │
│                                                          │
│  [Gemini sees full conversation history in GEMINI.md]   │
└─────────────────────────────────────────────────────────┘
```

---

## Commands Reference

### Core Commands

| Command | Description |
|---------|-------------|
| `super` | Main menu (shows active session if exists) |
| `super <cli>` | Launch CLI directly (claude, gemini, codex, kimi) |
| `super resume [file]` | Resume session (with fzf picker if no file) |
| `super switch <cli>` | Continue active session in different CLI |

### Session Management

| Command | Description |
|---------|-------------|
| `super status` | Show CLIs, sessions, recent activity |
| `super sessions` | List all sessions |
| `super log [N\|file]` | View session (last N turns or specific file) |
| `super save [note]` | Save checkpoint to session |
| `super catchup` | Quick summary of active session |

### Shortcuts

| Command | Description |
|---------|-------------|
| `super @` | Jump to active session |
| `super !` | New session, pick CLI |
| `super ?` | Fuzzy search all sessions |

### Maintenance

| Command | Description |
|---------|-------------|
| `super doctor` | Health check: hooks, symlinks, sessions |
| `super cleanup [days]` | Remove old sessions (default: 7 days) |
| `super clean` | Remove context injections |
| `super uninstall` | Remove all super hooks |

### Configuration

| Command | Description |
|---------|-------------|
| `super install [target]` | Install hooks (all or specific CLI) |
| `super config [show\|init\|edit]` | Manage super.config.yaml |
| `super validate` | Run project validators |

---

## Session File Format

`.super/sessions/2026-04-11_auth-refactor.md`:

```markdown
# Super Session: auth-refactor

**Project:** my-project
**Started:** 2026-04-11 14:32:00
**Directory:** ~/Projects/my-project
**File:** 2026-04-11_143200_auth-refactor.md

---

## 🟠 `[14:32:15]` 👤 User

How do I refactor this auth module?

### 🟠 `[14:32:18]` 🤖 Assistant

I'd suggest splitting it into three concerns...

> **Tool** `[14:32:19]`
> ```
> Bash: grep -r "authMiddleware" src/
> ```

---

## 💾 Manual Save `[2026-04-11 15:00:00]`

> **Note:** checkpoint before major changes

---

## 🔵 `[14:45:02]` 👤 User

Continue the auth refactor, focus on token validation
```

Plain Markdown. Readable by any AI. Trackable in git.

---

## Context Injection

When you run `super <cli>`, the last ~80 lines of your session are injected:

```markdown
<!-- super:session-context -->
## 📋 SuperCLI Cross-Session Context

Session: `2026-04-11_auth-refactor.md`

You are continuing a conversation that may have started in a different AI coding
assistant. The history below is the shared session log. Pick up where things
left off.

[...session history...]
<!-- /super:session-context -->
```

The injection block is automatically replaced on each launch.

---

## Hooks Coverage

| Event | Claude Code | Gemini CLI | Codex CLI | Kimi Code |
|---|:---:|:---:|:---:|:---:|
| Session start | ✅ | ✅ | ✅ | ✅ |
| User prompt | ✅ | ✅ | ✅ | ✅ |
| AI response | ✅ Stop | ✅ AfterAgent | ⚠️ partial | ✅ Stop |
| Shell commands | ✅ | ✅ | ✅ Bash only | ✅ |
| File writes | ✅ | ✅ | ❌ not yet | ✅ |
| Session end | ✅ | ✅ | ❌ | ✅ |

---

## Design Philosophy

super is designed for **flow**:

1. **Minimal friction** — `super @` continues your work
2. **No lock-in** — Plain Markdown sessions, standard hooks
3. **Invisible when not needed** — Hooks log silently
4. **Helpful when needed** — Doctor, status, catchup

---

## Troubleshooting

### super doctor

Run `super doctor` to check:
- ✓ CLI hooks installed
- ✓ Context files symlinked correctly
- ✓ Sessions healthy (no huge files)
- ⚠️ Old sessions that need cleanup

### Large sessions

If a session grows >1MB, context injection slows down. super warns you:

```bash
⚠️  auth-refactor.md is 2.3MB — context injection may be slow
```

Start a new session or archive old turns.

### No fzf?

super works fine without it. Install for fuzzy finding:

```bash
brew install fzf
```

---

## Extending

All hook scripts are plain bash in `hooks/<cli>/`. To add events:

1. Write `hooks/<cli>/your_event.sh` — read JSON from stdin
2. Add to config template
3. Re-run `super install`

---

## License

MIT — use it, fork it, make it better.
