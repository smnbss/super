# Reference — Phase 3.5: the top-level `AGENTS.md` and `DEVELOPER.md`

⚠️ **ORCHESTRATOR ONLY. A leaf worker rebuilding one page never needs this file.**
It is split out of `SKILL.md` because every worker used to pay its 25 KB to read rules for a
job only the final step performs.

## Phase 3.5 — Top-level AGENTS.md (brain navigation doc)

Every AI coding assistant that lands in the brain project — Claude Code, Gemini CLI, Codex, others — reads a root-level nav doc at session start. This phase generates a single canonical file (`AGENTS.md`) and exposes it under the other conventional names via symlinks so we never drift between copies.

**Anchor:** `<brain_root>` = the project directory found by the existing `$BRAIN_CONFIG` walk (same anchor as the rest of this skill). Never write to `$HOME`.

### ⚠️⚠️ 3.5a-0. AUDIT the hand-maintained open-decisions register. Never edit it. Always report it.

Most brains keep a hand-written **open-decisions register** at the very top of `AGENTS.md`, outside
every marker. **This skill may not edit it** — 3.5a's byte-for-byte preservation rule covers it
absolutely. But an unowned section with no budget and no eviction rule grows forever, and this one
does: measured 2026-09-10 it was **18,618 B, 13% of the whole file**, carrying 25 items, several of
them already closed.

**So audit it every run and report, in the Phase 5 digest:**

1. Its **byte size**, measured from disk.
2. Its **item count**.
3. ⚠️ **Every entry marked ✅ RESOLVED or ✅ CLOSED whose resolution is already recorded on
   `[[hub]]`.** Name each one and say it is droppable. The register usually says so itself — "a
   closed decision does not belong at the top of the always-loaded file" — and nothing enforces it,
   so closed entries sit there for weeks paying full context on every worker boot.
4. Any entry whose **detail duplicates a trap block verbatim**. The register should state the
   decision and point at the mechanism, not restate it.

⚠️ **REPORT, DO NOT EDIT.** A human decides what is closed. **An agent must never mark a decision
resolved on its own** — that is the standing rule that a ✅ RESOLVED marker on this brain's own
record is a CLAIM, not a measurement, and it has been falsified on six consecutive days before now.

### 3.5a. Regenerate ONLY this skill's block in `<brain_root>/AGENTS.md`

⚠️⚠️ **NEVER REWRITE THE WHOLE FILE.** `AGENTS.md` belongs to the brain it runs in, not to this
skill. Most of it is hand-maintained knowledge about *that* brain — its sources, its repos, its
tooling, its open decisions — and a rebuild that regenerates the file wholesale destroys work no
generator can reproduce. This skill owns **one demarcated block** and nothing else:

```markdown
<!-- BEGIN GENERATED: brain-rebuild-memory -->
…this skill's content, and only this skill's content…
<!-- END GENERATED: brain-rebuild-memory -->
```

**Marker contract — follow it exactly:**

| State of the file | What to do |
|---|---|
| Both markers present, once each | Replace **only** the text between them |
| Neither marker present | Insert the block once, directly **before the first `## ` heading** (so navigation sits near the top), and say so in the Phase 5 digest |
| Exactly **one** marker present | **ABORT. Change nothing.** Report it — a half-marked file must never be guessed at |
| Either marker appears more than once | **ABORT. Change nothing.** Report it |

- Everything before `BEGIN` and after `END` is preserved **byte for byte** — including blank lines,
  section order and trailing whitespace. Do not reflow, reorder, retitle or "tidy" the host file.
- Emit **nothing** outside the block. If a fact does not describe `memory/`, it does not belong to
  this skill, however useful it is.
- Apply the same content-hash short-circuit as Phases 2/3: if the regenerated block matches what is
  already between the markers, do not rewrite the file at all.

