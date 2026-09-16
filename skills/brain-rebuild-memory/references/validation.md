# Reference — Phase 0: validating the brain's measurable claims

⚠️ **ORCHESTRATOR ONLY, and it runs BEFORE any worker is dispatched.**

## Phase 0 — Validate the brain's own measurable claims. ZERO model requests.

```bash
bin/validate-brain-claims          # from the brain root; exit 1 on drift
```

Run this **before** any expensive phase, the same way the service-doc divergence gate runs before
a worker is dispatched. It re-runs every claim in `memory/.brain-claims.tsv` — a TSV of
`id · predicate · expected · owning page` — and reports where **disk no longer agrees with what a
live page asserts**. One shell call, no model requests, about a second.

**DRIFT is not a bug in the registry. It is the registry doing its job.** Update the **page and the
registry together** — a registry edited alone stops describing what the brain says, and the check
goes quiet while the page stays wrong.

⚠️⚠️ **A BROKEN PREDICATE IS NOT A PASS.** The runner reports one separately and exits non-zero,
because a predicate that returns nothing reads exactly like a clean result — the standing trap, and
the reason this file already carries two worked examples of scoped searches that missed
(`github/weroad/helm-charts` and `github/weroad/ai/`, neither of which exists).

**Add a claim to the registry whenever you write a number into a live page that a shell command can
re-derive.** That is the whole maintenance burden, and it is what keeps the check honest as the
brain grows.

### The marker vocabulary — three tiers, and a ratchet that enforces them

⚠️ **A marker on half the lines is not a warning system, it is decoration.** Measured 2026-09-10
before this rule landed: **25% of all non-blank lines** across `AGENTS.md` + `memory/L1` + `L2`
carried a marker, and **40–51% on the densest pages**. That is how a banned figure — the
`wemeet-hosted-ops` cron at "26 of 26" against a measured 29 — survived a rebuild on a page that
same run had rewritten. Nobody reads the 87th warning on a page.

| Marker | Means | Test before you use it |
|---|---|---|
| 🚨 | **Blocks a decision. A human must act.** | Can you name the person and the decision? If not, it is not 🚨. |
| ⚠️ | **A durable trap: doing X gives a wrong answer.** | Can you name the wrong answer someone would get? If not, it is not ⚠️. |
| *(none)* | A finding, a consequence, a scope qualifier. | Use **bold**. A scope qualifier reads better inline: "treat as UNCONFIRMED", "scope of this negative". |

⚠️⚠️ **THE SECOND TIER IS ABOLISHED. Never write `⚠️⚠️`.** It meant "extra important" with no
stated threshold, which is the definition of inflation — 1,003 of them had accumulated against
4,557 singles. All were collapsed to `⚠️` on 2026-09-10. **A marker with no defined bar always
inflates; do not reintroduce one.**

⚠️ **A heading does not need a marker when its own body already carries one.** 121 such headings
were stripped in the same pass. The section still warns; the title stops shouting.

⚠️ **Rotation bookkeeping is not a hazard.** "Trigger: CAP-DRIVEN" records which rule fired. It
gets no marker. The *rule* it illustrates — "a cap-driven rotation can cut into the live window,
so say which trigger fired every time" — keeps one.

**Enforcement is a ratchet, in `memory/.marker-budget.tsv`, checked by Phase 0.** Each page
carries a ceiling. **A page may HOLD or LOWER its ceiling. It may never raise it.**

⚠️⚠️ **A FLAT CAP WAS CONSIDERED AND REJECTED ON MEASUREMENT.** The median live page carried 86
markers, so a cap of 10 would have put **41 of 47 pages over on day one** — an unreachable number
everyone learns to ignore, exactly like the 12,288 B `repository-layout` budget written the same
morning and breached by 5× within hours. **A ratchet is always reachable and only ever improves.**
Lower a ceiling whenever a page genuinely sheds a marker. Never edit one upward to make a run pass.

### ⚠️ What this can and cannot validate — do not oversell it

Measured on the WeRoad brain 2026-09-10 across `AGENTS.md` + `memory/L1` + `memory/L2`: **2,666
warning-bearing lines**, classified by whether a machine can check them.

| Class | Share | Mechanically checkable? |
|---|---|---|
| **A** — a shell predicate AND an expected value | **5%** (154) | ✅ **Yes. This is what Phase 0 covers.** |
| **B** — a number or date, but no predicate written down | **46%** (1,242) | ⚠️ Only after someone writes the predicate. **This is the growth area — every B converted to an A is a claim that can never rot silently again.** |
| **C** — a command with no expected value | 1% (47) | ⚠️ Runnable, but there is nothing to compare against. |
| **D** — a prose rule with no number and no command | **45%** (1,223) | ❌ **No. And that is correct** — "spreadsheets export the first sheet only" and "a scoped search that misses is indistinguishable from a clean result" are timeless operational rules, not measurements. They do not rot on a schedule. |

**So Phase 0 covers about a twentieth of the warnings today, and could cover about half.** The
honest reading: **it catches the class of error the brain actually keeps making — a stale number
asserted in the present tense** — and it catches nothing else. It is not a correctness proof for
the brain's knowledge.

⚠️ **Three false-positive shapes the runner cannot see, so a human must judge them:**
1. **A dated register section** is history, not a stale claim. `memory/L1/metabase.md` correctly
   keeps a `## register 2026-09-09 — 1,981 cards` block *below* its 2026-09-10 one.
2. **A supersession note** legitimately quotes the old figure — "up from 6,347 across 53", "any
   1,981 figure is SUPERSEDED". Quoting a banned number in order to ban it is correct usage.
3. **An archive pointer** citing what the archived section said on its own date.

**The failure this phase prevents, with the worked example that justified it.** On 2026-09-10 a
by-hand sweep of banned figures found three live pages asserting superseded numbers in the present
tense: `business-domains.md` said the `wemeet-hosted-ops` cron was **"26 of 26"** when the measured
truth was **29 of 29** — a figure `AGENTS.md` explicitly bans by name; `team-cyclops.md` said
**"NINETEEN files exceed the cap today"** against 18; `team-tium.md` said **"`src/outline` holds 53
collections"** against 57. All three had survived a rebuild that same morning, on pages that phase
had rewritten. **A rebuild does not re-check a number it did not happen to touch. Phase 0 does.**

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

🚨 **`outputs/services/` DOES NOT EXIST. DO NOT COUNT IT, DO NOT LOOK FOR IT, DO NOT REPORT IT
MISSING.** The weroad docs went on 2026-09-15 (50 files) and the last 5 non-weroad docs went on
2026-09-16. `brain-rebuild-services` is DELETED. **There is no service-doc validation step any
more.**

⚠️ **The `weroad/jungle/cross/` RabbitMQ trio and `TRAPS-from-deleted-docs.md` went with that
deletion. Do NOT list them, and do NOT report them missing.** They survive only in git:
`git show 8d4188326:outputs/services/<path>` — that sha holds all 55 files.

⚠️ **Never name a service doc, a byte figure or a carried count.** Any "64 `.agent.md`",
"7 `.db.agent.md`", "3 cross-cutting", "55 files" or "5 files" figure is STALE — never repeat one.

**Where a repo's architecture lives now:** `github/<org>/<repo>/docs/`, read
`docs/documentation-guide.md` first. Fall back to `src/outline` (docs.weroad.com) when a repo
carries no `docs/`.

---

