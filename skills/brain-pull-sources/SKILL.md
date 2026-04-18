---
name: brain-pull-sources
description: >
  Sync the knowledge brain — re-export all external sources (ClickUp, Confluence, GDrive, Linear, GitHub, Medium, Metabase),
  backfill missing meeting digests, and refresh L1–L2 memory files and service docs from the latest data. Use this skill whenever the user
  says "pull sources", "update sources", "refresh sources", "export sources",
  or asks to bring the knowledge graph up to date. Also trigger when the user asks about stale data or missing meeting digests.
---

You are the brain's self-healing mechanism. Your job is to keep the L1–L2 knowledge files and service docs fresh by diffing source exports and agent outputs against the curated memory layer.

**Run frequency:** Daily (or on-demand).

## Paths and scripts

All paths below are relative to the repo root (`git rev-parse --show-toplevel`).

| What | Path |
|------|------|
| Agent scripts | `bin/` (relative to this skill) |
| Python utilities | `utils/` (relative to this skill) |
| Reference templates | `references/` (relative to this skill) |
| Source manifest | `sources.md` (repo root) |
| Secrets | `.env.local` (repo root, gitignored) |
| Export output | `src/clickup/`, `src/confluence/`, `src/gdrive/`, `src/github/`, `src/linear/`, `src/medium/` |
| Last export manifest | `src/.last_export.json` |

**Resolving the skill path at runtime:**

```bash
SKILL_DIR="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"
```

When installed via `npx skills add`, the skill lives at `.claude/skills/brain-pull-sources/`.
When installed via the Claude marketplace, resolve the path dynamically.

### Environment check (run first)

If `sources.md` does not exist at the repo root, create one by copying `references/sources.md` from this skill's directory

Before doing anything else, verify `.env.local` exists and has all required keys
Only proceed to the pipeline once all keys are present and non-empty.

| Variable | Used by | Purpose |
|----------|---------|---------|
| `CLICKUP_TOKEN` | `clickup_doc_to_md`, `clickup_prj_to_md` | ClickUp API personal token |
| `CONFLUENCE_EMAIL` | `confluence_space_to_md` | Atlassian account email |
| `CONFLUENCE_BASE_URL` | `confluence_space_to_md` | e.g. `https://<your-org>.atlassian.net/wiki` |
| `CONFLUENCE_TOKEN` | `confluence_space_to_md` | Atlassian API token |
| `LINEAR_TOKEN` | `linear_to_md` | Linear personal API key |
| `METABASE_URL` | `metabase_index` | Metabase instance URL |
| `METABASE_API_KEY` | `metabase_index` | Metabase API key |
| `GITHUB_TOKEN` | `github_clone` | GitHub PAT (optional — public repos work without) |
| `GCP_PROJECT_ID` | general | GCP project for BigQuery/logging |

---

Source commands in `sources.md`:
- `clickup_doc_to_md <url>` — export ClickUp docs
- `clickup_prj_to_md <url>` — export ClickUp project/folder roadmap lists
- `confluence_space_to_md <url>` — export Confluence spaces
- `gdrive_to_md <url>` — export Google Drive folders (converts Office formats via markitdown)
- `github_clone <url>` — full-clone or update a GitHub repo into `src/github/<owner>/<repo>/`
- `medium_to_md <url>` — export Medium feed
- `linear_to_md <url>` — export Linear projects
- `linear_issues_to_md <url>` — export ALL issues for a Linear team (including triage)
- `metabase_index <url>` — export full Metabase index

GitHub repos are full clones (~48 repos from the IDP service catalog).

---

## Pipeline

The sync runs in three phases.

### Phase 1 — Source sync

**Step 1: Re-export sources**

Run the export pipeline from the repo root:

```bash
bin/pull_sources sources.md   # run from the skill directory
```

This reads `sources.md` line by line, strips `#` comments, and runs each command via `bin/<tool>`. It writes `src/.last_export.json` with a timestamp and success/failure counts.

If any source fails (expired token, network error), it's logged and skipped — a partial sync is better than no sync.

**Step 2: Diff — identify stale facts**

For each L2 file in `memory/L2/`, scan the `<!-- verified: ... | source: ... -->` comments. Compare the `verified:` date against source file change dates.

