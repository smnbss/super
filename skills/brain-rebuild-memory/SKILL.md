---
name: brain-rebuild-memory
description: Rebuild the memory layers L2 (domain knowledge) and L1 (navigation MOCs) from source exports and service docs. Use when memory needs to be refreshed from the latest inputs.
---

# /update-memory

Rebuild the memory layers L2 and L1 from `outputs/` and `src/`.

## Config

Driven by `$BRAIN_CONFIG` (default `~/.super/brain.config.yml`). Relevant keys:

- `brain.path` — brain repo root
- `teams[]` — canonical engineering teams (name, slug, calendar_patterns, linear_teams). Drives `team-<slug>.md` scaffolding.
- `sources.clickup.monkeys_wiki_path` / `team_docs_prefix` — org-specific ClickUp folder names.
- `sources.confluence.intranet_path` / `wiki_path` — Confluence folder names.
- `sources.gdrive.exco_folder` / `projects_folder` / `one_pagers_folder` — named GDrive folders.
- `sources.personio.roster_file` / `columns` — HR roster source and schema. Disable `sources.personio.enabled` if the org uses a different HR system.
- `sources.<name>.enabled` — turn whole sources on/off.

Examples below show the WeRoad defaults. Substitute whatever the user's config says.

**Inputs (read-only):**
- `src/` — raw exports (ClickUp, Confluence, GDrive, GitHub, GWS, Linear, Medium, Metabase, Personio)
- `outputs/services/` — per-service technical docs + cross-cutting concerns
- `outputs/agents/` — agent time-series reports (SEO, bugs, meetings, press, etc.)

**Outputs:** `memory/L2/` (domain knowledge) + `memory/L1/` (navigation MOCs)

Outputs are read-only inputs — this command never modifies them.

## Prerequisites

1. `src/` must be populated — invoke `brain-pull-sources` first if empty.
2. `outputs/services/` must be populated — invoke `brain-rebuild-services` first if empty.

---

## Phase 1 — Inventory

Scan inputs and record what's available. This drives everything else.

### 1a. src/ inventory

For each top-level directory in `src/`, count files and list immediate children:

| Source | Structure |
|--------|-----------|
| `src/clickup/` | `Docs BUKTU/`, `Docs Tium/`, `🐵 Monkeys Wiki/` |
| `src/confluence/` | `Intranet/`, `Monkeys Wiki/` |
| `src/gdrive/` | `Monkeys/`, `Monkeys Heads/`, `Monkeys_Projects/`, `<Org> ExCo/`, `<Org>/` |
| `src/github/` | `<org>/` (repos), personal repos |
| `src/gws/` | `gmeet/` (2025/, 2026/) — meeting transcripts by year |
| `src/linear/` | `<org>/` (`MOL-issues/`, `all/`) |
| `src/medium/` | `smnbss/` — Simone's blog posts |
| `src/metabase/` | `<org>/` — collection/dashboard/card index |
| `src/personio/` | `staff-roster.tsv` — HR roster |

Verify these match reality — discover any new directories that appeared since last run.

### 1b. Service docs inventory

Count `.AGENT.MD` files in `outputs/services/` and list `outputs/services/cross/` entries:

- ~77 service docs: `<org>-<service>.AGENT.MD` (code/stack) + `<org>-<service>.DB.AGENT.MD` (database schema)
- 3 cross-cutting: `<org>-rabbitmq-topology.md`, `<org>-rabbitmq-schema.md`, `<org>-rabbitmq-producers-consumers.md`

Record all counts — they go in the Phase 5 digest.

---

## Phase 2 — L2 Rebuild (Domain Knowledge)

Each L2 file draws from specific inputs. Read those inputs, synthesize, write the L2 file.

### 2a. Team files (`team-*.md`)

**Inputs:** `src/personio/staff-roster.tsv` + `src/clickup/Docs {TeamName}/` + `src/linear/<org>/` + `outputs/services/*.AGENT.MD` (ownership)

For each team, produce `memory/L2/team-<name>.md`:
- **Members** — from `staff-roster.tsv` + any org config in github repos
- **Services owned** — from service docs tagged to this team (scan AGENT.MD frontmatter/headers)
- **Active projects** — from `src/linear/<org>/all/` (match team labels)
- **Docs pointers** — paths to their ClickUp docs folder, Confluence pages

Known teams come from `teams[]` in `$BRAIN_CONFIG`. WeRoad defaults: Buktu, Tium, SAIan, Saitama, Voyager, DevOps, CyclOps, Stomp, Rocket, YoData, IT, Staff (non-eng).

### 2b. technologies.md

