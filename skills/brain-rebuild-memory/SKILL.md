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

⚠️⚠️ **ONE SHORT-LIVED WORKER PER TARGET FILE. Do not walk the target list in one context.**

This phase is the worst cost-weighted step in the morning routine — **4.9M input-equivalent
tokens**, of which **2.9M were CACHE WRITES over just 66 requests** (2026-08-18). A cache-write
figure that size against that few requests means the prompt cache was being **rebuilt almost
every request**, which is what an 80-minute runtime with multi-minute thinking gaps produces:
one long-lived context that grows with every target it touches, re-paying for the whole prefix
each time and outliving the cache TTL in the gaps.

The fix is structural, and this skill already has the mechanism for it — **every target
declares its own `inputs`** (see the state-file schema below). So:

- **One worker per output file.** It receives that target's `inputs` glob set and nothing else.
  It reads, writes one file, and exits. Its context stays small and stays hot.
- **Never hand a worker the whole `src/` or `outputs/` tree** "for context". The declared
  inputs ARE the context; anything else is prefix you pay to re-cache.
- **Batch by independence, not by convenience:** all L2 targets are independent of each other,
  so they go in one fan-out. L1 MOCs depend on L2 output, so they are a second fan-out after it.
  `AGENTS.md` is last because it depends on both.
- **A worker that would touch more than a handful of files is mis-scoped** — split the target,
  or fix its `inputs`.
- ⚠️⚠️ **EVERY NESTED `Agent` DISPATCH MUST PASS `subagent_type: "general-purpose"` EXPLICITLY.
  Never omit it and never let it default.** The `wr-agents` plugin ships a `PreToolUse` hook
  (`hooks/enforce-subagents.sh`) that forces an interactive confirmation whenever an `Agent` call
  **without** `subagent_type` (which defaults to `"claude"`) carries a prompt/description
  mentioning a known jungle service/repo name (`coordinators`, `cashew`, …) — which a team-L2
  target's content routinely does, since it names the services that team owns. That "ask"
  overrides `defaultMode: bypassPermissions` by design (it's meant to catch real coding work
  routed to the wrong agent), so on an **unattended** morning run it stalls forever with nobody to
  answer it. Confirmed 2026-08-20: a `team-stomp.md` worker dispatched without `subagent_type`
  tripped this hook on its "coordinators" mention and the whole rebuild sat blocked until a human
  intervened. `general-purpose` is on the hook's allow-list and passes through silently — it is
  the correct type for this skill's workers regardless (they synthesize markdown from declared
  inputs, never touch service source code), so there is no tradeoff in always setting it.

**You MUST still block on every worker and verify its file writes before moving on or
returning** — check the target files exist on disk with fresh mtimes. Never dispatch a wave and
return "dispatched": detached workers die with your context and write nothing (observed
2026-07-14: "Wave 1 dispatched" → 0 files on disk). The rebuild is only done when Phases 4–5
have run against files that actually exist.

⚠️ **Verify the whole write set, not just `memory/`.** This skill also rewrites the top-level
**`AGENTS.md`** and **`DEVELOPER.md`**. A completion check globbing `memory/**/*.md` does not
match either, and on 2026-08-18 that is exactly how a regenerated `AGENTS.md` **missed the
commit** and had to be redone in a follow-up run.

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
| ~~`src/clickup/`~~ | **RETIRED 2026-08-06 and the tree DELETED.** The wiki moved to Outline — use `src/outline/🐵 Monkeys Wiki/`. An input glob naming `src/clickup/` matches nothing, so its target silently never regenerates. |
| `src/confluence/` | `Intranet/`, `Monkeys Wiki/` |
| `src/gdrive/` | `Monkeys/`, `Monkeys Heads/`, `Monkeys_Projects/`, `<Org> ExCo/`, `<Org>/` |
| `github/` | `<org>/` (repos), personal repos |
| `src/gmeet/` | `2025/`, `2026/` — meeting transcripts by year |
| `src/linear/` | `<org>/` (`MOL-issues/`, `all/`) |
| `src/medium/` | `smnbss/` — Simone's blog posts |
| `src/metabase/` | `<org>/` — collection/dashboard/card index |
| `src/personio/` | `staff-roster.tsv` — HR roster |

Verify these match reality — discover any new directories that appeared since last run.

**Never carry an inventory count forward from the previous `AGENTS.md` / `CLAUDE.md`.** Every number written in Phase 3.5 must be re-measured from the filesystem this run. Stale counts have survived multiple rebuilds by being copied from the prior output instead of recomputed.

#### 1a-i. Monorepo clone counts (`github/weroad/jungle/`)

A subdirectory count is **not** the clone count and must never be reported as one. Compute it from the monorepo's own authoritative repo list:

