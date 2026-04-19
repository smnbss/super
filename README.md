# super

Cross-CLI session bridge for **Claude Code**, **Gemini CLI**, and **Codex CLI**.

Work in one CLI, switch to another, and your conversation follows you. Sessions are plain Markdown files tracked in git.

## Install

Installation is a two-step flow so tokens don't have to exist before the installer runs.

```bash
git clone https://github.com/smnbss/super ~/.super
cd ~/your-project

super install                              # bootstrap super itself
# → edit .env.local with your credentials
super launch claude                        # or: super claude
# inside the CLI:
#   /super-setup                           # collects brain config, runs `super configure`
```

**`super install`** bootstraps super only — no credentials required:

- git-pulls `~/.super` + `npm install`
- writes `<project>/.super/super.config.yaml` from template
- installs system prereqs and CLI binaries (claude, gemini, codex) per catalog
- installs hooks into each CLI's native config
- copies built-in skills shipped in `$SUPER_HOME/skills/` into each CLI
- creates CLI-home debug symlinks and syncs skill directories
- scaffolds `<project>/.env.local` from `$SUPER_HOME/references/env.example` (never overwrites)
- adds `SUPER_HOME` to your shell profile
- prints a next-steps banner pointing at `.env.local` and `/super-setup`

**`super configure`** (also `super setup`) installs everything that needs credentials — called by the `/super-setup` skill after the user has filled in `.env.local`:

- installs enabled external skills from `super.config.yaml` (cloned from GitHub)
- installs enabled plugins (Claude Code marketplaces)
- resyncs skill directories so new skills surface in each CLI
- configures enabled MCP servers, resolving `$env:VAR` from `.env.local`
- creates `AGENTS.md` + `CLAUDE.md`/`GEMINI.md` symlinks at the project root

## Usage

### Launch Commands

```bash
# Basic launch (uses default model)
super claude                # Launch Claude Code (default: opus)
super gemini                # Launch Gemini CLI
super codex                 # Launch Codex CLI

# Launch with specific model (Claude Code only)
super claude --model sonnet # Launch Claude with Sonnet model
super claude --model opus   # Launch Claude with Opus model (explicit)
super claude --model haiku  # Launch Claude with Haiku model

# Launch with Ollama provider
super claude --provider ollama --model kimi-k2.5:cloud      # Use Kimi via Ollama
super claude --provider ollama --model minimax-m2.5:cloud  # Use MiniMax via Ollama
super claude --provider ollama --model glm-5:cloud         # Use GLM via Ollama
super claude --provider ollama --model gemma4:31b-cloud    # Use Gemma 4 via Ollama

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

## Debug symlinks

`super install` creates a convenience symlink inside each CLI's project dir:

- `<project>/.claude/.claude → ~/.claude`
- `<project>/.codex/.codex → ~/.codex`
- `<project>/.gemini/.gemini → ~/.gemini`
- `<project>/.super/.super → ~/.super`

These are **debug-only**. They let a developer `cd` into the CLI's global home from inside a project. super and every skill shipped with super **must ignore them**: never walk up through them, never enumerate into them, never write config through them. The project's real state lives at `<project>/.CLI/…` (not `<project>/.CLI/.CLI/…`).

Walk-up discovery (bash and JS) treats a symlinked `.CLI/` candidate as invalid — only a real `.CLI/` directory marks a project root.

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
| **super-setup** | Project-scoped setup wizard — run from inside your brain project. Writes `<project>/.super/brain.config.yml`, scaffolds `agents/memory/outputs/src`, generates `<project>/sources.md`, and runs `super configure` at the end to install external skills/plugins/MCPs. Run right after `super install`. |
| **super-persist** | Summarize the conversation and save it to the session file |
| **super-resume** | Read the session file and summarize what the session is about |
| **super-clone** | Create an OrbStack Ubuntu machine pre-configured for the current project |

### Brain skills

Skills for building and syncing a personal knowledge brain (formerly the `smnbss/brain` repo, merged in). **Project-scoped**: each brain is a directory containing `.super/`, with `agents/`, `memory/`, `outputs/`, `src/` alongside it. The shared config lives at `<project>/.super/brain.config.yml` — generated by `/super-setup` when you run it from inside the project (Linear slug, teams, source paths). No global state.

| Skill | Description |
|-------|-------------|
| **brain-pull-sources** | Export ClickUp, Confluence, GDrive, Linear, GitHub, Medium, Metabase into `src/` |
| **brain-rebuild-services** | Generate `.AGENT.MD` service docs from cloned GitHub repos |
| **brain-rebuild-memory** | Rebuild L1/L2 memory from `src/` + `outputs/services/` |
| **brain-reindex** | Rebuild qmd hybrid search index (requires qmd, auto-installed) |
| **brain-pull-my-meeting-notes** | Harvest Meet transcripts from Calendar + Drive |
| **brain-prepare-my-one-on-one** | Prepare 1:1 agendas from Linear + brain context |
| **brain-prepare-my-deep-dives** | Prepare deep-dive agendas per team |
| **brain-morning-start** | Daily bootstrap (sync + meeting notes + agendas) |
| **brain-push-reports** | Push agent outputs back to ClickUp |
| **brain-weekly-review** | Weekly summary from Workflowy + X + Linear |
| **brain-git-sync** | Commit and push brain changes |
| **brain-linear-create-project-context** / **-process-ideas** / **-process-tasks** | Linear workflows |

### Available but disabled

receiving-code-review, using-git-worktrees, subagent-driven-development, brainstorming, writing-skills (all from obra/superpowers). Enable in `super.config.yaml` and re-run `super configure`.

## Plugins and MCPs

Plugins (Claude Code only) and MCP servers are declared in `super.config.yaml`. `super configure` configures them across all CLIs — called by the `/super-setup` skill after you've filled in `.env.local`. See `super.config.yaml` for the full list and how to add your own.

## How it works

1. `super install` writes hooks into each CLI's native config and installs super's built-in skills
2. `super configure` (invoked by `/super-setup`) installs external skills, plugins, and MCPs from `super.config.yaml`
3. Hooks log turns to a shared `.super/sessions/*.md` file
4. `super launch` / `super switch <cli>` writes a context snapshot to `<project>/.super/session-context.md`; the CLI reads it when it starts so your conversation follows you
5. Plain Markdown throughout — readable by any AI, trackable in git

### Hooks coverage

| Event | Claude | Gemini | Codex |
|-------|:------:|:------:|:-----:|
| Session start | yes | yes | yes |
| User prompt | yes | yes | yes |
| AI response | yes | yes | partial |
| Shell commands | yes | yes | Bash only |
| File writes | yes | yes | no |
| Session end | yes | yes | no |

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
