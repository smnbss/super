---
name: brain-rebuild-memory
description: >-
  Rebuild the memory layers L2 (domain knowledge) and L1 (navigation MOCs) from
  source exports and service docs. Use when memory needs to be refreshed from
  the latest inputs.
---

# /update-memory

Rebuild the memory layers L2 and L1 from `outputs/` and `src/`.

## Execution discipline

If you parallelize target generation across worker agents (waves of L2 workers, then cascade L1s), you MUST **block on every worker and verify its file writes before moving on or returning** — check the target files exist on disk with fresh mtimes. Never dispatch a wave and return "dispatched": detached workers die with your context and write nothing (observed 2026-07-14: "Wave 1 dispatched" → 0 files on disk). The rebuild is only done when Phases 4–5 have run against files that actually exist.

## Mode

**Incremental by default.** Only targets whose inputs changed since the last run are regenerated. The state file `memory/.rebuild-state.json` records per-output inputs + max input mtime + content hash.

Trigger a full rebuild by passing `full` (or `force`) as the skill argument, or when the state file is absent / malformed. A full rebuild regenerates every L2, every L1, and the top-level `AGENTS.md`.

**Critical rule for incremental runs:** do **not** bump `verified:` dates or `updated:` frontmatter on files you skip. Preserved timestamps are how staleness tracking works — if you touch every file on every run, the signal dies.

## Config

Driven by `$BRAIN_CONFIG` (default `<project>/.super/brain.config.yml`, where `<project>` is found by walking up from cwd to the nearest **real** `.super/` directory — skip the `<project>/.super/.super` debug symlink, stop the walk before reaching `$HOME`, and realpath-skip any `.super/` that resolves to `$HOME/.super` (the global super install). If the walk returns `$HOME` or nothing, abort — never write memory at the top of the user's home directory). Relevant keys:

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
| `github/` | `<org>/` (repos), personal repos |
| `src/gmeet/` | `2025/`, `2026/` — meeting transcripts by year |
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

## Phase 1.5 — Change Detection (skip in full rebuild)

**Skip this phase entirely if running in full mode** — every target is dirty.

1. Load `memory/.rebuild-state.json`. Schema:
   ```json
   {
     "version": 1,
     "run_at": "2026-04-19T08:00:00Z",
     "targets": {
       "memory/L2/team-buktu.md": {
         "inputs": ["src/personio/staff-roster.tsv", "src/clickup/Docs BUKTU/**", "outputs/services/*.AGENT.MD"],
         "max_mtime": 1713398400,
         "content_hash": "sha256:..."
       }
     }
   }
   ```
   Missing / unparseable → treat every target as dirty (equivalent to full rebuild) and keep going.

2. For every L2 and L1 target listed in Phases 2–3 below, compute `current_max_mtime` = max `mtime` of all files matched by that target's `inputs` globs. Primary check is mtime (fast, good enough on 446K-file `github/`).

3. Mark a target **dirty** when any of:
   - target file does not exist on disk, **or**
   - target absent from state file, **or**
   - `current_max_mtime > recorded max_mtime`, **or**
   - target's inputs list has changed (new/removed globs from schema evolution).

4. **Cascade dirtiness upward:**
   - If any L2 file is dirty → every L1 file that cites it (see Phase 3 table) is also dirty.
   - If `src/<source>/` top-level structure changed (new/removed subdir) → the matching `memory/L1/<source>.md` is dirty.
   - If any L1 file is dirty → `memory/L1/hub.md` is dirty → top-level `AGENTS.md` is dirty.

5. Record the full dirty set and feed it to Phases 2–5. Clean targets are **read** (other phases may need their contents) but never rewritten.

---

## Phase 2 — L2 Rebuild (Domain Knowledge)

Regenerate only the L2 targets marked dirty in Phase 1.5. For each dirty target:
1. Read its declared inputs.
2. Synthesize.
3. Compute new content. **Compare against the existing file's content_hash** — if identical, leave the file untouched (don't churn mtime / git), but still refresh the state file's `max_mtime` for this target.
4. If content changed: write the file, set frontmatter `updated: <today>`, refresh `verified:` markers only on fact blocks whose source actually changed.

Clean targets: skip entirely. Do not touch `verified:` or `updated:`.

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

**Inputs:** `outputs/services/*.AGENT.MD` (stack sections) + `github/<org>/` (repo languages/frameworks)

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

**Inputs:** `src/gmeet/` (year/month/day structure)

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