```bash
# authoritative tracked-clone count
grep -oE 'weroad/[a-zA-Z0-9._-]+\.git' github/weroad/jungle/bin/repos.sh | sort -u | wc -l
# everything on disk that is NOT in that list = stale clones + monorepo working dirs
comm -13 <(grep -oE 'weroad/[a-zA-Z0-9._-]+\.git' github/weroad/jungle/bin/repos.sh \
            | sed 's|weroad/||; s|\.git$||' | sort) \
         <(ls -d github/weroad/jungle/*/ | xargs -n1 basename | sort)
```

`repos.sh` is the list `/brain-pull-sources` actually clones and refreshes. Directories on disk but absent from it fall into two kinds, and the generated text must distinguish them:
- **stale clones** — real git repos that were dropped from `repos.sh` and are therefore never refreshed again (report them by name; they are a freshness trap);
- **monorepo working dirs** — not clones at all (`_data`, `bin`, `bin-yodata`, `node_modules`, `resources`, `scripts`).

Also re-check each clone's HEAD resolves; report any that don't (`git -C <dir> rev-parse HEAD`), with the date re-confirmed this run.

### 1b. Service docs inventory

Count `.agent.md` files under `outputs/services/**` (owner subdirs — `weroad/`, `weroad/jungle/`, `smnbss/`, …) and list `outputs/services/weroad/jungle/cross/` entries:

