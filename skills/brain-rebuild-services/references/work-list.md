# Reference — building the service-doc work-list

⚠️ **ORCHESTRATOR ONLY. A leaf worker is handed its target doc and its delta base; it never
builds the work-list.** Split out of `SKILL.md` because every doc worker used to pay ~11 KB to
read how the list it was already given got made.

### 0.1 The work-list is DIVERGENCE, not movement

> ⚠️ **CORRECTED 2026-08-14. This step used to say "read the ledger and process
> exactly the repos listed", and "an empty ledger is a complete answer". That was
> wrong, and it silently rotted docs.** The ledger records *"HEAD moved during this
> run"*, which is not the same question as *"is this doc behind its repo?"*. A repo
> whose HEAD moves on a day its doc is **not** regenerated — the run failed, was
> interrupted, hit a spend limit, or the clone was skipped — never appears in a
> later ledger, so a ledger-driven work-list can never repair it. It stays stale
> until that repo happens to move again, which may be never.
>
> Measured on the live brain, 2026-08-14: **14 of 100 docs were behind their clone's
> HEAD, and all 14 were absent from that day's 22-line ledger.** Two independent
> causes, neither visible to a movement ledger:
>
> | Cause | Docs | Clones | Which |
> |---|---|---|---|
> | Clone **dirty** → `github_clone` skipped it, so its HEAD *cannot* move during the run. Unreachable **by construction**, not by accident. | **9** | **8** | `api-catalog.db`, `api-payments.db`, `api-spendsync.db`, `booking.db`, `cashew` **+** `cashew.db`, `community.db`, `message-board.db`, `my.db` |
> | Clone **clean**, HEAD simply moved on a day the doc was not regenerated. | 5 | 5 | `super`, `api-draghi`, `api-partner.db`, `api-travel-catalog.db`, `cli` |
>
> **9 docs but 8 clones** — `cashew` carries both `cashew.agent.md` and
> `cashew.db.agent.md`, so a per-clone count and a per-doc count differ. State which
> one you mean; the work-list is counted in **docs**.
>
> ⚠️ **Two of the five clean ones are on non-default branches** — `api-partner` on
> `ai-creation`, `cli` on `fix/wr-personio-stale-cdp-port` (4 ahead of `origin/main`).
> `git rev-parse HEAD` there is a *branch tip*, so a doc regenerated from it
> **documents a feature branch, not `main`**. Report the branch in the sweep output
> whenever it is not the default, and never let a doc silently describe unshipped
> work as production architecture.

**Compute the work-list by comparing every doc's recorded `head:` against its
clone's actual HEAD.** This is a deterministic shell sweep over ~100 docs — about a
second, and **zero model requests**, which is the entire point: it replaces a
model-derived work-list with a measured one. Nothing about the cost discipline below
changes; this only fixes *which* repos the discipline is applied to.