Regenerate only the L1 targets marked dirty in Phase 1.5 (including cascades from dirty L2 files). Same content-hash short-circuit as Phase 2 — identical content = leave file alone, just refresh state. L1 files are navigation maps. Each derives from L2 + outputs/services + src structure.

### Source MOCs

For each source in `src/`, create/update `memory/L1/<source>.md`:

| L1 File | Reads from |
|---------|-----------|
| `clickup.md` | `src/clickup/` structure + L2 files that cite clickup |
| `confluence.md` | `src/confluence/` structure + L2 files that cite confluence |
| `gdrive.md` | `src/gdrive/` structure + L2 files that cite gdrive |
| `github.md` | `github/` structure + L2 files that cite github |
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

## Phase 3.5 — Top-level AGENTS.md (brain navigation doc)

Every AI coding assistant that lands in the brain project — Claude Code, Gemini CLI, Codex, others — reads a root-level nav doc at session start. This phase generates a single canonical file (`AGENTS.md`) and exposes it under the other conventional names via symlinks so we never drift between copies.

**Anchor:** `<brain_root>` = the project directory found by the existing `$BRAIN_CONFIG` walk (same anchor as the rest of this skill). Never write to `$HOME`.

### 3.5a. Regenerate `<brain_root>/AGENTS.md`

Dirty when `hub.md` is dirty, when `src/` top-level structure changed, when Phase 1 inventory counts changed vs. the values baked into the current `AGENTS.md`, or in full-rebuild mode.

Content (assemble from Phase 1 inventory + the just-rebuilt L1 files):

