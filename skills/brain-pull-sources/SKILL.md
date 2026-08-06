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
| Source manifests | `sources.md` + `sources.github.md` (repo root) |
| Secrets | `.env.local` (repo root, gitignored) |
| Export output | non-GitHub → `src/clickup/`, `src/confluence/`, `src/gdrive/`, `src/linear/`, `src/medium/`, `src/metabase/`, `src/personio/`; GitHub → `github/<owner>/<repo>/` |
| Last export manifest | `src/.last_export.json` |

**Resolving the skill path at runtime:**

```bash
SKILL_DIR="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"
```

When installed via `npx skills add`, the skill lives at `.claude/skills/brain-pull-sources/`.
When installed via the Claude marketplace, resolve the path dynamically.

### Environment check (run first)

Sources are split across two files at the repo root, by where their output lands:

| File | Holds | Output tree |
|------|-------|-------------|
| `sources.md` | every non-GitHub source (ClickUp, Confluence, Drive, Medium, Linear, Metabase) | `src/<source>/` |
| `sources.github.md` | `github_clone` lines only | `github/<owner>/<repo>/` |

If either file is missing at the repo root, create it by copying the matching template from this skill's `references/` directory (`references/sources.md`, `references/sources.github.md`).

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
| `PERSONIO_CLIENT` | `personio_to_md` | Personio API client id (Settings → Integrations → API credentials) |
| `PERSONIO_SECRET` | `personio_to_md` | Personio API client secret |
| `GCP_PROJECT_ID` | general | GCP project for BigQuery/logging |

---

Source commands (the `github_clone` command lives in `sources.github.md`; all the rest live in `sources.md`):
- `clickup_doc_to_md <url>` — export ClickUp docs
- `clickup_prj_to_md <url>` — export ClickUp project/folder roadmap lists
- `confluence_space_to_md <url>` — export Confluence spaces
- `drive_to_md <url> [--mode full|index]` — export a Google Drive folder. **Default `--mode full`**: downloads + converts every file to `.md` (via markitdown) and also writes a per-folder `INDEX.md` with links to both the local `.md` and the original Drive file. **`--mode index`**: skips downloads and writes only per-folder `INDEX.md` catalogs (title + link + type + metadata). Use `index` for large/low-signal folders where full export is overkill. Output (both modes): `src/gdrive/<Drive Name>/<sub/path>/`. Registry at `src/gdrive/.registry.json`. Supports `--list` to review previously exported folders, `--full-rebuild` to ignore the folder-tree cache, and `--force` to re-download every file (full mode). Every converted `.md` carries YAML frontmatter with `gdrive_id`, `gdrive_url`, `gdrive_name`, `gdrive_mime`, `gdrive_modified`, and `gdrive_path` so downstream tools can cite the original Drive file.
- `github_clone <url>` — full-clone or update a GitHub repo into `github/<owner>/<repo>/`. **Never resets over local work.** A clone that is clean and on its default branch is hard-reset to `origin/<default>` as before (the mirror case). A clone with **local commits** gets `origin/<default>` **merged in**, keeping those commits — and a merge conflict aborts, leaving the clone untouched. A clone with **uncommitted changes** is skipped entirely. A failed fetch only triggers the destructive re-clone when there is nothing local to lose. Every deviation is appended to `$GITHUB_CLONE_REPORT` (default `.github-clone-report.md`, truncated per run by `pull_sources`, printed at the end of its output) so the daily update can report it — necessary because the jungle loop sends this script's stdout to `/dev/null`.
- `medium_to_md <url>` — export Medium feed
- `linear_to_md <url>` — export Linear projects
- `linear_issues_to_md <url>` — export ALL issues for a Linear team or project (including triage). **Incremental**: keeps a per-issue `updatedAt` map in `.issues-registry.json` and re-fetches the full description + rewrites the file only for issues that changed since the last run (the index is always rebuilt from the cheap bulk query). `--force` re-fetches everything. (A no-change run of a ~120-issue project drops from ~85s to ~2s.)
- `metabase_index <url>` — export full Metabase index
- `gmeet_to_md <email>` — harvest meeting notes/agendas/recordings/attachments the email is invited to (Google Calendar + Drive) into `src/gmeet/`; deterministic Steps 1–5 of `brain-pull-my-meeting-notes`, no LLM digests. Incremental via `src/gmeet/.registry.json`; `--since` / `--day` / `--days` / `--force` / `--list`. Assumes `email` == the authenticated gws user. **Its artifact-matching contract is load-bearing — see below before touching it.**

#### `gmeet_to_md` artifact matching — do not loosen these guards

