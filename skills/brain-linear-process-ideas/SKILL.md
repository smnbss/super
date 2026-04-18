---
name: brain-linear-process-ideas
description: >
  Pick the next "Idea:" issue from a Linear project, move it to In Progress, and
  iteratively improve it across 3 passes. Use when the user says "process idea",
  "work on next idea", "improve ideas", or passes a Linear project URL and asks
  to process or refine ideas.
---

# Linear — Process Idea

Pick the first "Idea:" issue in Todo from a Linear project, move it to In Progress,
and iteratively refine it across 3 structured passes. Each pass deepens the analysis
and is tracked with a counter in the issue description.

## Input

The Linear org slug is read from `$BRAIN_CONFIG` (default `<project>/.super/brain.config.yml`) → `linear.org`. The user can provide a Linear project URL, e.g.:
```
https://linear.app/<org>/project/super-edc40903e247/issues
```

**If no URL is provided**, read the `LINEAR_LOOP` env var from `.env.local` in the
project root. It contains a semicolon-separated list of Linear project URLs:
```bash
# Example: LINEAR_LOOP=https://linear.app/<org>/project/super-xxx/overview;https://linear.app/<org>/project/others-yyy/issues;
```

Process **each project** in the list sequentially — find the first "Idea:" issue in
Todo for each project and process it before moving to the next.

If neither a URL nor `LINEAR_LOOP` is available, **stop immediately** and ask:
> "I need a Linear project URL to process ideas from. Example: `https://linear.app/<org>/project/<slug>/issues`"

## Loop Behavior

When this skill runs repeatedly — whether via `/loop`, a scheduled trigger,
`/ralphloop`, or simply by invoking the skill again — each iteration should:

1. **Ingest new comments:** Fetch all comments on the issue. Find human comments
   posted after the last agent comment (i.e., not yet acknowledged). Incorporate
   their content as additional context for the current or next pass.
2. **Acknowledge incorporated comments:** After reading a human comment, post a
   brief acknowledgment so it is not re-processed on the next iteration:
   ```
   Incorporated your feedback — continuing with pass N.
   ---
   🤖 **Agent** | ack | <ISO-timestamp>
   ```
3. **Resume from where you left off:** Use the pass counter
   (`<!-- idea-processing: pass N/3 -->`) to determine which pass to continue or
   start next.
4. **Question-answer loop:** If the agent posted a question and received an answer,
   incorporate the answer and resume. If the answer raises new questions, post
   follow-ups and wait for the next iteration. This cycle repeats until the agent
   has no further open questions for the current pass.
5. **Feedback pass on new comments:** Even after all 3 passes are complete, if
   new unprocessed human comments are found, the agent performs a **Feedback Pass**
   (Step 6b) to incorporate the feedback and update the issue. This repeats on
   every loop iteration as long as new comments keep arriving.
6. **Termination:** The issue is fully processed when all 3 passes are complete
   AND no `<!-- agent-state: awaiting-response -->` marker exists AND no
   unprocessed human comments remain. Before reporting "Already complete",
   ensure the issue status is "In Progress" (move it if it's still in Todo
   or another status). Then move to the next project.

## Step 1 — Parse and fetch

Extract the project slug from the URL (segment after `/project/`, before next `/`).

**Important:** The Linear MCP `list_issues` tool does NOT resolve project slugs
reliably. Always fetch the project first, then use the returned project **name**
for `list_issues`.

1. `get_project` with `query: "<slug>"` — note the returned `name` and `id`.
2. `list_issues` with `project: "<project name from step 1>"`, `state: "Todo"`, `limit: 100`
3. `list_issues` with `project: "<project name from step 1>"`, `state: "In Progress"`, `limit: 100`
   — includes ideas already being processed (may have new comments to handle).
4. `list_issues` with `project: "<project name from step 1>"`, `state: "Cancelled"`, `limit: 100`
5. `list_issues` with `project: "<project name from step 1>"`, `state: "Duplicate"`, `limit: 100`

Steps 4–5 are for display only — Cancelled and Duplicate issues appear in the
diagnostic table but are **never eligible** for processing.

## Step 2 — List all issues and find the target