```bash
# From the brain root. Prints one line per doc that needs work, and why.
find outputs/services -name '*.agent.md' | while read -r DOC; do
  REL=${DOC#outputs/services/}; BASE=$(basename "$DOC")
  REPO_NAME=$(printf '%s' "$BASE" | sed -E 's/\.(db\.)?agent\.md$//')
  DIR="github/$(dirname "$REL")"; REPO="$DIR/$REPO_NAME"
  # Monorepo-container docs name the directory they live in, not a child of it
  # (jungle/jungle.agent.md -> github/weroad/jungle). Fall back ONLY in that case:
  # a blanket "parent is a repo" fallback silently maps every deleted-clone doc to
  # its parent monorepo and compares it against the wrong HEAD.
  [ -d "$REPO/.git" ] || { [ "$REPO_NAME" = "$(basename "$DIR")" ] && REPO="$DIR"; }
  # Deliberately NO walk-up-to-nearest-.git here. It looks like the general fix and
  # is worse than none: from github/weroad/jungle/<x> it lands on the jungle
  # container for every missing clone, which is how the frozen coordinators docs got
  # queued against the wrong HEAD. Workspace docs are handled by triage below, not
  # by guessing — api-rooming's host is buynana, which no walk-up would ever find.
  if [ ! -d "$REPO/.git" ]; then echo "UNRESOLVED	$REL	(no clone)"; continue; fi
  RECORDED=$(sed -n 's/.*head: \([0-9a-f]\{7,\}\).*/\1/p' "$DOC" | head -1)
  if [ -z "$RECORDED" ]; then echo "NO-STAMP	$REL	$REPO"; continue; fi
  R=$(git -C "$REPO" rev-parse -q --verify "$RECORDED^{commit}" 2>/dev/null || echo unknown)
  A=$(git -C "$REPO" rev-parse HEAD)
  # Flag a non-default branch and a dirty tree: HEAD on a feature branch means a
  # regenerated doc would describe unshipped work, and a dirty clone is one
  # github_clone skipped — the reason it is missing from the ledger at all.
  BR=$(git -C "$REPO" rev-parse --abbrev-ref HEAD)
  case "$BR" in main|master) BRN="";; *) BRN=" branch=$BR";; esac
  [ -n "$(git -C "$REPO" status --porcelain)" ] && BRN="$BRN dirty";
  [ "$R" = "$A" ] || echo "DIVERGED	$REL	$REPO	${RECORDED:0:8}..${A:0:8}$BRN"
done
```

Three rules this encodes, each of which cost something to learn:

- **A doc basename is a SERVICE name; a clone is a REPOSITORY. The mapping is
  many-to-one, and the IDP is the authority — not the filename.** Confirmed against
  `mcp__idp__list_services` on 2026-08-14: **16 repositories host more than one
  service** — `weroad/buynana` alone hosts four (`api-buynana`, `admin-buynana`,
  `tour-planner-buynana`, `api-rooming-buynana`), and `booking`, `my`, `community`,
  `beye`, `starter` host three each. Most docs happen to be named after their repo,
  so the convention usually works; where it doesn't, **resolve the service in the IDP
  and gate against `service.repository`**.

- **`UNRESOLVED` must be REPORTED and TRIAGED, never silently skipped and never
  blind-regenerated.** A doc whose clone cannot be found is invisible to any
  "diverged" count, so a broken mapping reads as a clean bill of health. Three causes,
  three different actions — do not collapse them:

  | Cause | Docs today | Action |
  |---|---|---|
  | Repo never cloned (absent from `sources.github.md`) | `personio-mcp-server`, `paperclip` | Report. Add to the manifest if it should be tracked. |
  | **Service of a monorepo** — the doc is named after a service, its repo is the monorepo | `api-rooming` and `tour-planner-buynana` → `weroad/buynana`; `admin-coordinators` and `api-coordinators{,.db}` → `weroad/coordinators` | Gate against the **monorepo** clone (`github/weroad/jungle/{buynana,coordinators}`). Both are cloned, so all four are gateable — they were never truly unresolvable. |
  | **Frozen `SUPERSEDED` doc** | `admin-coordinators`, `api-coordinators{,.db}` | Gateable, but **frozen by policy: never regenerate.** They describe the pre-consolidation repos. Note the IDP still lists both services against `weroad/coordinators` — the *repository* was consolidated, the *deployed applications* were not. |

  ⚠️ **A stale clone is worse than a missing one — and "the IDP knows it" is three
  different states, not one.** `list_repositories` and `list_services` answer
  different questions and must both be consulted:

  | IDP state | Meaning | Examples (2026-08-14) | Doc handling |
  |---|---|---|---|
  | registered **and** hosts ≥1 service | live | `my`, `api-myweroad`, `buynana`, `booking` | gate normally |
  | **registered but hosts NO deployed service** | repo still exists; its service moved into a monorepo | **`api-rooming`** — the service is `api-rooming-buynana`, shipping from `weroad/buynana` | the clone is a **decoy**: gating against it reports "unchanged" forever against a repo that ships nothing. Gate the doc against the **host monorepo**, or retire the doc. |
  | **not registered at all** | fully consolidated away | `admin-myweroad`, `myweroad` → `weroad/my`; `admin-coordinators`, `api-coordinators` → `weroad/coordinators` | clone is a deletion candidate (this is how the coordinators clones were cleaned up 2026-08-04) |

  `github/weroad/api-rooming` is a live clone at `7ce5e41` **and a registered IDP
  repository** — so a "is it in the IDP?" check passes and tells you nothing. The
  test that matters is **does any deployed service map to it**. Checking only
  `list_repositories` is how a doc ends up gated against a decoy.