Folder name, date and the `# H1` come from **Calendar and are always right**. The Gemini
notes/transcript **body** comes from a Drive *name* match and is the part that goes wrong, so a
misfiled note looks perfectly healthy. This has now been fixed **three times** (`c5442c8`,
`56acbd3`, `3335d2d`); a 2026-08-06 audit still found **128 of 758 `notes.md` (16.9%)** holding
another meeting's notes, including **3 one-to-one leaks** (one person's 1:1 notes inside another
person's folder — a confidentiality problem, not just an accuracy one). Every guard below exists
because its absence produced real, shipped damage.

- **Why loose title matching fails.** `TITLE_MATCH_THRESHOLD = 0.55` over `difflib` on the doc
  *name*: a family of meetings sharing a suffix scores high because the boilerplate dominates,
  while the distinguishing acronym is 3–5 chars. `'GED - Deep dive'` vs `'SAIAN DeepDive'` = 0.667,
  vs `'AI DeepDive'` = 0.750, `'Simon / Marina 1:1'` vs `'Simon / Giovanni 1:1'` = 0.706 — all
  above 0.55, none reaching `TITLE_MATCH_STRICT` (0.90).
- **Guard 1 — creation-date bound** (`DOC_CREATED_MAX_DAYS`): the candidate query filters on
  `modifiedTime`, so merely *opening* an old doc makes it a candidate.
- **Guard 2 — cross-meeting word conflict**: only fires when the stolen word belongs to another
  meeting **the same day**. Necessary but not sufficient — it cannot catch a misfile on a day when
  the rival meeting is not scheduled.
- **Guard 3 — `title_contradiction()`, day-INDEPENDENT**: if each side carries a distinctive word
  the other lacks, require `TITLE_MATCH_STRICT`. This is the guard that closes Guard 2's hole.
  Asymmetric cases are deliberately *not* contradictions, so legitimate renames still match.
- **`title_tokens()` keeps 2-letter UPPERCASE acronyms.** `AI` was dropped as noise by a
  `len >= 3` rule, which is precisely why `AI DeepDive` was the most frequent impostor (20
  folders). Lowercase 2-letter words stay dropped (`di`, `in`, `on`, `to`).
- **`_content_title_mismatch()` — the in-body check.** Reads the title Gemini wrote *inside* the
  doc, the only place the truth appears. Two verdicts, and the distinction is essential:
  `misfiled` (the body names another meeting **on that day** → discard) vs `suspect` (nothing on
  the calendar accounts for it → **keep**, record under `dataQuality`).
  ⚠️ **Never turn `suspect` into a discard.** `FE Alignment` legitimately carries bodies titled
  `GED Design Sharing/Alignment` on 7 different days with distinct `docId`s, and that title owns
  **no folder anywhere in two years** — it is the organiser's name for the same series.
  Discard-on-disagreement deletes 7 genuine files. The discriminator when auditing offline is
  *does the body's title own a folder somewhere?* (`Simon / Cass 1:1` owns 10 → real meeting →
  leak; `GED Design Sharing/Alignment` owns 0 → alias → keep.)
- **`looks_like_date_line()`**: Italian day-first dates (`19 mar 2026`) are not month-first, so
  without this they parse as a *title* and the guards reject good notes because `{mar}`
  "contradicts" `{ged}`.
- **`strip_gemini_suffix()` must strip only the trailing date/kind segment — never split on the
  first " - ".** WeRoad meeting titles routinely contain one, so a naive split truncated
  `'Zero Based - SUPPLY - 2026/06/15 … - Notes by Gemini'` to just `'Zero Based'` and
  `'GED - Deep dive - …'` to `'GED'`, destroying the only distinguishing part before any guard saw
  it.
- **⚠️ Known hole: a discarded doc is not re-offered.** `assign_matches()` is strictly one-to-one,
  and `_content_title_mismatch()` runs *after* assignment — so when the content check discards a
  note, that doc is already consumed and is **never offered to the meeting it actually belongs
  to**. Combined with the truncation bug above this destroyed real data: on 2026-06-15 the three
  `Zero Based - {SUPPLY,DEMAND,Coordi}` docs all reduced to the same string, were assigned to
  arbitrary folders, each was correctly discarded — and all three notes vanished. The same
  mechanism emptied 2026-06-26's Team Leader Session, whose plenaria content a whole month of
  `L2/` facts had been resting on.
  The suffix fix removes the common cause, but the hole remains. Two consequences:
  1. Anything that makes assignment *stricter* can turn a mis-assignment into a deletion. Never
     add a rejection rule without checking what happens to the doc afterwards.
  2. Audit for it after a bulk re-harvest — a discard whose doc-id then appears nowhere is a
     silent loss, not a cleanup:
     ```bash
     grep -c Discarding <harvest.log>          # every discard is a candidate loss
     # for each, confirm the docId landed somewhere:
     grep -rl "<docId>" src/gmeet --include=metadata.json
     ```
  The real fix is a second pass that re-offers each discarded doc to the meeting its own title
  names, when that meeting ended with no notes. Not implemented yet.
