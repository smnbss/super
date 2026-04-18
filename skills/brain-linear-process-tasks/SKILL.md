---
name: brain-linear-process-tasks
description: >
  Pick the next task issue from a Linear project, gather context, implement it,
  and mark it done. Use when the user says "process task", "implement next task",
  "work on next issue", or passes a Linear project URL and asks to implement tasks.
---

# Linear — Process Tasks

Pick the first eligible task issue from a Linear project, gather full context, ask
clarifying questions, implement the change, run tests, commit, and mark done.

## Input

The Linear org slug is read from `$BRAIN_CONFIG` (default `~/.super/brain.config.yml`) → `linear.org`. The user can provide a Linear project URL, e.g.:
```
https://linear.app/<org>/project/super-edc40903e247/issues
```

Optionally, the user can also provide a specific issue URL to work on:
```
https://linear.app/<org>/issue/SIM-7
```

**If no project URL is provided**, read the `LINEAR_LOOP` env var from `.env.local` in the
project root. It contains a semicolon-separated list of Linear project URLs:
```bash
# Example: LINEAR_LOOP=https://linear.app/<org>/project/super-xxx/overview;https://linear.app/<org>/project/others-yyy/issues;
```

Process **each project** in the list sequentially — find the first eligible task in
**In Progress** or **In Review** for each project and implement it before moving to the next.

If neither a URL nor `LINEAR_LOOP` is available, **stop immediately** and ask:
> "I need a Linear project URL to pick tasks from. Example: `https://linear.app/<org>/project/<slug>/issues`"

## Loop Behavior

When this skill runs repeatedly — whether via `/loop`, a scheduled trigger,
`/ralphloop`, or simply by invoking the skill again — each iteration should:

1. **Ingest new comments:** Fetch all comments on the issue. Find human comments
   posted after the last agent comment (i.e., not yet acknowledged). Incorporate
   their content as additional context — the user may have answered a question,
   refined requirements, or provided implementation guidance.
2. **Acknowledge incorporated comments:** After reading a human comment, post a
   brief acknowledgment so it is not re-processed on the next iteration:
   ```
   Incorporated your feedback — resuming implementation.
   ---
   🤖 **Agent** | ack | <ISO-timestamp>
   ```
3. **Question-answer loop:** If the agent posted a question and received an answer,
   incorporate the answer and resume implementation. If the answer raises new
   questions, post follow-ups and wait for the next iteration. This cycle repeats
   until the agent has no further open questions.
4. **Termination:** The task is fully processed when:
   - Implementation is complete, committed, and the issue is marked Done, AND
     no unprocessed human comments remain, OR
   - The agent has posted a question and is waiting for a reply (skip to next
     project in the loop).

## Step 1 — Parse and fetch

Extract the project slug from the URL (segment after `/project/`, before next `/`).

If a specific issue URL was provided, extract the issue identifier (e.g., `SIM-7`).

**Important:** The Linear MCP `list_issues` tool does NOT resolve project slugs
reliably. Always fetch the project first, then use the returned project **name**
for `list_issues`.

1. `get_project` with `query: "<slug>"` — note the returned `name` and `id`.
2. If a specific issue was given: `get_issue` with `query: "<identifier>"`
3. If no specific issue:
   - `list_issues` with `project: "<project name from step 1>"`, `state: "In Progress"`, `limit: 100`
   - `list_issues` with `project: "<project name from step 1>"`, `state: "In Review"`, `limit: 100`
   - Merge all result sets into a single list.
   
   **Excluded statuses:** Do NOT fetch or process issues with status "Done", "Cancelled", or "Duplicate". These are considered complete or irrelevant and should be ignored entirely.

## Step 2 — List all issues and find the target

**If a specific issue was provided:** Use that issue directly (skip the table).

Otherwise, print a diagnostic table of **all** issues in the project so the user
can see what exists and which one will be picked:

```
### <project name> — Issue Overview

| ID | Title | Status | Eligible |
|----|-------|--------|----------|
```