First, print a diagnostic table of **all** issues in the project so the user can see
what exists and which one will be picked:

```
### <project name> — Issue Overview

| ID | Title | Status | Eligible |
|----|-------|--------|----------|
```

An issue is **eligible** if:
- It is an `Idea:` issue in **Todo** (new idea to process), OR
- It is an `Idea:` issue in **In Progress** with all 3 passes complete AND
  unprocessed human comments (feedback pass needed).

An issue is **never eligible** if its status is **Cancelled** or **Duplicate**.
Skip these entirely — do not process, do not check for comments, do not move.

For each issue, the `Eligible` column should show:
- **YES — picked** for the eligible issue that wins the sort below
- **YES — feedback** for eligible In Progress issues with new comments (if not the picked one)
- `Yes — but <other ID> wins` for other eligible issues
- `No — cancelled` for issues in Cancelled status
- `No — duplicate` for issues in Duplicate status
- `No — In Progress, no new comments` for In Progress `Idea:` issues with no unprocessed comments
- `No — not eligible status` for `Idea:` issues in other statuses
- `No — not "Idea:"` for issues whose title doesn't start with `Idea:`

### Sorting and picking

Sort **all eligible issues together** (both Todo and In Progress with feedback)
by **priority descending** first (Urgent > High > Medium > Low > None), then by
**`createdAt` ascending** (oldest first) to break ties within the same priority.

Pick the **first** issue from this sorted list. Priority always wins — a High-priority
In Progress issue with feedback is picked before a Low-priority Todo issue.

Sort the diagnostic table the same way: priority descending, then `createdAt`
ascending. Add a `Priority` column to make the ordering visible:

```
| ID | Title | Status | Priority | Eligible |
|----|-------|--------|----------|----------|
```

**If no eligible issue is found:**
Stop and report:
> "No eligible 'Idea:' issues for project <name> — nothing in Todo and no completed ideas with new feedback."

If there are "Idea:" issues in other statuses (Backlog), mention them
so the user knows what exists.

## Step 3 — Move to In Progress

Use the `save_issue` Linear MCP tool to transition the issue:
- `id`: the issue identifier (e.g., "SIM-3")
- `state`: "In Progress"

Report: `"Moved <ID>: <title> to In Progress"`

## Step 4 — Check for pending question (resume check)

Before doing any work on the issue, check its description for the checkpoint marker:

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
   - Continue to Step 5 with the reply as additional context.
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
   additional context for the current or next pass.
5. For each incorporated comment, post an acknowledgment:
   ```
   Incorporated your feedback — continuing work.
   ---
   🤖 **Agent** | ack | <ISO-timestamp>
   ```
6. Pass the incorporated feedback as additional context to Step 5 and
   subsequent passes.

**Early exit:** If no unprocessed comments are found AND all 3 passes are already
complete (check the pass counter for `pass 3/3`):

1. **Ensure status is "In Progress":** If the issue is still in "Todo" (or any
   non-"In Progress" status), move it to "In Progress" using `save_issue`. This
   catches ideas that were fully refined but whose status wasn't updated, or that
   were moved back to Todo after processing.
2. Report:
   > "All passes complete, no new comments. Nothing to do for <ID>."

Then move to the next project in the loop.

**Feedback trigger:** If unprocessed comments ARE found AND all 3 passes are
already complete, do NOT early-exit. Instead, acknowledge the comments (as above)
and proceed to **Step 6b — Feedback Pass** to incorporate the new input.

## Step 5 — Read the full context

Fetch the complete issue using `get_issue` with the issue identifier.

Also read:
- The **project description** (from Step 1) — this provides the broader project context.
- Any **comments** on the issue using `list_comments` with `issueId: "<ID>"`.

Gather all of this into your working context.

## Step 6 — Three improvement passes

Perform exactly 3 passes on the idea. After each pass, update the issue description
using `save_issue`. Each pass builds on the previous one.

### Pass counter

Maintain a progress tracker at the TOP of the issue description:

```markdown
<!-- idea-processing: pass N/3 | last-updated: YYYY-MM-DD HH:MM -->
```