1. **Intro paragraph** — who the brain belongs to (read `<brain_root>/.super/brain.config.yml` for owner + org), one-line purpose.
2. **Repository Layout** — code fence showing `memory/`, `src/`, `outputs/` with live counts from Phase 1 (subdirs + file counts). L1 and L2 counts come from `ls memory/L1 | wc -l` and `ls memory/L2 | wc -l` after rebuild.
3. **How to Navigate** — 4-step path starting at `memory/L1/hub.md` + a `Quick Access` list pointing at the highest-signal L1 files (`entities.md`, `data-model.md`, `product-areas.md`, `teams.md`, `system-map.md`) plus `outputs/services/<repo>.AGENT.MD`. Then a **`### Knowledge Map`** subsection: a complete index of every L1 MOC grouped (Entry & cross-cutting · People & org · Product & business · Data & analytics · Engineering & systems · Sources · Content & voice), each L1 showing the L2 pages it connects to as `[[wikilinks]]`. Derive the groupings + L1→L2 edges from the just-rebuilt files (the Phase 3 derivation table + each L2's `Topics:` footer). This is the agent's traversal spine — it must stay accurate to the actual link graph.
4. **Freshness Tracking** — explain `verified:` fact blocks, `staleness_threshold:` frontmatter, and the `superseded:` marker convention.
5. **Searching** — always use the gbrain MCP tools (`mcp__gbrain__query`, `mcp__gbrain__search`, `mcp__gbrain__get_page`); the HTTP server is always-on so they're always available. Grep is for exact matches only.
6. **External Tools** — only include sections for tools the user actually has (detect via `command -v`): `gws` CLI, Chrome DevTools, etc. Skip sections whose CLI isn't installed.
7. **Skill Routing** — pull the routing table from `<brain_root>/.super/brain.config.yml` key `skill_routing` if present. If absent, write a short generic pointer: "skills live in `.claude/skills/` — invoke by name when the user's request matches their description."

Apply the same content-hash short-circuit as Phases 2/3: if regenerated content matches what's on disk, don't rewrite.

### 3.5b. Symlinks for other assistants

Run from `<brain_root>`:

```bash
ln -sfn AGENTS.md CLAUDE.md
command -v gemini >/dev/null 2>&1 && ln -sfn AGENTS.md GEMINI.md
```

**Never clobber a real file.** Before creating either symlink, check:
- If the path does not exist → create symlink.
- If the path is already a symlink to `AGENTS.md` → leave alone.
- If the path is a symlink to something else → overwrite with `ln -sfn` (that's the whole point of keeping them in sync).
- If the path is a **regular file** (not a symlink) → DO NOT overwrite. Flag in the Phase 5 digest as `CLAUDE.md is a real file — skipped symlink creation, user must resolve`.

Skip `GEMINI.md` entirely when `command -v gemini` returns non-zero. If a stale `GEMINI.md` symlink exists but gemini is no longer installed, leave the symlink in place — harmless, and removing it would be surprising.

Record final symlink status (`created` / `already-correct` / `skipped: gemini not installed` / `skipped: real file exists`) for the Phase 5 digest.

---

## Phase 4 — Verify

1. **Broken links**: grep all `[[wikilinks]]` in `memory/`, check each target exists
2. **Timestamps on rewritten files**: every `<!-- verified: -->` block on a file rebuilt this run must reflect today's date (or the date the underlying source changed). **Do not enforce this on skipped files** — their old dates are correct.
3. **Frontmatter on rewritten files**: `updated:` = today. Skipped files keep their prior `updated:`.
4. **Orphans**: memory files with no corresponding source → flag (don't delete)
5. **Symlink health**: `<brain_root>/CLAUDE.md` resolves to `AGENTS.md`; `GEMINI.md` resolves to `AGENTS.md` if gemini is installed.

---

## Phase 4.5 — Refresh the gbrain index (delegated to `gbrain sync`)

**This skill only writes markdown.** The brain repo is the system of record (`gbrain.yml` at the root); the gbrain DB is a derived cache. After Phase 4, the index (chunks, embeddings, wikilink edges, timeline) is refreshed by a single **`gbrain sync`** — it git-diffs the repo, imports only the rewritten files, embeds them, and extracts links/timeline natively.

- **Via `brain-morning-start`:** Part 5 runs the sync once for the whole morning's changes — do nothing here.
- **Standalone:** finish with
  ```bash
  gbrain sync --repo "$(git rev-parse --show-toplevel)" --skip-failed --no-pull --yes
  # keep the link graph curated (drop raw-export-origin links; idempotent):
  psql "$(gbrain config show 2>/dev/null | sed -n 's/^ *database_url: *//p')" -c \
    "DELETE FROM links WHERE from_page_id NOT IN (SELECT id FROM pages WHERE slug LIKE 'memory/%' OR slug LIKE 'outputs/%');"
  ```

**Sanity after a sync:** `gbrain backlinks memory/l1/hub` lists the hub MOC's incoming links; `gbrain graph memory/l1/hub --depth 1` traverses them. (`link_resolution.global_basename` must be `true` so bare `[[hub]]`/`[[teams]]` resolve.)

**Known gap:** native `gbrain extract timeline` only reads `## Timeline`-sentinel sections, so the `<!-- verified: YYYY-MM-DD -->` fact blocks are not captured as timeline entries (low-value; timeline stays sparse). **Do not** call `gbrain dream` (broken in v0.37.5.0).

---

## Phase 5 — Digest

Write `outputs/agents/brain-sync/YYYY-MM-DD-rebuild.md` with:
- Mode (`incremental` / `full`) and whether state file existed
- Source inventory table (src/ directories + file counts)
- Service docs inventory (service docs count, cross-cutting count)
- Memory stats (files before/after per layer, created/updated/skipped/flagged)
- **Incremental summary**: count of L2 skipped vs rebuilt, count of L1 skipped vs rebuilt, wall-clock savings vs full rebuild estimate
- Top-level nav: `AGENTS.md` regenerated y/n; symlink status for `CLAUDE.md` and `GEMINI.md`
- Changes summary (what was added, updated, removed)
- Broken links found
- Items flagged for review

Finally, write the updated `memory/.rebuild-state.json` with fresh `max_mtime` + `content_hash` for every target (including skipped ones — their mtimes may have advanced even if content matched).

---

## Linking & Connection Rules (gbrain optimization)

The whole point of L1/L2 is a navigable graph: gbrain materializes every `[[wikilink]]` into an edge (Phase 4.5) and uses those edges for backlink-boost ranking and `graph`/`graph-query` traversal. Maximize *correct* connection density. Apply these rules to every file written in Phases 2/3/3.5:

1. **Never emit an empty or text-only "see also" entry.** Every `## Related` bullet and every cell in an `L3 References`-style table MUST contain a resolvable `[[link]]`. If there is no target, omit the bullet/row entirely — do NOT write `-  — description` (the historical bug that left dead bullets in `technologies.md`).
2. **Reference pages as wikilinks, not code paths.** When a file points at another brain page, write `[[basename]]` — including service docs (`[[weroad-community.AGENT.MD]]`, resolves by `global_basename`) and DB docs (`[[weroad-unison.DB.AGENT.MD]]`). A bare `` `outputs/services/x.AGENT.MD` `` code-span produces NO edge. Reserve code-spans for paths you are *not* linking (raw `src/` exports without wikilink syntax).
3. **Bidirectional completeness.** Every L2 `Topics:` footer must link UP to **every L1 file that cites it** (the Phase 3 derivation table is the citation map) plus any obvious see-also L1s. Conversely every L1 must link DOWN (in a `## Related` block + body) to **every L2 it derives from**. Source MOCs (`github.md`, `metabase.md`, …) are the usual offenders — give each a `## Related` block pointing at the L2/L1 pages it feeds (e.g. `github → [[technologies]] · [[services]] · [[teams]]`; `metabase → [[data-model]] · [[team-data]]`). Footers are additive: when refreshing, never drop an existing valid link.
4. **Inline first-mention links.** In body prose, the first mention of another team, domain, service, source, or person that owns its own page gets a `[[wikilink]]`. This produces far more edges than footers alone. Example: in `technologies.md`, "AI/ML stack" → `[[team-data]]`, "main platform" → `[[team-rocket]]`, "data & analytics" → `[[data-model]]`.
5. **Concise frontmatter `description:`.** Keep `description:` a single topical sentence (≤ ~220 chars) naming the domain + its key entities — this is the page's summary vector. Put dated change-log detail in **body** sections under `<!-- verified: -->` blocks (which become chunks + timeline entries), not crammed into `description:`. Do not duplicate long WBR digests into the description.
6. **Self-contained section headings.** gbrain chunks by heading; a heading + its block should make sense out of context (name the entity/date), so a retrieved chunk is interpretable on its own.

After Phase 4's broken-link check, the graph should be strictly denser than the prior run with **zero** broken links and zero empty `[[]]`/`-  —` bullets.

## Execution Order

```
Phase 1   (inventory src + outputs/services)
  → Phase 1.5 (load state, detect dirty targets, cascade)     [skipped in full mode]
    → Phase 2   (rebuild dirty L2 from src + outputs/services)
      → Phase 3   (rebuild dirty L1 from L2 + outputs/services + src structure)
        → Phase 3.5 (regenerate AGENTS.md + CLAUDE.md/GEMINI.md symlinks)
          → Phase 4   (verify)
            → Phase 4.5 (writes markdown only; gbrain index/links/embeddings refreshed by the caller's single `gbrain sync`)
              → Phase 5   (digest + persist state)
```

## Rules

- **Discover, don't assume**: Scan directories to find what exists. The table above is a guide — new sources or files may have appeared.
- **Source wins**: If a source contradicts existing memory, update memory.
- **Outputs are read-only**: Never modify service doc files — they are inputs, not outputs.
- **Skip, don't fabricate**: If a source doesn't provide data for a section, use `<!-- TODO: source not available -->`.
- **Timestamp everything**: `<!-- verified: YYYY-MM-DD | source: ... -->` on every fact block.
- **Cite gdrive files by their Drive URL, not the local path**: any `.md` file under `src/gdrive/` is a converted-from-Drive export carrying YAML frontmatter with `gdrive_url`. When a fact derives from such a file, the `source:` field must be the `gdrive_url` value — not `src/gdrive/<path>.md`. The local path is an implementation detail; the Drive URL is what lets a human click through. For non-gdrive sources, continue to use the local path as before. When the input is a per-folder `INDEX.md` (index-only mode), cite the folder's Drive URL (the `Drive link:` line inside the INDEX) rather than the INDEX itself.
- **Preserve `<!-- superseded: -->` markers**: Keep them even in a rebuild.
- **Conservative on entities**: 2+ source appearances required for `entities.md`.
- **Maximize correct link density**: follow the "Linking & Connection Rules (gbrain optimization)" section above on every rewritten file — no empty/text-only see-also entries, wikilink (not code-path) every page reference, bidirectional Topics footers, inline first-mention links, concise `description:`.
- **Use `mcp__gbrain__query`** for semantic searches across the brain (the always-on HTTP server). Use Grep only for exact string/regex matches.
- **Agent outputs are read-only for L2**: `outputs/agents` reports feed into L2 summaries but are never modified by this command.
- **Don't touch clean files**: in incremental mode, skipped targets must keep their existing `verified:` and `updated:` values byte-for-byte. Rewriting an unchanged file defeats the entire staleness signal.
- **Content-hash short-circuit**: even for a dirty target, if the newly-synthesized content hashes identical to the file already on disk, leave the file unchanged and only update the state file.
- **Never clobber real `CLAUDE.md` / `GEMINI.md`**: if either exists as a regular file (not a symlink), flag it and move on. Only manage symlinks this skill created.