An issue is **eligible** if:
- It is a `Task:` issue in **In Progress** or **In Review** status.

**Excluded from consideration:**
- Issues with status **Done**, **Cancelled**, or **Duplicate** — skip these entirely
- Issues whose title does NOT start with `"Task:"` — those are ideas or other issue types handled by different skills

For each issue, the `Eligible` column should show:
- **YES — picked** for the eligible issue that wins the sort below
- `Yes — but <other ID> wins` for other eligible issues
- `No — excluded status (Done/Cancelled/Duplicate)` for issues in excluded statuses
- `No — not eligible status` for `Task:` issues in other statuses (e.g., Todo, Backlog)
- `No — not "Task:"` for issues whose title doesn't start with `Task:`

### Sorting and picking

Sort **all eligible issues** by **priority descending** first (Urgent > High > Medium > Low > None),
then by **`createdAt` ascending** (oldest first) to break ties within the same
priority.

Pick the **first** issue from this sorted list. Priority always wins — an Urgent
In Progress issue is picked before a Low-priority In Progress issue.

Sort the diagnostic table the same way: priority descending, then `createdAt`
ascending. Add a `Priority` column to make the ordering visible:

```
| ID | Title | Status | Priority | Eligible |
|----|-------|--------|----------|----------|
```

**If no eligible issue is found:**
Stop and report:
> "No eligible task issues for project <name> — nothing In Progress/In Review."

If there are task issues in other statuses (Todo, Backlog), mention
them so the user knows what exists. Note any Done/Cancelled/Duplicate
issues as "excluded from consideration."

## Step 3 — Check for pending question (resume check)

Before doing any work, check the issue description for the checkpoint marker:

```
<!-- agent-state: awaiting-response | comment-id:<id> | since:<timestamp> -->
```

**If the marker exists:**

1. Extract `since` timestamp and `comment-id`.
2. Fetch all comments using `list_comments` with `issueId: "<ID>"`.
3. Sort by `createdAt` ascending. Find all comments after the `since` timestamp.
4. Look for the first comment that does NOT contain `🤖 **Agent**` in its body.
5. **If a human reply is found:**
   - Read the reply content — this answers the agent's earlier question.
   - Remove the `<!-- agent-state: ... -->` marker from the issue description
     (update via `save_issue`).
   - Post an acknowledgment comment:
     ```
     Received your response — resuming work.
     ---
     🤖 **Agent** | status | <ISO-timestamp>
     ```
   - Continue to Step 4 with the reply as additional context.
6. **If no human reply is found:**
   - Report: "Still waiting for your reply on the Linear comment. Skipping this issue."
   - Do NOT remove the marker. Move to the next project in the loop.

**If the marker does NOT exist:** Continue to the general comment check below.

See `skills/references/linear-comment-protocol.md` for the full protocol spec.

### General comment ingestion (every loop iteration)

Regardless of whether the agent-state marker exists, check for unprocessed
human comments on every iteration:

1. Fetch all comments using `list_comments` with `issueId: "<ID>"`.
2. Sort by `createdAt` ascending.
3. Find all human comments (those NOT containing `🤖 **Agent**`) that appear
   AFTER the last agent comment. If no agent comments exist, all human comments
   since issue creation are candidates.
4. These are unprocessed feedback comments — incorporate their content as
   additional context for the implementation.
5. For each incorporated comment, post an acknowledgment:
   ```
   Incorporated your feedback — resuming implementation.
   ---
   🤖 **Agent** | ack | <ISO-timestamp>
   ```
6. Pass the incorporated feedback as additional context to Step 4 and
   subsequent steps.

## Step 4 — Read the full context

Fetch the complete issue using `get_issue` with the issue identifier.

Also read:
- The **project description** (from Step 1) — this provides the broader project context.
- Any **comments** on the issue using `list_comments` with `issueId: "<ID>"`.
- Any **sub-issues** if referenced.

Gather all of this into your working context.

## Step 5 — Ask before proceeding

**Before writing any code**, present the user with:

1. **Issue summary:** ID, title, description (condensed).
2. **Your understanding:** What needs to be done, in your own words.
3. **Approach:** How you plan to implement it (files to change, strategy).
4. **Questions:** Anything unclear or ambiguous — ask now.

If running interactively (user is present), wait for confirmation.

If running autonomously (e.g. via `/loop`, a scheduled trigger, or repeated
invocations) and the requirements
are unclear, **post a question on Linear instead of stopping**:

1. Post a comment with the question + agent signature:
   ```
   <your questions here>
   ---
   🤖 **Agent** | question | <ISO-timestamp>
   ```
2. Append the checkpoint marker to the issue description.
3. Report: "Posted a question on <ID>: <title>. Waiting for your reply in Linear."
4. Move to the next project in the loop.

On the next loop iteration, Step 3 (resume check) will detect the marker, find
the reply, incorporate it, and the agent re-enters Step 5 with the answer as
context. This question-answer cycle repeats until the agent has no further open
questions — only then does it proceed to implementation.

If requirements are clear (including when a previous question was just answered
and the answer resolves all ambiguity), proceed without asking.

## Step 6 — Move to In Review (if needed)

If the issue is currently in **In Progress**, use the `save_issue` Linear MCP tool to transition it:
- `id`: the issue identifier (e.g., "SIM-7")
- `state`: "In Review"

Report: `"Moved <ID>: <title> to In Review — starting implementation"`

If the issue is already in **In Review**, skip the transition and report:
`"<ID>: <title> is already In Review — starting implementation"`

## Step 7 — Implement

Implement the changes following best practices:

1. **Read before writing** — understand the existing code before modifying it.
2. **Make focused changes** — only change what the issue requires.
3. **Follow existing patterns** — match the codebase's conventions.

## Step 7a — Verify & QA

**Do not commit until this step passes.** This is a hard gate.

1. **Run the test suite** — execute the project's tests (`npm test`, `pytest`,
   `make test`, or whatever the project uses). All tests must pass.
2. **Run linting / type checks** — if the project has a linter or type checker
   (`npm run lint`, `mypy`, `tsc --noEmit`, etc.), run it. Zero new errors.
3. **Smoke-test the change** — verify the implementation actually does what the
   issue asked for. If it's a CLI change, run the command. If it's an API change,
   hit the endpoint. If it's a UI change and a dev server is available, check it
   in a browser.
4. **Review your own diff** — run `git diff` and read every changed line. Look for:
   - Accidental debug code left in
   - Unrelated changes that snuck in
   - Missing edge cases
5. **Fix any failures** — if tests, lint, or the smoke test fail, fix the issues
   and re-run this step. Do not proceed until everything is clean.

Only after all checks pass, proceed to Step 8 (Commit).

## Step 8 — Commit

Once tests pass, commit the changes to git:

1. Stage only the relevant files (not unrelated changes).
2. Write a commit message referencing the issue:
   ```
   feat: <short description> [<ID>]
   ```
3. Do NOT push unless the user explicitly asks.

## Step 9 — Update the project

Use the `save_status_update` Linear MCP tool to publish a project update:
- `type`: `"project"`
- `project`: the project ID or slug from Step 1
- `health`: choose based on the implementation:
  - `onTrack` if the task was completed cleanly
  - `atRisk` if the task was completed but with caveats or partial implementation
  - `offTrack` if the task could not be completed
- `body`: a concise Markdown summary including:
  - The issue ID and title
  - What was implemented
  - Any caveats or follow-ups needed

## Step 10 — Mark as Done

Use `save_issue` to transition the issue:
- `id`: the issue identifier
- `state`: "Done"

Add a comment on the issue summarizing what was done:
> "Implemented and committed. <one-line summary of what changed>.
> Commit: `<short hash>` — tests passing."

## Step 11 — Report

Print:
- Issue ID, title, and URL
- What was implemented (2-3 sentences)
- Commit hash
- Test results (pass/fail)
- Confirmation that the issue was marked Done
- Confirmation that a project status update was posted
- Any follow-ups or caveats