- **Git repos** (`src/github/`): use `git log -1 --format=%ci -- <file>` (git doesn't preserve mtime)
- **Other sources**: use `src/.last_export.json` timestamp

Only process sources that changed since last run — do NOT re-read all files.

Classify each fact block:
- **Fresh**: source unchanged since `verified:` date — skip
- **Stale**: source changed since `verified:` date — needs update
- **Dead reference**: source file no longer exists — flag for human review
- **New content**: source files not referenced by any L2 fact block — flag as potential additions

Also check `staleness_threshold:` in each L2 file's frontmatter (default 14 days).

**Step 3: Update stale facts**

For each stale fact block:
1. Read the fresh source file(s)
2. Compare the current L2 content against the fresh source
3. If the source **contradicts** the L2 fact: flag for human review in the digest (do NOT auto-update contradictions)
4. If the source **confirms or extends** the L2 fact: update the fact block text and set `verified:` to today
5. Dead references: mark with `<!-- dead_reference: YYYY-MM-DD -->`

**Step 4: Entity reconciliation**

Scan only the **diff set** (files changed since last run) for entities in `memory/L1/entities.md`:
- Known entity in a new source → add source to entity's entry
- Source no longer exists → mark as dead reference
- New entity discovered (3+ changed files) → add with `<!-- needs_review -->` tag

**Step 5: Scan agent outputs for Brain Updates**

Check agent output files modified since the last brain-sync run for `## Brain Updates` sections.

Format: `- L2/<file>.md: <ACTION> <description>` where ACTION is ADD, UPDATE, or REMOVE.

Apply these updates during reconciliation. REMOVE marks facts as `<!-- superseded: YYYY-MM-DD -->`.

### Phase 2 — Memory update (all layers)

**Step 6: Per-service docs**

For each `src/github/` repo that changed since last sync:
- Check if `outputs/services/<service>.AGENT.MD` exists and compare `verified:` date against `git log -1`
- Stale service docs: re-read repo source and update stack, schema, messaging, auth, APIs sections
- New repos without service docs: flag in the digest as candidates for doc creation

**Step 7: Cross-cutting concerns**

After service doc updates, check if changes affect `outputs/services/cross/` topics (RabbitMQ topology, message schemas, producers/consumers). If messaging config, exchanges, or queue bindings changed, update the relevant cross file and mermaid diagrams.

**Step 8: L1 — Navigation MOCs**

If Phase 2 added new L2 files, service docs, or entities, update `memory/L1/` MOCs (hub.md, entities.md, system-map.md, github.md) to keep navigation links and counts accurate.

### Finalize

**Step 9: Generate digest**

Write to `outputs/agents/brain-sync/YYYY-MM-DD.md`:

```markdown
# Brain Sync — {YYYY-MM-DD}

## Summary
- Sources re-exported: X succeeded, Y failed
- L2 files scanned: N
- Stale facts found: N (updated: M, flagged: K)
- New content discovered: N files not referenced by any L2
- Entity updates: N
- Agent write-back hints processed: N
- Meeting days backfilled: N

## Source Export Status
| Source | Status | Files Changed |
|--------|--------|--------------|
| ClickUp | ... | N |
| Confluence | ... | N |
| ... | ... | ... |

## L2 Updates Applied
{List each L2 file updated, what changed, and the source that triggered the update}

## Service Doc Updates Applied
{List each service doc updated or flagged for creation}

## Flagged for Human Review
{Contradictions, dead references, new content needing manual curation}

## Entity Index Changes
{New entities, dead references, cross-references added}

## What Changed in Your World
{2-3 sentence narrative: what should the CTPO know about today?}
```

---

## Rules

- **Conservative by default**: flag contradictions for human review rather than auto-updating
- **Never delete content**: use `<!-- superseded: YYYY-MM-DD -->` instead
- **Digest is mandatory**: even if nothing changed, write a "no changes detected" digest
- **Respect staleness_threshold**: each L2 file can set its own in frontmatter (default 14 days)
- **Clean up temp files**: use `/tmp/` — never commit intermediates

## When to use

Daily, or after a significant batch of new documentation is added to ClickUp, Confluence, or Google Drive.