- **The container fallback must be narrow, and there must be no walk-up.**
  `weroad/jungle/jungle.agent.md` documents the jungle monorepo *container* at
  `github/weroad/jungle`, not a child `github/weroad/jungle/jungle`, so a fallback is
  needed — but only when the doc's repo name equals its parent directory's name.
  Two tempting generalisations are both **wrong**, and each was tried and rejected
  while writing this: a blanket "if the child is missing, use the parent" mapped all
  three frozen coordinators docs onto the jungle container and queued them for a full
  read; and "walk up to the nearest `.git`" does the same thing for *every* missing
  clone under `jungle/`, while still not finding `api-rooming`'s real host
  (`buynana`, which no upward walk reaches). Guessing a repo is worse than reporting
  that you cannot resolve one.

Verified on the live brain, 2026-08-14. The sweep above uses the filename convention
and prints **14 `DIVERGED`, 23 `NO-STAMP`, 7 `UNRESOLVED`, 56 matched = 100**, with
`jungle.agent.md` correctly matched rather than reported stale. Triaging the 7
through the IDP moves 5 of them into `NO-STAMP` — `api-rooming` and
`tour-planner-buynana` gate against `buynana` (HEAD `72894668e`),
`admin-coordinators` and `api-coordinators{,.db}` against `coordinators`
(HEAD `3a48816d1`) — leaving the true picture:

| | convention only | after IDP triage |
|---|---|---|
| `DIVERGED` | 14 | 14 |
| `NO-STAMP` | 23 | 28 |
| `UNRESOLVED` | 7 | **2** (`personio-mcp-server`, `paperclip` — genuinely uncloned) |
| matched | 56 | 56 |

So the work-list is **14 docs behind their repo** plus **28 unstamped**, of which 3
(`admin-coordinators`, `api-coordinators{,.db}`) are frozen and must be stamped-and-
skipped rather than regenerated.
- **`NO-STAMP` counts as needing work** (and the pass must emit `head:`, per 0.2).
  30 of 100 docs carry no stamp today, so they can never take the cheap path.
  Treating them as work is what drains that backlog instead of freezing it.
- **An empty divergence set IS a complete answer** — report "0 docs behind their
  repos" and stop. An empty *ledger* is not.

**The ledger is now an optimization hint, not the source of truth.** Keep using
`.github-changed-repos.tsv` for what it is genuinely good at:

```
<owner>/<repo>	<reldir>	<before_sha>	<after_sha>
```

- Its `before_sha` is the **delta base** for 0.3 when the repo moved this run.
- It is a **cross-check**: a repo in the ledger that the sweep says is *not*
  diverged means the doc was already regenerated this run — expected, not a bug.
  A diverged doc *absent* from the ledger is the case above, and is the norm rather
  than the exception.
- ⚠️ **Read it only after `pull_sources` has exited** — it is written incrementally,
  so mid-run it is a well-formed but short list (7 lines read against a true 22).
- Invoked **with** a repo name: honour it even if the sweep says unchanged (the user
  asked), but still run 0.2 — the answer is usually "unchanged, nothing to do".
- Ledger absent: nothing is lost. The sweep does not depend on it.