**Dirty when** `hub.md` is dirty, when the L1/L2/archive inventory changed, or in full-rebuild mode.
A change under `src/`, `github/` or `outputs/` does **not** make *this* block dirty — it makes the
**repository-layout** block dirty instead (3.5a-2), which is a different block with a different
contract.

**Block content — four items, all about `memory/` and nothing else:**

1. **Memory Layout** — a fence covering `memory/L1/`, `memory/L2/` and `memory/L2/archive/` only,
   with counts **re-measured from disk this run** (`ls memory/L1 | wc -l`, `ls memory/L2/*.md | wc -l`,
   `ls memory/L2/archive/*.md | wc -l`) and one line on what each layer is for. **Never copy a count
   from the AGENTS.md already on disk** — stale counts have survived multiple rebuilds by being read
   back out of the previous output instead of recomputed. ⚠️ **Do not describe `src/`, `github/` or
   `outputs/` here.** Those are the brain's own layout, hand-maintained outside the block.
2. **How to Navigate** — the 4-step path starting at `memory/L1/hub.md`, a `Quick Access` list of the
   highest-signal L1 pages, and a **`### Knowledge Map`** subsection indexing every L1 MOC grouped by
   theme, each showing the L2 pages it connects to as `[[wikilinks]]`. Derive the groupings and the
   L1→L2 edges from the just-rebuilt files (the Phase 3 derivation table plus each L2's `Topics:`
   footer). This is the traversal spine and must match the real link graph.
   ⚠️⚠️ **THE KNOWLEDGE MAP IS A LINK GRAPH, NOT A DIGEST. THE EVICTION RULE IN §3.5a-2 APPLIES HERE
   TOO.** Each entry gets the L1 page name, a SHORT standing gloss of what that page is for, and its
   `[[wikilinks]]`. **It does NOT get a paragraph of what that page's newest dated entry says.**
   Measured 2026-09-04: this subsection had grown to 24,626 B carrying 39 ⚠️ markers, because each run
   appended its own findings under the L1 it touched — "Its 2026-09-04 entry records…". **That prose
   belongs on the L1 page itself, which already has a cap and a rotating archive. Write it there and
   link to it here.** ⚠️ The navigation RULES that live in this section are durable and stay: the
   deleted-doc wikilink guard, both halves of the `.db.agent.md` guard, and the `erp-buddy` inverted
   case. **Never drop those to save bytes** — they are named in the carry-through rule below.
3. **Freshness Tracking** — the `verified:` fact-block convention, `staleness_threshold:` frontmatter,
   the `superseded:` marker, and the rule that a claim wrong in *every* clause is deleted rather than
   annotated.
4. **Memory page naming** — the constraints this generator must itself obey, because it is the thing
   that creates these filenames: extensions must be lowercase `.md` (gbrain's `isMarkdownFilePath`
   tests `path.endsWith('.md')` case-sensitively, so an uppercase `.MD` page is rejected with reason
   `strategy` and silently never indexed, with no config surface to rescue it); and **never name a
   curated page `index.md`, `README.md`, `log.md` or `schema.md`** — `SYNC_SKIP_FILES` is tested on
   the basename before any include/exclude glob, so such a page is silently never indexed while
   `gbrain sync` still exits 0. Also restate the rule against introducing a wikilink to a deleted
   doc; name it in a code-span instead.

⚠️⚠️ **CARRY-THROUGH RULE — a regeneration must not silently drop a caveat.** This block is
regenerated rather than merged, which makes it the one place where a hard-won warning can vanish
without trace. So: **every trap, caveat or correction already inside the block survives the rewrite
unless you can show it is false.** Refresh the counts and the link graph around them; do not quietly
drop a `⚠️` line because it is not in the four-item spec above. In particular the block must always
carry, because nothing else states them:

- the **archive-rotation caveats** — rotation is cap-driven, not age-driven, so a rotated section is
  not old or superseded; an archive's period label is the *rotation* period, not the content period,
  so never infer a date from a page name; and **never read a count out of an archived section**,
  because an archived figure was right only on its own date.
