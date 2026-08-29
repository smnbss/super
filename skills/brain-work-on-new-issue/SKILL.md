---
name: brain-work-on-new-issue
description: >
  Open a NEW Linear issue for the next piece of work in a session that one of the
  `brain-work-on*` skills already set up — a local session from `brain-work-on`, or
  a cloud VM session from `brain-work-on-google-cloud` — then keep that work tracked
  as it runs. Use whenever the user starts a distinct new piece of work mid-session
  and says "new issue", "open a ticket for this", "track this in Linear", "log this
  as a separate issue", or "/brain-work-on-new-issue" — and also when a session that
  is already tracked in Linear pivots to something the current issue does not
  describe. Use it even when the user does not name Linear: if a session workspace
  exists and the work changes shape, a new issue is what keeps the board honest.
  Also use it to put the FIRST issue on a session that was created without tracking.
  Recovers the tracking context from the workspace on disk, confirms the project
  before writing anything, and never opens a second issue for work the current one
  already covers.
---

# Brain — Work On, New Issue

The `brain-work-on*` skills open a session and bind it to one Linear issue. This
skill opens the **next** issue in that same project when the work moves on to
something the current issue does not describe — and then keeps it updated as the
work runs.

It writes to Linear. It does not write code, and it does not re-run the context
load. The session already has that.

**Run it from the brain root, on the laptop.** The tracking record and the
workspace live under the brain's `outputs/`. On a cloud session the *code* is on a
VM, but the brain is not — an agent running on the VM has the repo and nothing
else, so it cannot read or update the pointer file.

## Session flavours

Any of these leaves a workspace this skill can pick up. They share one layout, so
what identifies the flavour is which marker files are present.

| Flavour | Opened by | Workspace | Marker files |
|---|---|---|---|
| Local | `brain-work-on` | `outputs/projects-work-on/<repo\|preset>/<session>/` | `.linear.json` |
| Cloud VM | `brain-work-on-google-cloud` | the same path | `.jungle-vm.json`, and `.linear.json` once tracked |
| Other family | any `brain-*` flow | `outputs/projects-<family>/<name>/` | `.linear.json` |

Local and cloud sessions share one layout, so the flavours differ only in which
marker files are present. The first segment is a repo, or a **jungle preset** — a
name selecting a whole stack rather than one repo (`partner` derives four compose
services, `my` likewise). A repo worked on both locally and on a VM groups under
one directory.

⚠️ **A pre-2026-08-29 cloud session is flat**, at `outputs/projects-work-on/<session>/`
— one level shallower, sitting exactly where a *repo* directory belongs. Nothing
writes that shape any more and the one known session was migrated, but a lookup
assuming a single depth still misses any that survive. Search both.

⚠️ **`WORKSPACE_ROOT` defaults to `$PWD/outputs/projects-work-on`.** Run the cloud
script's session verbs from the brain root or its state lands somewhere else
entirely.

## Step 0 — Recover the tracking context

Four sources, in this order. Stop at the first that answers.

1. **This session.** If a `brain-work-on*` skill ran in this conversation, the repo,
   workspace, team, project and current issue are already known. Use them.
2. **The workspace on disk.** The durable record, and the only source that survives
   a compaction or a fresh terminal. Look for **both** markers, at **any** depth:

   ```bash
   find outputs \( -name '.linear.json' -o -name '.jungle-vm.json' \) 2>/dev/null
   ```

   ⚠️ **Do not restrict the search to `outputs/projects-work-on/`.** Tracked
   sessions exist in other families too — `projects-setup/google-cloud-environments/`
   carries one today.

   ⚠️ Use `find`, not a `ls …/*/` glob. This shell is zsh, where an unmatched glob
   is a hard error raised *before* redirection, so `2>/dev/null` does not suppress
   it and a legitimately empty result reads as a broken lookup.

3. **Live cloud VMs**, when nothing on disk matches but the work is clearly remote:

   ```bash
   jungle_up_gcp.sh session list
   ```

   A running VM whose workspace dir holds no `.linear.json` is an **untracked
   session** — go to Step 1b, which opens its first issue.

4. **Nothing.** No session was ever set up. Say so and route to `brain-work-on` (or
   `brain-work-on-google-cloud` for a VM) — the tracking target is derived from the
   repo's owning team, and that derivation is those skills' job, not this one's.

Read every marker file in the chosen workspace, whole. They are complementary:

- **`.linear.json`** — team, project, current issue, log thread, plan file. Real
  files in this brain also carry `branch`, `commit`, `pr`, `workspace`.
- **`.jungle-vm.json`** — `vm`, `zone`, `project` (a **GCP** project, never the
  Linear one), `ip`, `image`, `repo`, `session`, `branch`, `mount`. On a cloud
  session this is what names the repo, so it is how the owning team gets derived.