- **Always diff a bulk re-harvest against a pre-run manifest** (path → `docId` + content hash per
  `notes.md`). Both the FE Alignment deletion and this one-to-one loss were invisible in the logs
  and in the counts, and surfaced only from the diff. A falling `notes.md` count is *usually*
  success — but it is also what data loss looks like, and only the diff tells them apart.
- **`best_match()` is deprecated and must stay unused** — no one-to-one constraint, so one doc gets
  claimed by several same-day meetings. That is the origin of most historical damage: of the 128
  misfiles, **120 were duplicates** of a correctly-filed copy. Use `assign_matches()`.
- **Transient-failure retry** (`gws_json`, `_GWS_TRANSIENT_RE`): keyring-unavailable, 429/5xx,
  quota, timeout and connection resets retry with backoff (5 attempts). A ~485-day backfill died
  after 198 completed days on a macOS keyring blip that self-healed in seconds. Permanent errors
  are **not** retried — calendar 403/404 must keep raising `CalendarAccessError` immediately.
- **Long backfills: drive them per-day, not as one `--since` span.** One process over ~485 days
  loses everything on a single failure; a per-day loop with a checkpoint file loses one day.
- **Auditing an existing corpus**: artifact-less folders are pruned, so a re-harvest of a bad day
  *removes* folders. `index.md` still lists every meeting, so calendar history survives — only the
  false artifact links go. A shrinking `notes.md` count is the success signal, not a regression.
  Note also that `*-digest.md` and `transcript.md` are **preserved** across re-harvests, so
  LLM-written digests keep whatever the old wrong notes said until regenerated separately.
- `personio_to_md` — export the staff roster from the Personio API (v1 `/company/employees`) into `src/personio/personio-staff.tsv` (canonical columns — ID, name, email, position, department, team, office, hire date, status, supervisor, contract end, occupation type). Takes no URL; authenticates with `PERSONIO_CLIENT`/`PERSONIO_SECRET` from `.env.local`. Attributes are flattened **by label**, so company-specific dynamic attributes (Team, Office) are picked up automatically and the export survives Personio attribute-id changes. Exports **active staff only** by default (status active/leave/onboarding); pass `--include-inactive` to keep ex-employees. Flags: `--list`, `--limit N` (page size, default 200), `--include-inactive`, `--base-url`, `--verbose`. If a canonical column comes back empty it prints a NOTE — usually the credential's readable-attributes scope in Personio needs widening. The bearer token used is read-only on persons/employees. (Replaces the retired `brain-personio-staff-sync` browser-scrape skill.)

GitHub repos are full clones (~48 repos from the IDP service catalog).

---

## Pipeline

The sync runs in three phases.

### Phase 1 — Source sync

**Step 1: Re-export sources**

Run the export pipeline (works from any directory — the sources files are resolved against the repo root):

```bash
bin/pull_sources              # no args → reads BOTH sources.md and sources.github.md
bin/pull_sources sources.md   # or pass explicit file(s) to process just those
GBRAIN_PULL_PAR=12 bin/pull_sources   # raise the parallel-lane cap (default 8)
```

With no arguments it reads both `sources.md` (→ `src/`) and `sources.github.md` (→ `github/`), strips `#` comments, and runs the sources **in parallel** via `bin/<tool>`. It writes `src/.last_export.json` with a timestamp and combined success/failure counts.

**Parallelism (safe by construction):** each source becomes a *lane*, and lanes run concurrently up to `GBRAIN_PULL_PAR` (default 8):
- Commands of the **same tool** (e.g. two `clickup_doc_to_md`) share one registry file, so they run **serially within a single per-tool lane**.
- **Different tools** touch different registries → their lanes run concurrently.
- `github_clone` has no shared state → **every repo is its own lane** (the ~70 repo fetches all run in parallel, the biggest wall-clock win).

Most exporters are also incremental on their own (registry + per-item `updatedAt`/`version`/`date_updated`/git-fetch), so a no-change daily run mostly skips re-fetching content. If any source fails (expired token, network error), it's logged and counted but doesn't block the others — a partial sync is better than no sync.

**Step 2: Diff — identify stale facts**

For each L2 file in `memory/L2/`, scan the `<!-- verified: ... | source: ... -->` comments. Compare the `verified:` date against source file change dates.

- **Git repos** (`github/`): use `git log -1 --format=%ci -- <file>` (git doesn't preserve mtime)
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

For each `github/` repo that changed since last sync:
- Check if `outputs/services/<service>.agent.md` exists and compare `verified:` date against `git log -1`
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