- the **deleted-doc wikilink guard, both halves** — never introduce a `[[link]]` to a deleted
  `.agent.md` *or* `.db.agent.md`; name it in a code-span. Confirm a `.db` doc exists on disk before
  linking it, since its absence is now the common case.

If you believe a caveat is obsolete, **say so in the digest with the evidence** and let a human drop
it. Deleting it silently is the failure this rule exists to prevent.

**Explicitly NOT this block's business — never emit here, never touch:** gbrain server, jobs-worker
or reindex configuration; the reindex runbook; External Tools and CLI inventories; skill routing;
skill-editing conventions; agent-dispatch rules; and any open-decisions register. All of that is the
brain's, hand-maintained outside every marker. **If something in that list is currently inside this
block, move it out rather than regenerating it** — and say so in the digest.

The `src/` / `github/` / `outputs/` layout is **not** in this block either, but it is not off-limits
to the skill: it has its own block and its own merge contract in **3.5a-2** below. Counts there are
refreshed; **annotations there are never rewritten.**

### 3.5a-2. Update the Repository Layout block — MERGE, never regenerate

The brain's `## Repository Layout` section is a **second, separately marked block**, and it obeys a
**different contract from 3.5a**:

```markdown
<!-- BEGIN GENERATED: brain-rebuild-memory:repository-layout -->
<!-- END GENERATED: brain-rebuild-memory:repository-layout -->
```

The same marker rules apply (both present → work inside them · neither → insert before the existing
`## Repository Layout` heading and report · exactly one, or either twice → **ABORT, change nothing**).
What differs is what you may do inside.

⚠️⚠️ **THIS BLOCK IS A MIX OF DERIVED AND HAND-WRITTEN CONTENT, AND YOU CAN ONLY TOUCH ONE OF THEM.**
The tree structure and the file counts are derivable from disk. **Every annotation line is not** — the
⚠️ traps, the corrections, the "never read a count out of an archived section" warnings are knowledge
a human or a prior run paid for, and no generator can reproduce them. A regeneration of this block
destroys them silently and the loss is invisible until someone acts on a trap that is no longer
written down.

**So merge, line by line:**

| Case | Action |
|---|---|
| Source already listed | Update **only** its count/figure text. Copy every **durable** line of its entry through **verbatim**. A dated run-log line is not durable — see the eviction rule below. |
| Source on disk (or in `sources.md` / `sources.github.md`) but **absent** from the block | Add a minimal entry — name, path, counts — and **flag it in the Phase 5 digest as needing annotation.** Never invent a trap note. |
| Entry present but its tree is **gone** | Remove the entry, and **name in the digest every annotation line you dropped with it**, so a real caveat can be re-homed rather than lost. |
| Anything you cannot classify | Leave it exactly as it is and report it. |

#### ⚠️⚠️ The eviction rule — this block is NOT a changelog, and without this rule it can only grow

**Measured 2026-09-04: `AGENTS.md` reached 210,519 B, about 58,500 tokens loaded into every session
on every surface, because `CLAUDE.md` and `GEMINI.md` are symlinks to it. `## Repository Layout` was
125,983 B of that — 59.8%. Of that block, only 2,645 B was actual path-and-gloss layout. The other
123,337 B, 98% of the block, was dated narrative.** The cause was the merge contract above: it said
copy every other line through verbatim, and nothing ever said what to stop copying. Each run appended
another dated paragraph and no run ever removed one.

**Every annotation line in this block is one of two kinds. Classify each one before you copy it.**

1. **A DURABLE TRAP** — a timeless operational constraint with no run date attached. "Spreadsheets
   export the first sheet only." "Cite by `gdrive_url`, never by path." "`metadata.json` `attendees`
   is the invite list, not the attendance list." "Unique-count, never line-count." **Copy these
   through verbatim, forever. The carry-through rule above governs them and does not change.**