⚠️ **`project` means different things in the two files.** In `.jungle-vm.json` it is
the GCP project. The Linear project is `linearProject` in `.linear.json`. Reading
the wrong one puts the issue on a board that does not exist.

If several workspaces match, pick by the repo the conversation is working in. If two
are plausible, ask which session this belongs to — binding new work to the wrong
session's project is not visible afterwards.

## Step 1 — Confirm the project before writing anything

Propose in one line and stop. The context already names the project, so this is a
yes/no, not an interrogation:

> Next issue goes to **STM** → project *Cashew Cost Approval*, alongside `STM-412`.
> Confirm, name a different project, or say "no tracking".

Accept all three. **"No tracking" is first-class** — a quick fix or a read-only
detour should not litter the board.

### 1b — The session has no `.linear.json` yet

A session created without tracking (common for a cloud VM spun up to try something)
has no project to confirm. Derive the team rather than asking cold:

1. Take `repo` from `.jungle-vm.json` — **not the directory name**, which can be a
   preset rather than a repo. Fall back to the directory only when no
   `.jungle-vm.json` exists.
2. Resolve it to IDP service dirs — repo name ≠ service dir, and a repo commonly
   maps to two prefixed services:

   ```bash
   ls -d src/idp/*<repo>* 2>/dev/null       # cashew -> admin-cashew AND api-cashew
   grep -iE "^\|\s*Owning team\s*\|" src/idp/<service>/service.md
   ```

   Owners agree → use it. Owners disagree → ask which surface. No hits → check
   `sources.idp.absent_services` in config before concluding it is not a service.
3. Map that owner to a Linear key through `brain.config.yml`, matching
   `teams[].idp_owner` and taking that entry's `linear_key`. If it has none, use
   `linear.fallback_team`. If that is unset, **ask — never invent a team.**

⚠️ **Never infer a Linear key from the team name.** `saitama` → `STM`, `saian` →
`AI`, `content-seo` → `CNT`. A name-shaped guess resolves to no team, and
`list_projects` answers a wrong-but-plausible key with an **empty list, not an
error**. A config still carrying the old `linear_teams:` field has not been
migrated — say so rather than reading names as keys.

Then propose the project as in Step 1.

### Listing projects

If the user names a different project, list the team's active projects with the
**MCP** `list_projects` (`team: "<KEY>"`, `state: "started"`).

⚠️ `list_projects` caps `limit` at **50** and truncates silently — follow `cursor`
while `hasNextPage` is true before concluding a project does not exist.

⚠️ **Do not reach for `wr-linear projects list` here.** Its plain `--team` call
works but is capped at the default 50, and *every* flag that would take you past
that — `--all`, `--limit 100` — returns **0 rows, exit 0**. An empty board and a
broken flag look identical. Only the MCP exposes a cursor. This is specific to
projects: `wr-linear issues list --project "<name>" --all` paginates correctly and
is the right tool in Step 2.

If the user names a project on a **different team**, take the team from the project
rather than reusing the pointer's `team` — a project can span teams, and writing
the issue to the wrong one puts it on a board nobody is looking at.

## Step 2 — New issue, or sub-issue of the current one?

The user asked for a new issue, so default to one. But check the discriminator
first, because getting this backwards is the most common way this skill makes a
board worse:

| The work is… | Open |
|---|---|
| a distinct goal the current issue's title does not describe | a **new issue** in the project |
| another phase of the goal the current issue already states | a **sub-issue** (`parentId` = current issue) |
| one more turn of conversation on work already in flight | **nothing** — a reply in the log thread (Step 6) |

A session is dozens of conversational turns. Issue-per-request makes the board
untriageable and distorts every count that reads it, so the bar for a new issue is
a **new goal**, not a new instruction.

### Duplicate guard

Before creating, look for an open issue in the project that already covers this:

```bash
wr-linear issues list --project "<project name>" --all
```

`--all` auto-paginates correctly for issues (359 rows on Bugs Triage, where the MCP
caps at 250 silently), so this is the cheap, complete read. If a near-identical open
issue exists, say so and ask whether to reattach to it instead of opening a second.

## Step 3 — Create the issue

Resolve the tool by suffix at run time. The Linear MCP is a remotely-managed
connector with an **opaque, unstable server id**:

```
ToolSearch  query: "+save_issue linear"      → mcp__<id>__save_issue
ToolSearch  query: "+save_comment linear"    → mcp__<id>__save_comment
ToolSearch  query: "+list_projects linear"   → mcp__<id>__list_projects
```

⚠️ **Never write a literal `mcp__<uuid>__*` name into a file or reuse one from
earlier in the conversation.** This is the observed failure mode, not a
hypothetical: two sibling skills in this repo still call bare `list_issues` /
`update_issue` from when the Linear MCP was ambient, and both of their write steps
are dead as a result.