**Inputs:** `outputs/services/*.AGENT.MD` (stack sections) + `src/github/<org>/` (repo languages/frameworks)

- Aggregate tech stacks from all service docs (language, framework, DB, messaging)
- Group by layer: frontend, backend, data, infra
- Note the most common patterns

### 2c. monkeys-wiki.md

**Inputs:** `src/clickup/🐵 Monkeys Wiki/` + `src/confluence/Monkeys Wiki/`

- Section inventory from both sources
- Merge overlapping content, note which source is authoritative for what
- File counts and structure

### 2d. confluence-monkeys-wiki.md

**Inputs:** `src/confluence/Monkeys Wiki/`

- Section inventory (platforms, insights, product, etc.)
- File counts per section

### 2e. intranet.md

**Inputs:** `src/confluence/Intranet/`

- Section inventory (HR, brand, hiring, perks, policies)
- File counts per section

### 2f. one-pagers.md

**Inputs:** `src/gdrive/Monkeys_Projects/` + `src/gdrive/Monkeys/`

- List product proposals / one-pagers
- Group by product area or team if possible
- Count and date range

### 2g. exco.md

**Inputs:** `src/gdrive/<Org> ExCo/`

- List executive/board documents
- Group by type (board decks, financial reports, investor updates)
- Date range and count

### 2h. meetings.md

**Inputs:** `src/gws/gmeet/` (year/month/day structure)

- Count meetings per month
- Date range covered
- Note the structure (transcript files, attendees)

### 2i. workflowy.md

**Inputs:** `outputs/agents/my-workflowy/` (daily exports)

- Summarize latest export structure
- Date range covered

### 2j. x-content.md

**Inputs:** `outputs/agents/my-x.com/` (daily digests)

- Summarize latest digest topics
- Date range covered

### 2k. seo-reports.md

**Inputs:** `outputs/agents/seo/`, `outputs/agents/seo-geo/`, `outputs/agents/seo-site-architecture/`

- Summarize latest audit findings
- Date range covered

### 2l. tech-reports.md

**Inputs:** `outputs/agents/tech-bugs/`, `outputs/agents/tech-linear-project-updates/`, `outputs/agents/tech-post-mortem-summary/`

- Summarize latest reports
- Date range covered

### 2m. press-and-market.md

**Inputs:** `outputs/agents/biz-global-press-review/`, `outputs/agents/biz-middle-east-impact/`, `outputs/agents/biz-war-hp-optimization/`

- Summarize latest press/market reports
- Date range covered

### 2n. monthly-updates.md

**Inputs:** `outputs/agents/tech-monkeys-monthly-updates/`

- List generated decks with dates
- Note latest month covered

### 2o. cross-references.md

