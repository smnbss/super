---
name: brain-reindex
description: Rebuild the qmd hybrid search index (BM25 + vector) over the brain — agents, memory, outputs, src. Use when the user says "reindex", "rebuild qmd", "update the index", "brain-reindex", or "brain-index", or after a large sync that added new files.
---

# /brain-reindex

Rebuild the qmd hybrid search index over the 4 top-level brain folders: `agents/`, `memory/`, `outputs/`, `src/`.

## When to Use

- After `brain-pull-sources` adds a large batch of new files
- After `brain-rebuild-memory` or `brain-rebuild-services` rewrites memory
- When `qmd query` returns stale or missing results
- First-time setup on a new machine

## Prerequisites

- `qmd` must be on PATH. Super installs it automatically via `npm install -g @tobilu/qmd` during `install.sh`. Reinstall super if qmd is missing.
- The brain is the project root — the dir containing `.super/`. The script walks up from `$SUPER_PROJECT_DIR` (or cwd) to find it.
- `<project>/.super/brain.config.yml` is read for `organization.name` + `organization.role` (used in qmd `globalContext`). If missing, sensible fallbacks are used. Run `/super-setup` to create it.

## What it does

1. Writes `~/.config/qmd/index.yml` with the full collection map
2. Runs `qmd update` to scan files
3. Runs `qmd embed` to build BM25 + vector indexes

First run downloads ~2GB of GGUF embedding models (one-time).

## Run

```bash
./bin/qmd-reindex
```

Run from anywhere inside your brain project — the script finds the root via the nearest `.super/`. Override with `SUPER_PROJECT_DIR` if needed:

```bash
SUPER_PROJECT_DIR="$HOME/code/another-brain" ./bin/qmd-reindex
```

## Collections

Four top-level collections map 1:1 to the 4 brain folders. Per-subfolder context hints are set via qmd's `contexts:` map.

| Collection | Path       | Pattern              | Subfolder contexts                                                                 |
|------------|------------|----------------------|------------------------------------------------------------------------------------|
| `agents`   | `agents/`  | `**/*.md`            | —                                                                                  |
| `memory`   | `memory/`  | `**/*.md`            | `L1/` (MOCs), `L2/` (domain knowledge)                                             |
| `outputs`  | `outputs/` | `**/*.{md,AGENT.MD}` | `services/`, `agents/`, `projects/`                                                |
| `src`      | `src/`     | `**/*.md`            | `clickup/`, `confluence/`, `gdrive/`, `github/`, `gws/`, `linear/`, `medium/`, `metabase/` |

Missing folders are auto-created before indexing (empty dirs are fine — qmd skips them).
