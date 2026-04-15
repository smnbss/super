# super

Cross-CLI session bridge for **Claude Code**, **Gemini CLI**, **Codex CLI**, and **Kimi Code CLI**.

Work in one CLI, switch to another, and your conversation follows you. Sessions are plain Markdown files tracked in git.

## Install

```bash
git clone https://github.com/smnbss/super ~/.super
cd ~/your-project
super install
```

`super install` sets up hooks for all detected CLIs, installs enabled skills/plugins/MCPs, and adds `SUPER_HOME` to your shell profile.

## Usage

### Launch Commands

```bash
# Basic launch (uses default model)
super claude                # Launch Claude Code (default: opus)
super gemini                # Launch Gemini CLI
super codex                 # Launch Codex CLI
super kimi                  # Launch Kimi Code CLI

# Launch with specific model (Claude Code only)
super claude --model sonnet # Launch Claude with Sonnet model
super claude --model opus   # Launch Claude with Opus model (explicit)
super claude --model haiku  # Launch Claude with Haiku model

# Launch with Ollama provider
super claude --provider ollama --model kimi-k2.5:cloud      # Use Kimi via Ollama
super claude --provider ollama --model minimax-m2.5:cloud  # Use MiniMax via Ollama
super claude --provider ollama --model glm-5:cloud         # Use GLM via Ollama

# Launch with title
super claude --title "fix auth"    # Named session
super gemini --title "docs update" # Named session

# Resume session
super claude --resume              # Resume with picker
super claude --resume session.md   # Resume specific session

# Session management
super switch gemini         # Continue current session in Gemini
super resume                # Pick a previous session
super @                     # Jump to active session
super !                     # New session (pick CLI)
super ?                     # Fuzzy search sessions
```

### Session management

```bash
super status                # Active session + recent activity
super log [N]               # View session (last N turns)
super save [note]           # Checkpoint with note
super catchup               # Quick summary
super doctor                # Health check
super cleanup [days]        # Remove old sessions (default: 7)
```

## Configuration

All configuration lives in `super.config.yaml` (project-level in `.super/` or global in `~/.super/`).

```bash
super config show           # View current config
super config edit           # Open in editor
```

The config file declares system deps, CLIs, skills, plugins, and MCPs. Secrets use `$env:VAR_NAME` references resolved from `.env.local` at install time.

## Skills

Skills are prompt-based capabilities installed into each CLI's native skill directory. Define them in `super.config.yaml` under `skills:`, sourced from GitHub repos.

### Default skills

| Skill | Source | Description |
|-------|--------|-------------|
| **gstack** | garrytan/gstack | Dev workflow toolkit — review, ship, debug, QA, and more |
| **requesting-code-review** | obra/superpowers | Structured code review methodology |
| **playwright-cli** | microsoft/playwright-cli | Browser testing with Playwright |
| **verification-before-completion** | obra/superpowers | Verify work before claiming done |
| **systematic-debugging** | obra/superpowers | Root cause investigation methodology |
| **test-driven-development** | obra/superpowers | Write tests first, then implement |
| **writing-plans** | obra/superpowers | Structured plan creation |
| **executing-plans** | obra/superpowers | Stay scoped when executing plan tasks |

### Built-in skills

| Skill | Description |
|-------|-------------|
| **super-persist** | Summarize the conversation and save it to the session file |
| **super-resume** | Read the session file and summarize what the session is about |
| **super-clone** | Create an OrbStack Ubuntu machine pre-configured for the current project |

### Available but disabled

receiving-code-review, using-git-worktrees, subagent-driven-development, brainstorming, writing-skills (all from obra/superpowers). Enable in `super.config.yaml` and re-run `super install`.

## Plugins and MCPs

Plugins (Claude Code only) and MCP servers are declared in `super.config.yaml`. `super install` configures them across all CLIs. See `super.config.yaml` for the full list and how to add your own.

## How it works

1. `super install` writes hooks into each CLI's native config
2. Hooks log turns to a shared `.super/sessions/*.md` file
3. `super switch <cli>` injects session history into the target CLI's context
4. Plain Markdown throughout — readable by any AI, trackable in git

### Hooks coverage

| Event | Claude | Gemini | Codex | Kimi |
|-------|:------:|:------:|:-----:|:----:|
| Session start | yes | yes | yes | yes |
| User prompt | yes | yes | yes | yes |
| AI response | yes | yes | partial | yes |
| Shell commands | yes | yes | Bash only | yes |
| File writes | yes | yes | no | yes |
| Session end | yes | yes | no | yes |

## Ubuntu setup

```bash
git clone https://github.com/smnbss/super ~/.super
cat <<'EOF' >> ~/.bashrc
export PATH="$HOME/.local/bin:$PATH"
export SUPER_HOME="$HOME/.super"
export PATH="$SUPER_HOME:$PATH"
EOF
source ~/.bashrc
mkdir ~/my-project && cd ~/my-project
super install
```

Or use `/super-clone` to provision an OrbStack machine automatically.

## License

MIT