2. **A DATED RUN-LOG LINE** — it opens with or contains a specific date, and it reports what one run
   measured. "2026-08-24: 3 repos moved HEAD." "This run's pull reported 60 new and 65 pruned."
   **Do NOT copy these through. They do not belong in this block at all.**

**Where a dated line belongs instead.** Every source in this block already has an owning `memory/L1`
page with a working cap and a rotating archive. `src/gdrive/` → [[gdrive]]. `src/confluence/` →
[[confluence]]. `src/linear/` → [[linear]]. `src/metabase/` → [[metabase]]. `src/idp/` and
`outputs/services/` → [[services]]. `github/` → [[github]]. `src/personio/` → [[team-members]].
`src/gmeet/` → [[meetings]]. `src/workflowly/` → [[workflowy]]. **Write the dated fact to that page,
which Phase 3 already does. Then leave it out of here.** This block carries the CURRENT count and the
durable traps, and points at the owning page for the history.

⚠️ **This is not a licence to drop a caveat.** A line carrying a date AND a durable rule is durable —
keep it, and keep its date, because the date is part of the claim. When in doubt, treat the line as
durable and keep it. **The failure this rule prevents is unbounded growth, not thoroughness.** The
carry-through rule still outranks brevity.

#### ⚠️⚠️ Class 3 — a durable trap ALREADY WRITTEN on its owning page. Keep the pointer, not the text.

**Evicting only dated lines is not enough, and the measurement says so. Durable traps accumulate
too.** Measured 2026-09-10: `AGENTS.md` reached 139,414 B, about 34,000 tokens, and it loads into
every interactive session AND into each of ~30 nested worker boots per morning run. `## Repository
Layout` was 60,927 B of that, 44%. **Only 4,552 B was path-and-gloss layout. `### Durable traps, by
source` alone was 34,884 B, a quarter of the whole file** — and every line of it was class 1, so the
eviction rule protected all of it and the block grew anyway. That run added roughly 9 KB of
genuinely new durable traps in a single day.

**A trap does not have to live in the always-loaded file to be enforced. It has to live where the
agent that could trip it will read it.** Every source in this block already has an owning
`memory/L1` page, and that page already carries the same traps: a 21-phrase probe across
`confluence`, `gdrive`, `github`, `linear`, `metabase`, `personio`, `gmeet`, `idp` and `outline` on
2026-09-10 found **21 of 21 already duplicated** on the owning page. The block was paying ~35 KB per
worker boot to restate what the worker reads anyway.

**So classify every durable trap a third way, and prefer class 3:**

3. **A DURABLE TRAP THAT IS ALREADY WRITTEN, IN FORCE, ON ITS OWNING `memory/` PAGE** — keep a
   **pointer** in this block, not the trap text.

**The eviction is conditional on proof, and the proof is a grep. Never evict on assumption.**

```bash
# Before you move a trap out, confirm the owning page really carries it.
grep -qiF -- '<distinctive phrase from the trap>' memory/L1/<owner>.md && echo SAFE || echo WRITE-IT-FIRST
```

| Probe says | Action |
|---|---|
| `SAFE` | Replace the trap text here with a pointer line. The trap is not lost, it is one hop away. |
| `WRITE-IT-FIRST` | ⚠️ **Write the trap onto the owning page FIRST, in this same run, then evict.** A trap that exists in exactly one place may not be deleted from that place. |
| You cannot identify an owning page | **Keep the trap here verbatim** and flag it in the Phase 5 digest. A trap with no home stays in the always-loaded file. |

**What the block keeps instead: a routing table, one line per source**, naming the path, the current
count, and the owning page an agent MUST read before it touches that source. That is strictly
stronger than today, where the traps are technically present but buried in 35 KB that a worker skims.

⚠️⚠️ **THREE KINDS OF TRAP NEVER LEAVE THIS FILE, whatever the probe says.** They are the ones that
fire *before* an agent has read any page, so a pointer is too late:
1. **Traps about the memory system itself** — the page cap, the archive rotation rules, the
   `SYNC_SKIP_FILES` basenames, the deleted-service-doc wikilink guard, the uppercase-extension gate.