Call `save_issue` with `title`, `team`, `project`, and a `description` carrying the
goal, the plan file path if one exists, and the current commit sha — so the issue
says what it was projected from.

**On a cloud session, record where the code actually is.** Put `vm`, `zone`, `image`
and `branch` from `.jungle-vm.json` in the description. Without them the issue
describes work nobody else can find: the branch exists only on that VM until it is
pushed. **Leave `ip` out** — `session refresh-ip` changes it whenever the operator's
network does, so a recorded address goes stale silently.

Constraints that hold on every team:

- **Leave `estimate` and `cycle` unset.** That is what keeps this work off the
  owning team's burndown while still showing on their board — correct, because it
  is their codebase but not their sprint commitment.
- **Never create a label.** Labels are per-team board configuration and
  heterogeneous across teams. Use one only if the user names one that already
  exists there.
- **No `Idea:` / `Task:` title prefix.** Those are other skills' conventions and
  they make this work sort into the wrong bucket.

Relate the new issue to the previous one when they share a thread of work — a
Linear relation, not a `parentId`. Siblings under a project stay independently
triageable. A `parentId` would quietly make the old issue a container it was never
scoped to be.

## Step 4 — Sub-issues, only where there are phases

If the work has two or more distinct phases, create one sub-issue per phase with
`parentId` set to the new issue. If it is a single change, the issue alone is the
right granularity — empty sub-issues are noise on a board.

When the scope is not clear enough to name the phases, that is a signal to run
`superpowers:brainstorming` and then `superpowers:writing-plans` first, and project
the resulting plan. Do not invent phases to fill the table.

**The plan file stays authoritative. Linear is a projection of it.** Sync one
direction only: plan → Linear. Reading state back out of Linear and into the plan
gives two sources of truth, and they diverge on the first update that lands in only
one of them.

## Step 5 — Update `.linear.json` by merging, never rewriting

Write the file the moment the issue exists, before any sub-issue, so an interrupted
run is resumable. It goes in the **session workspace**, beside `.jungle-vm.json`
when there is one.

```json
{
  "repo": "api-partner",
  "scope": "api-partner",
  "session": "agenttest",
  "team": "STM",
  "linearProject": "Cashew Cost Approval",
  "issue": "STM-418",
  "issueUrl": "https://linear.app/weroad/issue/STM-418/...",
  "planFile": "outputs/projects-work-on/api-partner/agenttest/superpowers-artifacts/plans/2026-08-29-agenttest.md",
  "logThreadId": "<comment id on STM-418>",
  "issues": [
    {"issue": "STM-412", "url": "…", "title": "…", "opened": "2026-08-21", "logThreadId": "…"},
    {"issue": "STM-418", "url": "…", "title": "…", "opened": "2026-08-29", "logThreadId": "…"}
  ]
}
```

- `issue` / `issueUrl` / `logThreadId` always describe the **current** issue.
  `brain-work-on` reattaches by reading `issue`, so pointing it at the newest is
  what makes a later re-run continue this work rather than the old work.
- `issues[]` is append-only history, newest last. On a file that has no `issues[]`
  yet, seed it from the flat fields **before** appending, or the previous issue is
  lost from the record.
- ⚠️ **Move `logThreadId` with `issue`.** Leaving the old thread id in place is
  silent and costly: every later request in this session gets logged onto the
  previous issue, so the new one looks abandoned and the old one looks endless.
- ⚠️ **Merge into the existing JSON — never rewrite it from the template above.**
  Real pointer files carry fields this skill does not know about (`branch`,
  `commit`, `pr`, `workspace`), and dropping them breaks whatever wrote them.
- `scope` is the workspace's first path segment — the repo or preset the session
  sits under. Record it when it differs from `repo`, so the workspace is findable
  from the pointer alone.
- ⚠️ **Never write into `.jungle-vm.json`.** The cloud script owns it and rewrites
  it wholesale on `session create` and `refresh-ip`. Anything added there is lost
  without warning. Tracking state belongs in `.linear.json`.

One workspace carries one current issue. A repo carries several concurrently-tracked
sessions (`super/` holds both `gmeet-to-md` and `super/`), so the pointer belongs to
the **session** dir, never a shared parent.

If the new work is genuinely a different **work stream** rather than the next step of
this one, give it its own session workspace, with its own `.linear.json` — and say
so, since that is a directory the user will look for later. Same stream, new issue →
same workspace, merged pointer.

## Step 6 — Keep the work tracked as it runs

This is the standing behaviour for the rest of the session, not a one-time step.

| Event | Linear write |
|---|---|
| the user makes another request | a **reply in the log thread** on the current issue (`save_comment`, `parentId` = `logThreadId`) |
| a phase completes | move that sub-issue's `state` forward |
| all phases complete | move the issue's `state` forward, and say so in the thread |
| the goal changes shape | back to Step 1 — a new goal is a new issue |