- service docs, nested by owner (**re-measure; 64 `.agent.md` + 7 `.db.agent.md` on 2026-08-18** after 27 `.db` docs were superseded by `src/idp/<service>/database.md`): `<owner>/<service>.agent.md` (code/stack) + `<owner>/<service>.db.agent.md` (database schema). Filenames are de-prefixed (`weroad/community.agent.md`, not `weroad-community.agent.md`); the basename stays globally unique for `global_basename` resolution.
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
         "inputs": ["src/personio/staff-roster.tsv", "src/outline/**", "outputs/services/**/*.agent.md"],
         "max_mtime": 1713398400,
         "content_hash": "sha256:..."
       },
       "memory/L1/teams.md": {
         "inputs": [".super/brain.config.yml", "memory/L2/team-*.md", "src/personio/staff-roster.tsv"],
         "max_mtime": 1713398400,
         "content_hash": "sha256:..."
       }
     }
   }
   ```
   Note `memory/L1/teams.md` (and `team-members.md`) list **`.super/brain.config.yml`** — the
   `$BRAIN_CONFIG` file — as a first-class input. Config is an input like any other source: a
   `teams[]` edit must make these targets dirty, and mtime alone carries that signal only if the
   path is in the globs. See Phase 3's `teams.md` section.
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
2. Synthesize. For accretive targets, then apply "Size Caps & Archive Rotation" (section below): the live window of dated sections stays, older sections move verbatim to `memory/L2/archive/`.
3. Compute new content. **Compare against the existing file's content_hash** — if identical, leave the file untouched (don't churn mtime / git), but still refresh the state file's `max_mtime` for this target.
4. If content changed: write the file, set frontmatter `updated: <today>`, refresh `verified:` markers only on fact blocks whose source actually changed.

Clean targets: skip entirely. Do not touch `verified:` or `updated:`.

Each L2 file draws from specific inputs. Read those inputs, synthesize, write the L2 file.

### 2a. Team files (`team-*.md`)

**Inputs:** `src/personio/staff-roster.tsv` + `src/outline/**` + `src/linear/<org>/` + `outputs/services/**/*.agent.md` (ownership)

For each team, produce `memory/L2/team-<name>.md`:
- **Members** — from `staff-roster.tsv` + any org config in github repos
- **Services owned** — from service docs tagged to this team (scan agent.md frontmatter/headers)
- **Active projects** — from `src/linear/<org>/all/` (match team labels)
- **Docs pointers** — paths to their ClickUp docs folder, Confluence pages

Known teams come from `teams[]` in `$BRAIN_CONFIG`. WeRoad defaults: Buktu, Tium, SAIan, Saitama, Voyager, DevOps, CyclOps, Stomp, Rocket, YoData, IT, Staff (non-eng).

### 2b. technologies.md

**Inputs:** `outputs/services/**/*.agent.md` (stack sections) + `github/<org>/` (repo languages/frameworks)

- Aggregate tech stacks from all service docs (language, framework, DB, messaging)
- Group by layer: frontend, backend, data, infra
- Note the most common patterns

### 2c. monkeys-wiki.md

**Inputs:** `src/outline/🐵 Monkeys Wiki/` + `src/confluence/Monkeys Wiki/`

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
- Live window: current + previous ISO week of `## WNN update` sections; older harvests rotate to `meetings-YYYY-MM` archives (see "Size Caps & Archive Rotation")

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
| ~~`clickup.md`~~ | **DO NOT GENERATE.** The source was retired 2026-08-06, `src/clickup/` deleted, and the L1 MOC dropped. Listed here only so a future run does not recreate it. |
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
| `teams.md` | All `memory/L2/team-*.md` files + `src/personio/staff-roster.tsv` + **`$BRAIN_CONFIG` `teams[]`** |
| `team-members.md` | `src/personio/staff-roster.tsv` + `memory/L2/team-*.md` members sections + **`$BRAIN_CONFIG` `teams[]`** (for the Linear-team column) |
| `product-areas.md` | Team L2 files (group features by product area) |
| `business-domains.md` | `memory/L2/exco.md` + `memory/L2/intranet.md` + `memory/L2/one-pagers.md` |
| `data-model.md` | **`src/outline/BI Wiki/**`** (dbt's documentation home — see the docs-first note below) + `outputs/services/**/*.db.agent.md` + BigQuery metadata |
| `entities.md` | Full scan of all L2 files — anything appearing in 2+ sources gets an entry |
| `tone-of-voice.md` | `src/medium/smnbss/` — Simone's writing voice analysis |
| `skills.md` | `.claude/skills/*/SKILL.md` — enumerate all skills |
| `system-map.md` | `.claude/agents/`, `.claude/skills/`, `.claude/commands/` — full system index |
| `hub.md` | **Last** — reads all other L1 files, builds the top-level nav with counts. Keep only the last **7** "What changed" entries live; older entries rotate to `hub-changelog-YYYY-MM` archives (see "Size Caps & Archive Rotation") |

> ⚠️ **Docs-first repos have NO `.agent.md` — do not treat that as a gap.** As of
> 2026-08-12, `brain-rebuild-services` deletes rather than generates a per-repo doc for
> any repo whose documentation lives in Outline via `doc-sync`; 26 were removed in that
> run (api-catalog, api-partner, api-payments, booking, buynana, community,
> coordinators, **dbt**, kaioh, my, myweroad, partner, weroad, wemeet, …). Consequences
> for every `inputs` glob in this table and in Phase 2:
>
> - `outputs/services/**/*.agent.md` now resolves to **62** files, not 88. Any target
>   whose knowledge came from a deleted doc must add
>   **`src/outline/<Collection> Wiki/**`** to its inputs — that tree is gbrain-indexed
>   and is the same content the owning team maintains. The clone's `docs/domain/` is the
>   byte-authoritative side if you need to disambiguate.
> - **`outputs/services/**/*.db.agent.md` (34 files) survives untouched** and is still
>   the only source for columns, enums and status lifecycles. Schema knowledge did not
>   move.
> - **`outputs/services/TRAPS-from-deleted-docs.md` is append-only** — 39 corrections
>   extracted from the deleted docs. Read it wherever you previously read a service
>   doc's `## Traps` section, and never regenerate it.
> - Repo↔collection mapping is by **document-basename overlap**, never by collection
>   name (two collections are both titled `Partner Portal`). `n8n-workflows` has no
>   collection and therefore keeps its doc.
>
> A stale glob here **loses detail silently instead of failing**, which is why this note
> sits next to the table rather than in a changelog.

#### `memory/L1/teams.md`

Generate this file from `$BRAIN_CONFIG` `teams[]` + `memory/L2/team-*.md` + `src/personio/staff-roster.tsv` + any team data in `src/linear/` or `src/outline/`.

**`$BRAIN_CONFIG` is a declared input of this target** — it MUST appear in the target's `inputs` list in `memory/.rebuild-state.json` (as `.super/brain.config.yml`), so that editing `teams[]` marks `teams.md` dirty on the next incremental run. Without it a new team row sits in config and never reaches the table, and the prep skills go on re-deriving that calendar event by hand every run (observed 2026-08-06: the `GED - Deep dive` recurring event had no row).

**Every `teams[]` row must produce a table row**, including non-squad functional teams with no IDP services (e.g. `GED`, `Content/SEO`). Conversely, do not invent rows with no config entry and no Personio/Linear backing. Verify each row's `Linear teams` cell against `mcp__linear__list_teams` (a team's Personio name is frequently NOT its Linear name — `GED` → `Design`, `Content` → `CONTENT&SEO`) and each `Members` count against Active rows in the roster.

The file must contain a **machine-readable mapping table** at the top (after frontmatter) with these exact columns:

```markdown
| Team name | Calendar patterns | File slug | Linear teams | Members |
|-----------|-------------------|-----------|--------------|---------|
```

- **Team name**: canonical team name (e.g., `Buktu`, `Tium`, `DevOps & IT`)
- **Calendar patterns**: comma-separated, case-insensitive patterns used in calendar summaries (e.g., `Buktu`, `SAITAMA - Deep Dive`)
- **File slug**: lowercase, no spaces, used for output filenames (e.g., `buktu`, `devops-it`)
- **Linear teams**: comma-separated Linear team **names** as returned by `mcp__linear__list_teams`, or `—` if none (e.g., `BUKTU`, `DEVOPS, IT`). ⚠️ **Names, never keys** — `SAITAMA` not `STM`, `DEVOPS` not `DVO`, `Data Engineering` not `DE`. Mixed forms were shipping in `team-members.md` until 2026-08-18 and nothing downstream matched both.
- **Members**: count of members from `team-members.md`, or list of names if count is small

