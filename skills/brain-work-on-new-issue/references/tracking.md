# The tracker contract

**This file holds the contract. A `SKILL.md` holds a flow.** Three skills project a session onto
a tracker: `brain-work-on`, `brain-work-on-new-issue` and `brain-work-on-google-cloud`. The rules
below were written in all three and are now written here once.

Read this before you write to any tracker.

## The three tiers

| Tier | Linear | GitHub |
|---|---|---|
| Session | one issue, `save_issue` | one issue, `gh issue create` |
| Phase | sub-issue, `parentId` | sub-issue, `addSubIssue` GraphQL mutation |
| Request log | one comment thread, replies by `parentId` | one comment, PATCHed in place |

### Six rules that hold on both trackers

1. One workspace holds one issue.
2. A new goal gets a new issue and a new session directory.
3. A sub-issue is a phase of the current goal. It stays in the same directory.
4. One more turn of conversation is a log entry, never an issue.
5. Never create a label.
6. The plan file stays authoritative. The tracker is a projection of it, in one direction.

⚠️ **Never read state back out of the tracker and into the plan.** Two sources of truth diverge
on the first update that lands in only one of them.

### Three Linear rules that GitHub SKIPS, and does not adapt

1. **The owning-team derivation.** No `src/idp/*<repo>*` glob. No `service.md` read. No
   `brain.config.yml` `teams[].linear_key` lookup. No `linear.fallback_team`.
2. **The project confirmation.** GitHub has no Linear project. Its nearest analogue is a
   milestone. Confirm the repo instead.
3. **`estimate` and `cycle`.** GitHub has neither.

## Resolving the tracker

Four rules, in this order. Stop at the first that answers.

1. The `.tracking.json` in the session workspace. Its `tracker` field wins over any repo marker.
   A tracked session never changes tracker.
2. The marker `<!-- tracker: github -->` or `<!-- tracker: linear -->`, in the matched repo's
   `AGENTS.md`, then its `CLAUDE.md`.
3. The prose fallback `GitHub Issues is the tracker`, in the same two files.
4. Nothing found. Use Linear, by the existing derivation, unchanged.

```bash
repo_dir="github/<org>/<repo>"
tracker=""
for f in "$repo_dir/AGENTS.md" "$repo_dir/CLAUDE.md"; do
  [ -f "$f" ] || continue
  if grep -qiE '^<!--[[:space:]]*tracker:[[:space:]]*github[[:space:]]*-->' "$f"; then
    tracker=github; break
  fi
  if grep -qiE '^<!--[[:space:]]*tracker:[[:space:]]*linear[[:space:]]*-->' "$f"; then
    tracker=linear; break
  fi
  if grep -qiF 'GitHub Issues is the tracker' "$f"; then tracker=github; break; fi
done
```

⚠️ **A missing marker is not evidence the repo uses Linear.** It is the absence of a
declaration. Rule 4 catches it. **Say which rule answered.**

⚠️ **The brain's own root `AGENTS.md` is not a repo marker.** Read the marker only from
`github/<org>/<repo>/`. Never walk up from the current directory.

⚠️ **A repo with no `AGENTS.md` and no `CLAUDE.md` answers empty.** That is rule 4, not an error.

## The `.tracking.json` schema

One pointer file per session directory, on both trackers.

### Common fields

| Field | Meaning |
|---|---|
| `tracker` | `"linear"` or `"github"`. **First key in the file.** |
| `repo` | the bare repo name, for example `tastetheworld` |
| `scope` | the workspace's first path segment — a repo or a jungle preset |
| `session` | the session directory name |
| `issue` | the human reference. **Always a string.** |
| `issueUrl` | the full URL |
| `workspace` | the workspace path from the brain root |
| `planFile` | path to the plan, or `null` |
| `previousSession` | the workspace this one split from, when it split from one |

### Linear-only fields

| Field | Meaning |
|---|---|
| `team` | the Linear team key, for example `SIM` |
| `linearProject` | the Linear project name |
| `logThreadId` | the root comment id of the log thread |

### GitHub-only fields

| Field | Meaning |
|---|---|
| `githubRepo` | `"<owner>/<repo>"`, for example `smnbss/tastetheworld` |
| `issueNodeId` | the GraphQL node id. `addSubIssue` needs it. |
| `logCommentId` | the REST comment id of the session log comment |

### Example

```json
{
  "tracker": "github",
  "repo": "tastetheworld",
  "githubRepo": "smnbss/tastetheworld",
  "scope": "tastetheworld",
  "session": "34-restaurant-photos",
  "issue": "34",
  "issueUrl": "https://github.com/smnbss/tastetheworld/issues/34",
  "issueNodeId": "I_kwDOPiZHI88AAAABSHB5PA",
  "logCommentId": null,
  "planFile": null,
  "previousSession": "outputs/projects-work-on/tastetheworld/open-issue-sweep",
  "workspace": "outputs/projects-work-on/tastetheworld/34-restaurant-photos"
}
```

⚠️ **`issue` is a STRING on both trackers** — `"SIM-64"` and `"34"`. A JSON type that changes by
tracker reads fine and breaks a comparison silently.