2. **Traps that govern how an agent is DISPATCHED** — above all the `subagent_type:
   "general-purpose"` hook rule, which must be obeyed before any worker exists to read anything.
3. **Traps about measurement discipline in general** — re-measure from disk, never carry a count
   forward, state the scope of a negative result, a resolved marker is a claim not a measurement.

⚠️ **This rule moves traps. It never deletes one.** If a run cannot prove the owning page carries a
trap, that trap stays. **The carry-through rule still outranks every byte target in this section**,
and class 3 exists precisely so that obeying it no longer forces the file to grow without bound.

#### Byte budget — measure it, and report a breach

`AGENTS.md` had no cap and no rotation target for its whole life, which is why it grew unbounded
while every `memory/` page stayed inside 40,960 B. It now has one.

```bash
stat -f '%z' AGENTS.md          # whole file  — target ≤ 61,440 B (60 KB), hard warn at 81,920 B
```

- **Per-block targets: `brain-rebuild-memory` ≤ 24,576 B · `repository-layout` ≤ 12,288 B.**
- These are **budgets, not shears.** ⚠️ **Never drop a durable trap to hit a number** — the
  carry-through rule wins, exactly as it does for the `memory/` page cap. If the block cannot fit
  inside its budget on durable content alone, **say so in the Phase 5 digest and let a human decide**,
  the same way an over-cap service doc is escalated rather than silently cut.
- Report the whole-file size and both block sizes in the Phase 5 digest **every run**, breach or not.
  A number nobody prints is a number nobody notices moving.

⚠️⚠️ **ORDER OF OPERATIONS WHEN THIS FILE IS OVER BUDGET — and it is the same order every `memory/`
page uses. Do NOT skip to the last rung.**

1. **Evict class 2** (dated run-log lines) to the owning page. Free, and already mandatory.
2. **Evict class 3** (durable traps the owning page provably carries) to a pointer. **This is the
   rung that was missing until 2026-09-10, and it is why the file could only grow.** A run that
   reports a breach without having applied class 3 has not finished its job.
3. **Only then** report the residue and let a human decide.

**Why this file needs its own rung 2 and a `memory/` page does not:** a `memory/` page rotates into
a dated archive under `memory/L2/archive/`. **`AGENTS.md` has no archive and cannot have one** — it
is a single always-loaded file, not a period-stamped series. **Its rotation target is the owning
`memory/L1` page**, reached by pointer. Class 3 IS this file's rotation mechanism. Treat it as such.

⚠️ **Weigh a byte here against ~30 worker boots, not one.** `CLAUDE.md` and `GEMINI.md` are symlinks
to `AGENTS.md`, and a morning run boots roughly 30 nested workers that each pay the whole file. At
139,414 B that is about 1M tokens per run for this file alone. **A kilobyte removed here is ~30 KB
of context returned across the run** — which is why the skill's own cost discipline names "a smaller
`AGENTS.md`" as one of only three real levers, alongside fewer workers and fewer enabled plugins.

- **Re-measure every count from disk this run.** Never read a figure back out of the block you are
  about to rewrite — that is precisely how a stale count survives many rebuilds.
- Counts to refresh include the per-source file totals, the tracked-clone count for a monorepo
  container (from its registry, not a subdirectory count), and the `outputs/` doc totals.
- **`memory/` is NOT described here.** It lives in the 3.5a block. Keep the two disjoint.

### 3.5b. Top-level DEVELOPER.md (developer onboarding guide) — NEW 2026-08-26, Simone's call