Below the table, keep human-readable sections (services owned, deep dive links, external systems) derived from L2 files.

#### `memory/L1/team-members.md`

Generate this file from `src/personio/staff-roster.tsv` + the Members sections of `memory/L2/team-*.md` + **a live Linear read** (see *Linear-teams join* below).

**Read the roster's real header, never a remembered column list.** The export carries
`ID | First Name | Last Name | Email | Position | Department | Team | Office | Hire Date | Status | Supervisor | Contract End Date | Occupation Type`.
⚠️ Two of those columns were missing from this skill's documented list and from `$BRAIN_CONFIG`
`sources.personio.columns` until 2026-08-18 — `Email` above all — and the consequence was not an
error but a **silent `—`**: `Email` is populated on **205/205** exported rows and rendered `—` on
**190/199** roster rows for months. Start this target by diffing
`head -1 src/personio/personio-staff.tsv` against `$BRAIN_CONFIG` `sources.personio.columns`; if
they disagree, **fix the config first**, then generate. A column you do not know about cannot fail
loudly — it just renders empty.

The file must contain a **machine-readable mapping table** at the top (after frontmatter) with these exact columns:

```markdown
| Name patterns | File slug | Email | Role | Team / Department | Linear teams |
|---------------|-----------|-------|------|-------------------|--------------|
```

- **Name patterns**: pipe-separated, case-insensitive identifiers that could appear in calendar summaries (e.g., `Bera | Simone Berardozzi` or `Alex | Alessandro`)
- **File slug**: lowercase, spaces → hyphens, used for output filenames (e.g., `bera`, `alex`)
- **Email**: the roster's `Email` cell, verbatim. **`—` is only legal when that TSV cell is
  genuinely empty** — which, on the current export, is never. This column is the join key for every
  downstream Linear and Workspace lookup, so an unnecessary `—` here disables those lookups
  silently. Do not "leave it out for brevity"; do not fill it by guessing
  `first.last@<domain>` either — Personio holds the real local-part and it does not always follow
  the pattern (`giulio.ricotti@` drops "Prina", `serhiy.kovalchuk@` for *Sergio* Kovalchuk).
- **Role**: Position from Personio (e.g., `Senior Digital Product Manager`)
- **Team / Department**: Department from Personio, or team name from L2 files if different
- **Linear teams**: see *Linear-teams join* below. **Never a bare `—`.**

Only include Active employees from the staff roster. If a nickname or alias is known from calendar patterns but not in Personio, add it as an extra Name pattern and mark the source as `user`.

##### Linear-teams join — derive it live, and label the blanks

⚠️ **This column is load-bearing and it was wrong for months.** `brain-prepare-my-one-on-one` and
`brain-prepare-my-deep-dives` read it to decide whether to query Linear at all, so a `—` does not
degrade an agenda — it **removes every Linear section from it while the agenda still looks
complete**. Audited 2026-08-18: **188 of 199 rows read `—`, and 73 of those people had live Linear
team membership.** Alberto Marinelli (`alberto.marinelli@weroad.com`, member of BI / Data
Engineering / Growth, lead of 9 active projects, 27 open issues) rendered as `—` and got a 1:1
agenda with no project or issue context at all.

Derive the column **from live Linear on every rebuild**, never from `src/linear/` alone:

1. `mcp__linear__list_teams` (`limit: 250`) → the full team list with `key` and `name`. Keep both:
   the roster must print the **`name`** (`SAITAMA`, `DEVOPS`, `CONTENT&SEO`), never the `key`
   (`STM`, `DVO`). Both forms were in the table before 2026-08-18 and downstream matched on neither
   reliably.
2. For each team, list its members — `mcp__linear__list_users` with `team:`, or
   `wr-linear teams members <key> --all`. Build `email → {team names}`.