If this marker already exists (from a previous run), read the current pass number
and continue from where it left off. If all 3 passes are already done, report that
and ask the user if they want to reset and do 3 more.

### Pass 1 — Research & Expand

**Goal:** Understand the idea deeply and expand it with research.

- What problem does this idea solve? Who benefits?
- What are the key assumptions? Are they valid?
- Research: use web search, DeepWiki, or brain knowledge (`qmd query`) to find
  relevant prior art, similar implementations, documentation, or competing approaches.
- Expand the description with findings: background, prior art, relevant links.
- List 3-5 concrete approaches or options to implement this idea.

**Update the issue description** with the expanded context. Preserve the original
idea text — add to it, don't replace it.

Format:
```markdown
<!-- idea-processing: pass 1/3 | last-updated: YYYY-MM-DD HH:MM -->

## Original Idea

<original description, preserved verbatim>

## Pass 1 — Research & Expansion

### Problem Statement
<crisp problem statement>

### Background & Prior Art
<research findings, links, similar approaches>

### Options
1. **<Option name>** — <description, pros, cons>
2. **<Option name>** — <description, pros, cons>
3. **<Option name>** — <description, pros, cons>
```

### Pass 2 — Evaluate & Recommend

**Goal:** Critically evaluate each option and recommend a path forward.

- For each option from Pass 1, assess:
  - **Feasibility:** How hard is it? What's the effort (T-shirt size)?
  - **Impact:** How much does it move the needle on the problem?
  - **Risk:** What could go wrong? Dependencies? Blockers?
  - **Alignment:** Does it fit the project goals (from project description)?
- Score each option on a simple matrix (feasibility x impact).
- Recommend a preferred option with clear reasoning.
- Identify what you'd need to validate before committing.

**Append** to the issue description:
```markdown
## Pass 2 — Evaluation & Recommendation

### Option Comparison

| Option | Feasibility | Impact | Risk | Score |
|--------|-------------|--------|------|-------|
| ...    | ...         | ...    | ...  | ...   |

### Recommendation
<which option and why>

### Open Questions / Validation Needed
- <question 1>
- <question 2>
```

Update the pass counter to `pass 2/3`.

### Pass 3 — Action Plan

**Goal:** Turn the recommendation into concrete next steps.

- Break the recommended option into actionable tasks (3-7 tasks).
- For each task: what needs to happen, rough effort, any dependencies.
- Identify the first concrete step someone could take TODAY.
- Flag any decisions that need human input before proceeding.
- Write a one-paragraph "elevator pitch" summary of the refined idea.

**Append** to the issue description:
```markdown
## Pass 3 — Action Plan

### Summary
<one paragraph elevator pitch of the refined idea>

### Tasks
- [ ] <task 1> — <effort estimate>
- [ ] <task 2> — <effort estimate>
- [ ] <task 3> — <effort estimate>

### First Step
<what to do right now>

### Decisions Needed
- <decision 1 — who needs to decide>
```

Update the pass counter to `pass 3/3`.

### Between passes — check for new comments

Before starting each subsequent pass (2 and 3), re-fetch comments to check if the
user has posted feedback since the previous pass completed:

1. Fetch all comments using `list_comments` with `issueId: "<ID>"`.
2. Find human comments posted after your last agent comment.
3. If found, incorporate the feedback into the upcoming pass. Post an acknowledgment:
   ```
   Incorporated your feedback — continuing with pass N.
   ---
   🤖 **Agent** | ack | <ISO-timestamp>
   ```
4. If the feedback changes direction or scope, adjust the remaining passes
   accordingly — the user's input takes priority over prior analysis.

### Pause for questions (any pass)

If during any pass the agent encounters ambiguity that would significantly affect
the output (e.g., unclear scope, conflicting requirements, missing domain context),
it SHOULD pause and ask via Linear:

1. Complete whatever partial analysis is possible.
2. Update the issue description with progress so far (including the pass counter).
3. Post a comment with the question + agent signature:
   ```
   <your questions here>
   ---
   🤖 **Agent** | question | <ISO-timestamp>
   ```
4. Append the checkpoint marker to the issue description.
5. Stop and report: "Posted a question on <ID>: <title>. Waiting for your reply in Linear."