`DEVELOPER.md` is a hand-curated developer guide (setup steps, `bin/` script commands, env-var
conventions, troubleshooting recipes). **Most of it never changes and this phase must never touch
it.** Two parts of it do go stale on their own, silently, because the numbers and claims they carry
are already computed correctly elsewhere in this same skill run (or in `brain-rebuild-services`) and
nothing currently pushes that back into this file. That drift is real, not hypothetical: the file's
own cap-breach line said "22 files... exceed the 40,960-byte cap" on 2026-08-26, the same day that
cap was raised to 65,536 B and the true count dropped to 4 — the file was already wrong the moment
the decision landed, because nothing told it.

**Anchor:** same `<brain_root>` as the rest of this skill.

#### 3.5b-1. Regenerate ONLY the "Key Resources counts" block — same marker contract as 3.5a

```markdown
<!-- BEGIN GENERATED: brain-rebuild-memory:developer-counts -->
<!-- END GENERATED: brain-rebuild-memory:developer-counts -->
```

Same marker rules as 3.5a (both present → replace between them · neither → insert directly after the
existing `## Key Resources` heading and report · exactly one, or either twice → **ABORT, change
nothing**). Same content-hash short-circuit: if the regenerated block matches what's already there,
don't rewrite the file.

**Block content — every count/cap claim currently scattered through `## Key Resources`, re-measured
from disk this run, never copied from the file already on disk:**
- `outputs/services/` file counts (`*.agent.md`, `*.db.agent.md`, total) and its byte cap — **the cap
  value itself is hand-set policy** (currently 65,536 B, see `brain-rebuild-services/SKILL.md`
  "Changelog & size discipline" — read it from there, never hardcode a remembered number), but the
  *count of files over it* is derived and must be re-measured every run.
- `src/idp/` scale (services, total files) and its "declared but unserved" doc-gap breakdown, read
  from `src/idp/catalog.md`'s own table, never carried forward.
- `src/outline/` scale (file count, collection count via `find -mindepth 1 -maxdepth 1 -type d`, not
  a bare `-maxdepth 1` which double-counts the root).
- The service→team map's "all N services" figure in `## Service → Team Map`, matching `src/idp/catalog.md`.

**Dirty when** `outputs/services/`, `src/idp/`, or `src/outline/` changed this run, when the
`outputs/services/` cap value itself changed, or in full-rebuild mode.

#### 3.5b-2. Merge-review the "Developer Traps" section — NEVER regenerate wholesale

Same principle as 3.5a-2's Repository Layout block: **each trap bullet is a hand-won caveat a
generator cannot reproduce, and a wholesale rewrite destroys it silently.** This section is merged,
never regenerated:

| Case | Action |
|---|---|
| A trap's underlying fact changed this run (surfaced by 2b service-doc regen, 2c IDP catalog re-measurement, 2a GitHub HEAD-move detection, or a meeting-harvest Brain Update) | Update that bullet in place with the new fact. **Never delete a trap silently** — if it's fully resolved, prefix it `✅ RESOLVED <date>:` and keep one line of what changed, matching the house convention used everywhere else in this brain. |
| A new fact from this run is genuinely trap-shaped — a developer will trip over it locally, not just "interesting to know" — and isn't already covered | Add a new bullet, sourced, at the end of the list. **Only when it's squarely developer-facing** (breaks local dev, a removed dependency, an auth/env change, a footgun in a script) — not every service-doc finding belongs here; most belong in `outputs/services/**/<repo>.agent.md` instead, which already exists for that. |
| Nothing relevant changed this run | Leave the section untouched. |
| Uncertain whether a bullet is still current | Leave it as-is and flag it in the Phase 5 digest rather than guessing. |

**Never touch anything outside `## Developer Traps` and the marked counts block** — Prerequisites,
First-Time Setup, Running Services, Database Operations, Repo Management, Per-Repo Local Dev
Commands, Troubleshooting and Environment Variables Convention are all hand-maintained and out of
scope for this phase, however tempting a stale-looking line in them might be. If one of those looks
wrong, flag it in the digest for a human — do not edit it.

### 3.5c. Symlinks for other assistants

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