Create the log thread with a root comment on the new issue as soon as it exists, and
store its id as `logThreadId`. One thread per issue: the thread is the log, issues
are the structure.

⚠️ **On a cloud session, do not move an issue to a done state while its branch is
unpushed.** The code exists only on that VM. The cloud script guards the same
boundary — `session rm` refuses to delete a VM whose branch has no `origin/` counterpart
— and an issue marked done invites exactly that deletion. Check first:

```bash
jungle_up_gcp.sh session list          # is the VM still there?
```

Then confirm the branch reached `origin` before closing anything.

⚠️ **A cloud agent's progress does not reach Linear by itself.** It runs detached
under tmux on the VM, with no brain and no pointer file. Read what it did with
`session agent log <session>` and write the updates from the laptop. Silence in the
log thread means nobody wrote them, not that nothing happened.

Use the `patch` array for later description edits rather than rewriting the whole
description. Anchors must match exactly once and the whole patch aborts if one
fails, so it either applies cleanly or changes nothing — which is what you want on a
record other people are reading.

Progress writes are the one exception to "only write when the user asks". Everything
else on the board should be traceable to a request.

## Why this shape

The expensive failure here is not a missing issue — it is a board that stops
describing reality. That happens two ways, and they pull in opposite directions:
open an issue per request and the board fills with fragments nobody can triage.
Open none and a week of work sits inside one stale title while the team plans
around a picture that is a week old.

So the bar is a **new goal**, the log thread absorbs everything below that bar, and
the pointer file carries the history so a session picked up cold — after a
compaction, on another day, from another terminal, or from a VM that has been
running unattended — can tell which issue it is actually continuing.

The Linear conventions themselves are **shared, and now written in three places**:
here, in `brain-work-on` Step 9, and in `brain-work-on-google-cloud`'s "Linear
tracking". A change to any of them has to land in all three.

## Common mistakes

| Mistake | Why it breaks |
|---|---|
| Asking "which project?" cold | `.linear.json` names it. Propose; confirm. |
| Looking only at one depth | A cloud session predating 2026-08-29 is flat, at `<session>/`. |
| Assuming the first segment is a repo | It can be a jungle preset — `partner`, `my`. Read `repo` from `.jungle-vm.json`. |
| Searching only `outputs/projects-work-on/` | Tracked sessions live in other families too — `projects-setup/` has one. |
| Treating a missing `.linear.json` as "no session" | A cloud VM with only `.jungle-vm.json` is a real, untracked session. Open its first issue. |
| Reading `project` from `.jungle-vm.json` as the Linear project | That is the GCP project. The Linear one is `linearProject`. |
| Writing tracking state into `.jungle-vm.json` | The cloud script rewrites it wholesale on `create` and `refresh-ip`. |
| Recording the VM `ip` on the issue | `refresh-ip` changes it whenever the network does. Record `vm`, `zone`, `image`, `branch`. |
| Closing an issue whose branch is unpushed | On a cloud session the code exists only on the VM, and done invites `session rm`. |
| Assuming the VM agent updated Linear | It runs detached with no brain. Read `session agent log` and write from the laptop. |
| Rewriting `.linear.json` from the template | Real files carry `branch`, `commit`, `pr`, `workspace`. Merge. |
| Leaving `logThreadId` pointing at the old issue | Every later request logs onto the previous issue, silently. |
| Overwriting `issue` without seeding `issues[]` | The previous issue vanishes from the record. |
| A new issue for every request | Untriageable board, distorted counts. That is what the log thread is for. |
| `parentId` = the previous issue | Makes a sibling goal into a child of a scope that never covered it. |
| Inventing phases to fill sub-issues | Empty sub-issues are noise. No clear phases → brainstorm and plan first. |
| Hardcoding `mcp__<uuid>__save_issue` | The connector id is unstable. Resolve by suffix via ToolSearch. |
| `wr-linear projects list --all` / `--limit 100` | Returns 0 rows, exit 0. Only the MCP can page projects. |
| Trusting the first page of `list_projects` | Caps at 50 and truncates silently. Follow `cursor`. |
| Guessing a Linear key from a team name | `saitama`→`STM`, `saian`→`AI`. Read `teams[].linear_key`; a wrong key returns an empty list, not an error. |
| Setting `estimate` or `cycle` | Pulls the session into the owning team's burndown. |
| Creating a label | Labels are per-team board config. Only use one that exists. |
| Reusing the pointer's `team` for a project on another team | Writes the issue to a board nobody watches. |
| Reading state back from Linear into the plan | Two sources of truth diverge. Plan → Linear, one direction. |
| Naming a new session doc `README.md` | gbrain's `SYNC_SKIP_FILES` drops that basename silently, exit 0 — the doc is invisible to every search. |