On the next loop iteration, Step 4 (resume check) will detect the marker, find
the reply, incorporate it, and the agent continues the pass from where it left off.
This question-answer cycle repeats until the agent has no further open questions
for the current pass — only then does it proceed to the next pass.

## Step 6b — Feedback Pass (post-completion comments)

This step runs when all 3 passes are complete but new unprocessed human comments
have been found. It allows the idea to evolve based on ongoing feedback without
resetting the original 3-pass work.

### Tracking

Maintain a feedback counter alongside the pass counter:

```markdown
<!-- idea-processing: pass 3/3 | feedback N | last-updated: YYYY-MM-DD HH:MM -->
```

`N` starts at 1 and increments with each feedback pass. If no feedback passes
have occurred yet, there is no `feedback` field in the marker.

### What to do

1. Re-read the full issue description (all 3 passes) and the new comment(s).
2. Determine what the feedback changes:
   - **New information** — update the relevant pass section (research, evaluation,
     or action plan) with the new data.
   - **Challenge to a recommendation** — re-evaluate the affected option(s) and
     update Pass 2 and/or Pass 3 accordingly.
   - **New requirement or constraint** — update all affected sections.
   - **Approval or confirmation** — note the confirmation inline and update the
     action plan if it unblocks a step.
   - **Question from the user** — answer it in a comment (using the agent
     signature) and update the description if the answer affects the plan.
3. Append a summary of what changed at the bottom of the issue description:

```markdown
## Feedback Pass N — <YYYY-MM-DD>

**Triggered by:** comment from <user> at <timestamp>

### Changes Made
- <what was updated and why>

### Impact on Recommendation
<did the recommendation change? if so, what's the new recommendation and why>
```

4. Update the feedback counter: `<!-- idea-processing: pass 3/3 | feedback N | last-updated: YYYY-MM-DD HH:MM -->`
5. Post a comment summarizing the update:
   ```
   Incorporated your feedback in Feedback Pass N. Updated: <brief list of sections changed>.
   ---
   🤖 **Agent** | feedback-pass | <ISO-timestamp>
   ```
6. If the feedback raises questions the agent cannot resolve, follow the same
   question protocol as regular passes (post question, set awaiting-response marker).

After the feedback pass, continue to Step 7 (Final update) only if this is the
first time reaching completion. If Step 7 was already done in a prior iteration,
skip directly to Step 8 (status update) with an updated summary, then Step 9
(report).

## Step 7 — Final update

After all 3 passes, leave the issue in "In Progress" (the user decides when to move
it to Done or back to Todo).

Add a comment on the issue summarizing what was done:
> "Completed 3-pass idea refinement. The description now contains: research & options
> (Pass 1), evaluation & recommendation (Pass 2), and an action plan (Pass 3).
> Ready for human review."

## Step 8 — Create a project status update

Use the `save_status_update` Linear MCP tool to publish a project update:
- `type`: `"project"`
- `project`: the project ID or slug from Step 1
- `health`: choose based on the refined idea:
  - `onTrack` if the idea has a clear path forward and actionable next steps
  - `atRisk` if significant open questions or blockers remain
  - `offTrack` if the idea is not viable or requires major rethinking
- `body`: a concise Markdown summary of the idea refinement. Include:
  - The issue ID and title that was processed
  - Which passes were completed
  - The recommended option
  - The first actionable step
  - Any decisions needed

Example body:
```markdown
Refined SIM-3: Automate weekly report generation.

**Progress:**
- Completed 3-pass idea refinement (Pass 1: research & options, Pass 2: evaluation, Pass 3: action plan)
- **Recommended option:** Build a Python script triggered by GitHub Actions
- **First step:** Draft the script to pull data from the analytics API

**Decisions needed:** Confirm budget for GitHub Actions runners.
```

## Step 9 — Report

Print:
- Issue ID, title, and URL
- Which passes were completed (1/3, 2/3, 3/3)
- The recommended option (one sentence)
- The first actionable step
- Confirmation that a project status update was posted
- A reminder that the issue is in "In Progress" awaiting human review
