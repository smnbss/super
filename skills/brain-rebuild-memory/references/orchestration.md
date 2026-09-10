# Reference — orchestration: worker batching, verification, digest

⚠️ **ORCHESTRATOR ONLY. A leaf worker executes one target and reports; it does not
dispatch, verify the whole write set, or write the digest.**

## Execution discipline

⚠️⚠️ **ONE WORKER PER *BATCH OF TARGETS*, SIZED BY WEIGHT. Never one context that walks the
whole target list, and never one worker for a single cheap page.**

This phase is the worst cost-weighted step in the morning routine, and it has now failed in
**both** directions. Read both measurements before changing the rule again.

**2026-08-18 — too few workers.** 4.9M input-equivalent tokens, of which **2.9M were CACHE WRITES
over just 66 requests**. A cache-write figure that size against that few requests means the prompt
cache was being rebuilt almost every request: one long-lived context growing with every target it
touched, re-paying the whole prefix each time and outliving the cache TTL in the thinking gaps.
The fix was one worker per target file.

**2026-09-09 — too many workers. That fix solved half the problem and created a new one.** The
phase fanned out to **30 workers and cost 71.6M effective tokens** (weighting cache reads 0.1x,
cache writes 2x, output 5x). Of that: **26.1M (36%) was re-reading an identical ~130K header**, and
**29.6M (41%) was STILL cache writes** — the rebuild-per-worker problem was not fixed, only spread
across 30 workers. **Actual output was 1.08M tokens, 8% of the cost.**

⚠️⚠️ **THE MEASUREMENT THAT SETTLES THE RULE, AND IT IS COUNTERINTUITIVE: A WORKER'S CACHE-WRITE
SHARE FALLS AS IT RUNS LONGER**, because the fixed ~130K boot amortises. Measured 2026-09-09:
`team-content-seo.md` at 22 turns paid **61%** of its cost in cache writes; `team-staff.md` at 44
turns paid 43%; `monkeys-wiki.md` at 117 turns paid **25%**. **So a one-page worker is the WORST
shape available — it pays a full boot and never amortises it.** Batching light targets is a win on
*both* axes at once, and the 2026-08-18 fear does not apply to a BOUNDED batch.

⚠️ **Only ~1.4% of a worker's opening context is its own task prompt.** The rest is the harness
system prompt and eager tool schemas (~72K, not yours to change), `AGENTS.md` + `MEMORY.md` (~36K),
the skill listing (~10K) and deferred tool names (~9K). **You cannot shrink the header from here.
You can only pay it fewer times.** That is what this rule is for.

The fix is structural, and this skill already has the mechanism for it — **every target
declares its own `inputs`** (see the state-file schema below). So:

- **Weigh each dirty target first, then group.** A target is HEAVY if it is a team L2 with a
  live Linear/Personio join, or any target whose declared `inputs` exceed roughly 15 files or
  200 KB. Everything else is LIGHT.
- **HEAVY target → its own worker.** Measured 2026-09-09, these ran 2.3M–5.9M each and are already
  amortising their boot: `teams`, `monkeys-wiki`, `technologies`+`releases`, the gdrive-driven L2
  set, `skills`+`system-map`, `cross-references`, `team-members`, `product-areas`+`business-domains`.
- **LIGHT targets → batch them, MAX 5 PER WORKER, GROUPED BY SHARED `inputs`.** The grouping matters
  as much as the count: all eleven `team-*.md` targets read the same `brain.config.yml` `teams[]`,
  the same `src/personio/personio-staff.tsv` and the same weekly gmeet digest, so a batch reads
  those **once instead of eleven times**. Measured 2026-09-09: 13 workers cost under 2.0M each and
  **19.5M in total to produce 276K of output**.
- ⚠️ **A BATCH IS A BOUNDED LIST HANDED TO THE WORKER UP FRONT. It is NOT "walk the target list".**
  That distinction is the whole difference between this rule and the 2026-08-18 failure. Never let
  a worker discover more targets as it goes, and never exceed 5.