**Inputs:** All other L2 files (read after they're written)

- Extract tables, timelines, or facts that span multiple L2 domains
- Travel pages timeline, A/B tests, payments by market, investor reports

---

## Phase 3 — L1 Rebuild (Navigation MOCs)

L1 files are navigation maps. Each derives from L2 + outputs/services + src structure.

### Source MOCs

For each source in `src/`, create/update `memory/L1/<source>.md`:

| L1 File | Reads from |
|---------|-----------|
| `clickup.md` | `src/clickup/` structure + L2 files that cite clickup |
| `confluence.md` | `src/confluence/` structure + L2 files that cite confluence |
| `gdrive.md` | `src/gdrive/` structure + L2 files that cite gdrive |
| `github.md` | `src/github/` structure + L2 files that cite github |
| `metabase.md` | `src/metabase/` structure + L2 files that cite metabase |

Each source MOC contains:
- File counts by subfolder
- Links to every L2 file that draws from this source

### Cross-cutting MOCs

| L1 File | Derives from |
|---------|-------------|
| `teams.md` | All `memory/L2/team-*.md` files + `src/personio/staff-roster.tsv` |
| `team-members.md` | `src/personio/staff-roster.tsv` + `memory/L2/team-*.md` members sections |
| `product-areas.md` | Team L2 files (group features by product area) |
| `business-domains.md` | `memory/L2/exco.md` + `memory/L2/intranet.md` + `memory/L2/one-pagers.md` |
| `data-model.md` | `outputs/services/<org>-dbt.AGENT.MD` + `outputs/services/<org>-dashboards.AGENT.MD` + BigQuery metadata |
| `entities.md` | Full scan of all L2 files — anything appearing in 2+ sources gets an entry |
| `tone-of-voice.md` | `src/medium/smnbss/` — Simone's writing voice analysis |
| `skills.md` | `.claude/skills/*/SKILL.md` — enumerate all skills |
| `system-map.md` | `.claude/agents/`, `.claude/skills/`, `.claude/commands/` — full system index |
| `hub.md` | **Last** — reads all other L1 files, builds the top-level nav with counts |

#### `memory/L1/teams.md`

Generate this file from `memory/L2/team-*.md` + `src/personio/staff-roster.tsv` + any team data in `src/linear/` or `src/clickup/`.

The file must contain a **machine-readable mapping table** at the top (after frontmatter) with these exact columns:

```markdown
| Team name | Calendar patterns | File slug | Linear teams | Members |
|-----------|-------------------|-----------|--------------|---------|
```

- **Team name**: canonical team name (e.g., `Buktu`, `Tium`, `DevOps & IT`)
- **Calendar patterns**: comma-separated, case-insensitive patterns used in calendar summaries (e.g., `Buktu`, `SAITAMA - Deep Dive`)
- **File slug**: lowercase, no spaces, used for output filenames (e.g., `buktu`, `devops-it`)
- **Linear teams**: comma-separated Linear team names, or `—` if none (e.g., `TEAM_BUKTU`, `DEVOPS, IT`)
- **Members**: count of members from `team-members.md`, or list of names if count is small

Below the table, keep human-readable sections (services owned, deep dive links, external systems) derived from L2 files.

#### `memory/L1/team-members.md`

Generate this file from `src/personio/staff-roster.tsv` (columns: `First Name | Last Name | Position | Department | Hire Date | Status | Supervisor`) + the Members sections of `memory/L2/team-*.md` + any `src/linear/` team membership exports.

The file must contain a **machine-readable mapping table** at the top (after frontmatter) with these exact columns:

```markdown
| Name patterns | File slug | Email | Role | Team / Department | Linear teams |
|---------------|-----------|-------|------|-------------------|--------------|
```

- **Name patterns**: pipe-separated, case-insensitive identifiers that could appear in calendar summaries (e.g., `Bera | Simone Berardozzi` or `Alex | Alessandro`)
- **File slug**: lowercase, spaces → hyphens, used for output filenames (e.g., `bera`, `alex`)
- **Email**: from Personio or Linear, or `—` if unknown
- **Role**: Position from Personio (e.g., `Senior Digital Product Manager`)
- **Team / Department**: Department from Personio, or team name from L2 files if different
- **Linear teams**: comma-separated Linear team names the person belongs to, or `—` if none / not applicable

Only include Active employees from the staff roster. If a nickname or alias is known from calendar patterns but not in Personio, add it as an extra Name pattern and mark the source as `user`.

These two files are the **canonical source** for `brain-prepare-my-deep-dives` and `brain-prepare-my-one-on-one`. They must be regenerated on every rebuild so skills never use stale hardcoded mappings.

---

## Phase 4 — Verify

1. **Broken links**: grep all `[[wikilinks]]` in `memory/`, check each target exists
2. **Timestamps**: every `<!-- verified: -->` block must have today's date
3. **Frontmatter**: every file's `updated:` = today
4. **Orphans**: memory files with no corresponding source → flag (don't delete)

---

## Phase 5 — Digest

Write `outputs/agents/brain-sync/YYYY-MM-DD-rebuild.md` with:
- Source inventory table (src/ directories + file counts)
- Service docs inventory (service docs count, cross-cutting count)
- Memory stats (files before/after per layer, created/updated/flagged)
- Changes summary (what was added, updated, removed)
- Broken links found
- Items flagged for review

---

## Execution Order

```
Phase 1 (inventory src + outputs/services)
  → Phase 2 (rebuild L2 from src + outputs/services)
    → Phase 3 (rebuild L1 from L2 + outputs/services + src structure)
      → Phase 4 (verify)
        → Phase 5 (digest)
```

## Rules

- **Discover, don't assume**: Scan directories to find what exists. The table above is a guide — new sources or files may have appeared.
- **Source wins**: If a source contradicts existing memory, update memory.
- **Outputs are read-only**: Never modify service doc files — they are inputs, not outputs.
- **Skip, don't fabricate**: If a source doesn't provide data for a section, use `<!-- TODO: source not available -->`.
- **Timestamp everything**: `<!-- verified: YYYY-MM-DD | source: ... -->` on every fact block.
- **Preserve `<!-- superseded: -->` markers**: Keep them even in a rebuild.
- **Conservative on entities**: 2+ source appearances required for `entities.md`.
- **Use `qmd query`** for semantic searches across the brain. Use Grep only for exact string/regex matches.
- **Agent outputs are read-only for L2**: `outputs/agents` reports feed into L2 summaries but are never modified by this command.