3. Join to the roster **on the Personio `Email` cell, lowercased**. Name matching is not a fallback
   here: Linear display names drift from Personio legal names (`Sergio Kovalchuk` vs `serhiy.`,
   `Matteo - Frag - Crosta`, `Victoria Guevara` vs Personio's `Maria Victoria Guevara`), and three
   Linear accounts carry an email as their `name`.
4. **Drop org-wide container teams from the cell** — `Digital: Others`,
   `Digital: Product Development`, `Digital: Guilds`, `Monkeys Triage`, `AI Specialist`, `HEADS`,
   `Simon`. They contain 17–42 people each, they are not query targets, and including them makes
   every engineer's cell look identical. Keep the guilds (`Backend Guild`, `Frontend Guild`) and
   `STAFF` — those own real projects.

**Then label every cell. A blank must say which kind of blank it is:**

| Situation | Cell value |
|---|---|
| Joined, has team membership | `BI, Data Engineering, Growth` (Linear team **names**, comma-separated, alphabetical) |
| Joined, Linear account exists, zero team membership | `none (Linear account, no team)` |
| Joined, no Linear account for that email | `none (no Linear account)` |
| Personio row absent — founder / ExCo / external / candidate | `— (not in Personio; join not possible)` |

⚠️ **The Personio→Linear join is not total and must not be presented as if it were.** Personio omits
founders and part of ExCo entirely (Fabio Bin has no row) and carries no departure dates, so the
unjoined set legitimately contains real people. Conversely, live Linear carries members with **no**
Personio row — as of 2026-08-18: `tech@weroad.com` (AUTOMATIONS) and `team-crm@weroad.com` (service
accounts, never add them), `chiara.bertorelle.ext@` (external guest), Chung Fei Wu (deliberately
excluded from this table) and Himali Mishra. **Report the unjoined count in the section prose; never
let an unjoinable person render the same as a person with no Linear presence.**

⚠️ **Team membership under-covers where a person actually works — say so, don't silently widen the
cell.** Alberto Marinelli is not a member of `AI Guild` yet leads six AI Guild projects, and his
assigned issues span `BI, DE, GRO, TIUM, AIG` — five teams against three memberships. Do **not**
paper over this by unioning in the teams of every project someone leads: multi-team projects would
hand Matteo Risso eleven extra teams that are project scope, not his teams. The correct fix lives
downstream — `brain-prepare-my-one-on-one` queries Linear **by email** (`list_projects member:`,
`list_issues assignee:`), which is complete regardless of this column. Keep this column as the
membership fact, and keep the email column populated so downstream never needs it.

⚠️ **`mcp__linear__list_projects` pages at 50 and truncates silently** — a valid page with no hint
more exist. Paginate with `cursor` before counting anything. `wr-linear projects list` is worse:
`--all` and `--limit 250` both fail with `400 Query too complex`, and **`--state` is accepted and
ignored** (every state filter returns the same first 50 rows). `wr-linear teams members --all` and
`wr-linear users list --all` do paginate correctly.

##### ⚠️ Byte budget — this page can no longer rotate its way under the cap

Populating `Email` on ~199 rows added **~4.7 KB to the roster table**, which is **not rotatable** —
rotation moves dated prose sections, and the table is the point of the file. The table alone is
**~30 KB of the 40,960-byte cap**, so the prose has to fit in what is left.

**Do not resolve this by deleting the Linear/email warnings above — they are the whole reason the
column is populated.** A rebuild that hits the cap here and starts trimming warnings will
reintroduce exactly the silent failure this section documents.

⚠️⚠️ **HARD PROSE BUDGET — COMPUTE IT, DO NOT ESTIMATE IT.** Before writing the page, measure the
table and subtract:

```bash
TBL=$(sed -n '/^| Name patterns | File slug/,$p' memory/L1/team-members.md | wc -c)
echo "prose budget = $(( 40960 - TBL - 1024 ))"   # 1 KB reserved for headcount growth
```

**Everything above the table must fit that budget.** Compacted 2026-08-19 to **9,156 B of prose /
39,184 B total** with all 37 durable facts intact and the table byte-identical — that is the proven
shape, so treat ~9.2 KB as the working target and re-derive it if the table grows.

To stay inside it, these are **rules, not preferences**:
- **Exactly ONE dated roster-state section is live at a time, and it is ≤ ~1.3 KB.** Rotate the
  previous one every run. Net growth per rebuild must be ~0.
- **The dated section carries durable facts only — never the measurement narrative.** Specifically
  do NOT re-emit: "the whole diff is one added line", per-run spot-check tallies ("13 cells
  re-checked, 0 contradictions"), or a restatement of rules already in *Standing lookup rules*.
  One compact join-coverage line (`N teams · N account-no-team · N no-account`) is the whole
  quantitative budget.
- **The `## Archive` section is a pointer plus its two warnings** (cap-driven-not-age-driven; never
  read a headcount out of an archived resync) **plus any archived claim that is a trap rather than
  history**. It is **not** a table of contents for the log — the log has headings.
- **Do not re-add the `mcp__linear__list_projects` / `wr-linear projects list` pagination traps
  here.** They are Linear tooling traps, not roster rules, and they now live in `memory/L1/linear.md`
  (relocated 2026-08-19). Duplicating them is what pushed this page over the cap.
- **Never reword the three `Linear teams` blank tokens.** `brain-prepare-my-one-on-one` matches
  `none (no Linear account)`, `none (Linear account, no team)` and
  `— (not in Personio; join not possible)` as **exact strings** in its decision table. Shortening
  them to save bytes silently breaks that consumer — it is not a valid compaction lever.

If the computed budget is still not met **with all durable facts kept**, stop and put the choice to
the user: raise the cap for this page specifically, or split the table into a companion page. Do not
silently shed content.

These two files are the **canonical source** for `brain-prepare-my-deep-dives` and `brain-prepare-my-one-on-one`. They must be regenerated on every rebuild so skills never use stale hardcoded mappings.

---

## Phase 3.5 — Top-level AGENTS.md (brain navigation doc)

Every AI coding assistant that lands in the brain project — Claude Code, Gemini CLI, Codex, others — reads a root-level nav doc at session start. This phase generates a single canonical file (`AGENTS.md`) and exposes it under the other conventional names via symlinks so we never drift between copies.

**Anchor:** `<brain_root>` = the project directory found by the existing `$BRAIN_CONFIG` walk (same anchor as the rest of this skill). Never write to `$HOME`.

### 3.5a. Regenerate `<brain_root>/AGENTS.md`

Dirty when `hub.md` is dirty, when `src/` top-level structure changed, when Phase 1 inventory counts changed vs. the values baked into the current `AGENTS.md`, or in full-rebuild mode.

Content (assemble from Phase 1 inventory + the just-rebuilt L1 files):

1. **Intro paragraph** — who the brain belongs to (read `<brain_root>/.super/brain.config.yml` for owner + org), one-line purpose.
2. **Repository Layout** — code fence showing `memory/`, `src/`, `outputs/` with live counts from Phase 1 (subdirs + file counts). L1 and L2 counts come from `ls memory/L1 | wc -l` and `ls memory/L2 | wc -l` after rebuild. Once `memory/L2/archive/` exists, list it as its own layout line with its file count (rolled-out dated sections; see "Size Caps & Archive Rotation").
   **Every count here is re-measured from disk this run — never copied from the AGENTS.md already on disk.** The `github/` line in particular must use the Phase 1a-i figures: the `repos.sh` tracked-clone count for the jungle monorepo (not the subdirectory count), the stale clones named, and any clone with an unresolvable HEAD called out with the date it was last re-confirmed.
3. **How to Navigate** — 4-step path starting at `memory/L1/hub.md` + a `Quick Access` list pointing at the highest-signal L1 files (`entities.md`, `data-model.md`, `product-areas.md`, `teams.md`, `system-map.md`) plus `outputs/services/<owner>/<repo>.agent.md`. Then a **`### Knowledge Map`** subsection: a complete index of every L1 MOC grouped (Entry & cross-cutting · People & org · Product & business · Data & analytics · Engineering & systems · Sources · Content & voice), each L1 showing the L2 pages it connects to as `[[wikilinks]]`. Derive the groupings + L1→L2 edges from the just-rebuilt files (the Phase 3 derivation table + each L2's `Topics:` footer). This is the agent's traversal spine — it must stay accurate to the actual link graph.
4. **Freshness Tracking** — explain `verified:` fact blocks, `staleness_threshold:` frontmatter, and the `superseded:` marker convention.
5. **Searching** — always use the gbrain MCP tools (`mcp__gbrain__query`, `mcp__gbrain__search`, `mcp__gbrain__get_page`); the HTTP server is always-on so they're always available. Grep is for exact matches only. **Always include the lowercase-extension warning:** gbrain's sync classifier (`isMarkdownFilePath`, `src/core/sync.ts`) tests `path.endsWith('.md')` case-sensitively, so an uppercase `.MD` file is rejected with reason `strategy` and silently never imported; there is no config surface for it (`gbrain.yml` include/exclude globs are applied *after* the extension gate). This is why service docs are `<repo>.agent.md` / `<repo>.db.agent.md` — the old `.AGENT.MD` form kept all 108 of them out of the index until 2026-07-27, and it couldn't be rescued by a wikilink rewrite either (link extraction strips only a lowercase `.md`, and `normalizeBasename` drops dots, so `[[cms.AGENT.MD]]` → `cmsagentmd` can never meet the page key `cmsagent`). Never introduce an uppercase-extension page.
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
4. **Orphans**: memory files with no corresponding source → flag (don't delete). `memory/L2/archive/` pages are exempt — their source is the `archive_of:` parent.
5. **Symlink health**: `<brain_root>/CLAUDE.md` resolves to `AGENTS.md`; `GEMINI.md` resolves to `AGENTS.md` if gemini is installed.
6. **Size caps**: every file rewritten this run is ≤ 40 KB; additionally flag any `memory/` file > 50 KB (gbrain's warn threshold) in the digest. If an over-cap file is an accretive target, rotate it before finishing (see "Size Caps & Archive Rotation").
7. **Archive integrity**: closed-period archives were not touched this run (mtimes unchanged); every archive page has a `Topics:` footer linking its parent; every rotated parent has an `## Archive` section with one `[[wikilink]]` bullet per archive page.

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
- **Rotation summary**: archives created / appended-to, sections moved per live file, live-file sizes before → after, any file still over the 40 KB cap (with reason)
- Top-level nav: `AGENTS.md` regenerated y/n; symlink status for `CLAUDE.md` and `GEMINI.md`
- Changes summary (what was added, updated, removed)
- Broken links found
- Items flagged for review

Finally, write the updated `memory/.rebuild-state.json` with fresh `max_mtime` + `content_hash` for every target (including skipped ones — their mtimes may have advanced even if content matched).

---

## Linking & Connection Rules (gbrain optimization)

The whole point of L1/L2 is a navigable graph: gbrain materializes every `[[wikilink]]` into an edge (Phase 4.5) and uses those edges for backlink-boost ranking and `graph`/`graph-query` traversal. Maximize *correct* connection density. Apply these rules to every file written in Phases 2/3/3.5:

1. **Never emit an empty or text-only "see also" entry.** Every `## Related` bullet and every cell in an `L3 References`-style table MUST contain a resolvable `[[link]]`. If there is no target, omit the bullet/row entirely — do NOT write `-  — description` (the historical bug that left dead bullets in `technologies.md`).
2. **Reference pages as wikilinks, not code paths.** When a file points at another brain page, write `[[basename]]` — including service docs (`[[community.agent.md]]`, resolves by `global_basename` regardless of the `outputs/services/<owner>/` subdir) and DB docs (`[[unison.db.agent.md]]`). A bare `` `outputs/services/x.agent.md` `` code-span produces NO edge. Reserve code-spans for paths you are *not* linking (raw `src/` exports without wikilink syntax).
3. **Bidirectional completeness.** Every L2 `Topics:` footer must link UP to **every L1 file that cites it** (the Phase 3 derivation table is the citation map) plus any obvious see-also L1s. Conversely every L1 must link DOWN (in a `## Related` block + body) to **every L2 it derives from**. Source MOCs (`github.md`, `metabase.md`, …) are the usual offenders — give each a `## Related` block pointing at the L2/L1 pages it feeds (e.g. `github → [[technologies]] · [[services]] · [[teams]]`; `metabase → [[data-model]] · [[team-data]]`). Footers are additive: when refreshing, never drop an existing valid link.
4. **Inline first-mention links.** In body prose, the first mention of another team, domain, service, source, or person that owns its own page gets a `[[wikilink]]`. This produces far more edges than footers alone. Example: in `technologies.md`, "AI/ML stack" → `[[team-data]]`, "main platform" → `[[team-rocket]]`, "data & analytics" → `[[data-model]]`.
5. **Concise frontmatter `description:`.** Keep `description:` a single topical sentence (≤ ~220 chars) naming the domain + its key entities — this is the page's summary vector. Put dated change-log detail in **body** sections under `<!-- verified: -->` blocks (which become chunks + timeline entries), not crammed into `description:`. Do not duplicate long WBR digests into the description.
6. **Self-contained section headings.** gbrain chunks by heading; a heading + its block should make sense out of context (name the entity/date), so a retrieved chunk is interpretable on its own.

After Phase 4's broken-link check, the graph should be strictly denser than the prior run with **zero** broken links and zero empty `[[]]`/`-  —` bullets.

## Size Caps & Archive Rotation (retrieval optimization)

gbrain warns above ~50 KB per page; oversized pages chunk poorly and dilute retrieval (observed 2026-07-14: `meetings.md` 129 KB, `hub.md` 107 KB, `workflowy.md` 80 KB, `technologies.md` 68 KB, `team-tium.md` 63 KB, `releases.md` 62 KB, `exco.md` 53 KB, `x-content.md` 48 KB). The cause is accretion: dated update sections prepended on every harvest/rebuild and never rolled out. The fix is **rotation into archive pages** — content moves verbatim; it is never summarized away or deleted.

**Hard cap: every live file under `memory/` must land ≤ 40 KB after a rewrite.** Two mechanisms enforce it, in order:

1. **Window rotation (primary, deterministic).** Each accretive target keeps only its recent window of dated sections in the live file; everything older moves to archive pages:

   | Live file | Dated-section window kept live | Archive page basename |
   |-----------|-------------------------------|----------------------|
   | `L2/meetings.md` | current + previous ISO week (`## WNN update …` sections) | `meetings-YYYY-MM` |
   | `L1/hub.md` | last **7** "What changed" entries | `hub-changelog-YYYY-MM` |
   | `L2/releases.md` | current + previous quarter | `releases-YYYY-QN` |
   | `L2/technologies.md` | dated refresh sections from the last **30 days** | `technologies-log-YYYY-MM` |
   | `L2/exco.md` | dated sections from the last **45 days** | `exco-log-YYYY-QN` |
   | `L2/team-<slug>.md` | dated sections from the last **45 days** | `team-<slug>-log-YYYY-QN` |
   | `L2/workflowy.md` | digest sections from the last **30 days** | `workflowy-log-YYYY-MM` |
   | `L2/x-content.md` | digest sections from the last **30 days** | `x-content-log-YYYY-MM` |

   A section's own date (from its heading or `verified:` marker) decides whether it is in-window and which archive period it belongs to — not today's date. Durable reference sections (velocity tables, "How to Use", coverage, member lists, IDP snapshots) are not dated update sections and always stay live.

2. **Cap backstop (any file).** If a just-synthesized file still exceeds 40 KB, keep rotating its oldest dated sections out until it fits. If a file exceeds the cap and has no dated sections left to rotate, write it anyway and flag it in the Phase 5 digest for restructuring — never drop content silently.

### Rotation procedure (applied whenever a listed target is rewritten)

1. Synthesize the live file as usual (new dated sections at top).
2. Partition dated sections: in-window stays live; out-of-window moves. Moved sections go **verbatim** — heading, body, `<!-- verified: -->` / `<!-- superseded: -->` markers, and inline `[[wikilinks]]` all intact. The link edges migrate with them: archives live under `memory/`, so they are indexed and survive the Phase 4.5 link cleanup — graph density is preserved, not lost.
3. Write/append the archive page at `memory/L2/archive/<basename>.md` (create the directory on first use). Keep sections newest-first inside each archive. **An archive whose period has closed (a past month or quarter) is immutable — never rewrite it on later runs.** Only the current period's archive may receive appends, and the content-hash short-circuit applies to it like any other write.
4. In the live file, maintain an `## Archive` section directly above the `Topics:` footer: one bullet per archive page, newest first, each with a single-line retrieval summary — e.g. `- [[meetings-2026-06]] — June 2026 (12 harvests, W23–W26: Q3 zero-based roadmap, WeMeet payments live, ExCo org reveal)`.
5. Rewrite the live file's frontmatter `description:` to the concise ≤ ~220-char form (Linking rule 5). Dated digest text accumulated in `description:` is the same bloat in a second location — it belongs in body sections, which rotation now bounds.

### Archive page template

```markdown
---
type: archive
archive_of: meetings
period: 2026-06
description: "Archive — meetings dated sections for June 2026, rolled out of the live [[meetings]] page."
updated: 2026-07-15
staleness_threshold: 365d
---

# Meetings — Archive 2026-06

Dated sections rolled verbatim out of [[meetings]]; newest first.

<moved sections, unmodified>

---
Topics: [[meetings]], [[hub]]
```

Bare-basename wikilinks (`[[meetings]]`, `[[hub]]`) are correct in archives — `global_basename` resolves them. Archive basenames are globally unique by construction (`<parent>-<period>`).

### Bookkeeping

- Archives are **side outputs of rotating their parent**, not synthesis targets: no `.rebuild-state.json` entries, no dirty tracking, no input globs. They are only touched when their parent rotates.
- **Backlog on first rotation:** create one archive per period for *all* out-of-window sections in one pass (e.g. the first `meetings.md` rotation produces `meetings-2026-05` and `meetings-2026-06` together).
- `releases.md` is updated via harvest "Brain Updates" rather than a dedicated Phase 2 step — the rotation rules still apply every time this skill rewrites it, and the Phase 4 size check catches it regardless of who wrote it.

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
- **Cap live files at 40 KB — rotate, never delete**: apply "Size Caps & Archive Rotation" to every accretive target; out-of-window dated sections move verbatim to `memory/L2/archive/` with bidirectional links (parent `## Archive` section ↔ archive `Topics:` footer).
- **Closed-period archives are immutable**: never rewrite an archive whose month/quarter has ended — only the current period's archive may receive appends.
- **Conservative on entities**: 2+ source appearances required for `entities.md`.
- **Maximize correct link density**: follow the "Linking & Connection Rules (gbrain optimization)" section above on every rewritten file — no empty/text-only see-also entries, wikilink (not code-path) every page reference, bidirectional Topics footers, inline first-mention links, concise `description:`.
- **Use `mcp__gbrain__query`** for semantic searches across the brain (the always-on HTTP server). Use Grep only for exact string/regex matches.
- **Agent outputs are read-only for L2**: `outputs/agents` reports feed into L2 summaries but are never modified by this command.
- **Don't touch clean files**: in incremental mode, skipped targets must keep their existing `verified:` and `updated:` values byte-for-byte. Rewriting an unchanged file defeats the entire staleness signal.
- **Content-hash short-circuit**: even for a dirty target, if the newly-synthesized content hashes identical to the file already on disk, leave the file unchanged and only update the state file.
- **Never clobber real `CLAUDE.md` / `GEMINI.md`**: if either exists as a regular file (not a symlink), flag it and move on. Only manage symlinks this skill created.