- **Never hand a worker the whole `src/` or `outputs/` tree** "for context". The declared
  inputs ARE the context; anything else is prefix you pay to re-cache.
- **Dependency order still governs the fan-outs:** all L2 targets are independent of each other, so
  they go in one fan-out (batched per the rule above). L1 MOCs depend on L2 output, so they are a
  second fan-out after it. `AGENTS.md` is last because it depends on both.
- **A worker whose batch would touch more than a handful of files beyond its declared `inputs` is
  mis-scoped** — split the batch, or fix the `inputs`.
- ⚠️ **Report the worker count and the per-worker turn count in the Phase 5 digest.** The failure
  mode in both directions was invisible until someone measured it. A phase that silently drifts back
  to 30 workers, or back to one, must be caught on the next run and not three weeks later.
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

## Phase 4 — Verify

1. **Broken links**: grep all `[[wikilinks]]` in `memory/`, check each target exists
2. **Timestamps on rewritten files**: every `<!-- verified: -->` block on a file rebuilt this run must reflect today's date (or the date the underlying source changed). **Do not enforce this on skipped files** — their old dates are correct.
3. **Frontmatter on rewritten files**: `updated:` = today. Skipped files keep their prior `updated:`.
4. **Orphans**: memory files with no corresponding source → flag (don't delete). `memory/L2/archive/` pages are exempt — their source is the `archive_of:` parent.
5. **Symlink health**: `<brain_root>/CLAUDE.md` resolves to `AGENTS.md`; `GEMINI.md` resolves to `AGENTS.md` if gemini is installed.
5b. **DEVELOPER.md marker integrity**: `<!-- BEGIN/END GENERATED: brain-rebuild-memory:developer-counts -->` each appear exactly once (or the phase aborted and reported it, per 3.5b-1); everything outside the block and outside `## Developer Traps` is byte-for-byte unchanged from before this run's edits.
6. **Compaction**: for every rewritten file, `bytes before → after` is recorded, and any file that GREW has a stated reason (see "Compaction — facts over history").
7. **Size caps**: every file rewritten this run is ≤ 40 KB; additionally flag any `memory/` file > 50 KB (gbrain's warn threshold) in the digest. If an over-cap file is an accretive target, rotate it before finishing (see "Size Caps & Archive Rotation").
8. **Archive integrity**: closed-period archives were not touched this run (mtimes unchanged); every archive page has a `Topics:` footer linking its parent; every rotated parent has an `## Archive` section with one `[[wikilink]]` bullet per archive page.

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
- **Compaction summary**: per rewritten file, `bytes before → after` and one line on what was compacted away (see "Compaction — facts over history"). **Name any file that GREW, with the reason** — growth is the exception and needs justifying, not the default.
- Top-level nav: `AGENTS.md` regenerated y/n; symlink status for `CLAUDE.md` and `GEMINI.md`
- Changes summary (what was added, updated, removed)
- Broken links found
- Items flagged for review

Finally, write the updated `memory/.rebuild-state.json` with fresh `max_mtime` + `content_hash` for every target (including skipped ones — their mtimes may have advanced even if content matched).

---

### ⚠️ What to put in a worker's dispatch prompt — and what to leave out

**Name `SKILL.md` and the phase. Never name a reference a worker will not execute.**
The split exists so a leaf worker pays 42,814 B instead of 87,651 B; telling it to
"read the skill and its references" throws that saving away in one line.

| Give the worker | Do NOT give the worker |
|---|---|
| `.claude/skills/brain-rebuild-memory/SKILL.md` | `references/agents-md.md` — Phase 3.5 is yours |
| Its bounded target list and their declared `inputs` | `references/validation.md` — Phase 0 already ran |
| The 2–3 findings that bear on ITS targets | `references/orchestration.md` — this file |
| The path to the run briefing, for anything else | The whole findings register pasted inline |

⚠️ **Findings go in ONE briefing file and are referenced by path.** Measured 2026-09-10: the same
~10K-token block pasted into eight prompts cost ~80K tokens of pure duplication.