⚠️ **Merge into an existing pointer. Never rewrite it from the template.** Real files carry
`branch`, `commit`, `pr` and `note`. Dropping one breaks whatever wrote it.

⚠️ **A legacy `issues[]` array may be present. Read it. Never extend it.** A workspace that needs
a second issue needs a second directory.

⚠️ **Never write tracking state into `.jungle-vm.json`.** The cloud script rewrites that file
wholesale on `session create` and on `refresh-ip`.

### The pre-rename pointer

⚠️ **A `.linear.json` or a `.github-issue.json` is a PRE-RENAME pointer.** Read it. Rewrite it as
`.tracking.json` in the same directory. Say that you did.

⚠️ **Never treat a pre-rename pointer as an untracked session.** That opens a duplicate issue.

The fallback exists for a clone or a branch that predates the rename. It expires by use, not by
date.

## Session directory naming

| Tracker | Form | Example |
|---|---|---|
| Linear | `<issue-key>-<slug>`, lowercase | `sim-64-secret-manager-auth` |
| GitHub | `<issue-number>-<slug>` | `34-restaurant-photos` |

GitHub has no project key, so the number stands alone. Keep the slug to 3 or 4 words, kebab-case.
A directory created before an issue exists keeps its work-stream name.

⚠️ **Never name a session's primary document `README.md`.** gbrain's `SYNC_SKIP_FILES` drops that
basename silently, exit 0, so the document is invisible to every search. The same applies to
`index.md`, `log.md` and `schema.md`.

## Per-tracker verbs

### Linear

The Linear MCP is a remotely-managed connector with an opaque, unstable server id. Resolve each
tool by suffix at run time.

```
ToolSearch  query: "+save_issue linear"      -> mcp__<id>__save_issue
ToolSearch  query: "+save_comment linear"    -> mcp__<id>__save_comment
ToolSearch  query: "+list_projects linear"   -> mcp__<id>__list_projects
```

⚠️ **Never write a literal `mcp__<uuid>__*` name into a file.** The connector id is unstable.

⚠️ **`list_projects` caps `limit` at 50 and truncates silently.** Follow `cursor` while
`hasNextPage` is true.

⚠️ **Do not use `wr-linear projects list` to page.** Its plain `--team` call works but stops at
50. Every flag that would take you past 50 returns **0 rows, exit 0**. An empty board and a
broken flag look identical. This is specific to projects. `wr-linear issues list --project
"<name>" --all` paginates correctly.

### GitHub

```bash
# create the session issue. It prints the issue URL.
gh issue create --repo <owner>/<repo> --title "<title>" --body "<body>"

# read the node id once, and store it as issueNodeId
gh api repos/<owner>/<repo>/issues/<n> --jq '.node_id'

# attach a phase as a sub-issue, using the child's URL. No node-id lookup needed.
gh api graphql -f query='
  mutation($parent:ID!, $childUrl:String!) {
    addSubIssue(input:{issueId:$parent, subIssueUrl:$childUrl}) { issue { number } }
  }' -f parent="<issueNodeId>" -f childUrl="<child issue url>"

# duplicate guard, before you create anything
gh issue list --repo <owner>/<repo> --state open --limit 100
gh issue list --repo <owner>/<repo> --state all --search "<term>"
```

Three constraints on a GitHub issue:

1. **The title states the observed problem, not the proposed fix.** *"Favorites tab shows the
   Scan screen"* is a title. *"Add a render branch"* is not.
2. **Never create a label.** Apply an existing one when it fits. Apply none when none fits.
3. **Never put a credential in an issue body.** An issue body reaches every collaborator and is
   copied into notifications.

## The log tier

One log per issue. The log is the thread. Issues are the structure.

⚠️ **One issue per request is wrong.** A session is dozens of conversational turns. Issue per
request makes a board untriageable and distorts every count that reads it.

### Linear

Post a root comment when the issue exists. Store its id as `logThreadId`. Reply to it with
`save_comment` and `parentId` for each later request.

### GitHub

GitHub issue comments are flat. There is no `parentId` and no thread. Post **one** comment when
the issue exists.

````markdown
## Session log

Workspace: `outputs/projects-work-on/<scope>/<session>/`

- 2026-09-19 — <the first request, one line>
````

Store its REST id as `logCommentId`. Append each later request to the same comment.

```bash
gh api repos/<owner>/<repo>/issues/comments/<logCommentId> --jq '.body' > /tmp/log.md
# append one dated line to /tmp/log.md, then write it back
gh api -X PATCH repos/<owner>/<repo>/issues/comments/<logCommentId> -F body=@/tmp/log.md
```

⚠️ **`logCommentId` is the REST comment id, a number. It is NOT the GraphQL node id.** The two
look different and both are called the comment's id. A PATCH with the node id returns **404**,
not a type error. `gh issue comment` prints only the comment URL, whose last path segment is
`issuecomment-<id>`. Read the id from there, or read it directly:

```bash
gh api repos/<owner>/<repo>/issues/<n>/comments --jq '.[-1].id'
```

⚠️ **A read-modify-write loses a concurrent append.** Two agents on one issue is not supported.

⚠️ **Never write a verbatim transcript into the log.** Write one line per request, in the user's
words, with no pasted output. A verbatim log is the likeliest way a credential reaches an issue.
