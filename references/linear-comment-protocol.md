# Linear Comment Protocol — Agent/Human Async Loop

Shared specification for agent-human asynchronous communication via Linear
comments. Used by `brain-linear-process-idea` and `brain-linear-process-tasks`.

## Problem

Both agent and human comments appear as the same author (Simone Basso) because
the Linear MCP uses a personal API token. The agent needs a deterministic way to
distinguish its own comments from human replies.

## Agent Comment Signature

Every comment posted by the agent MUST end with this signature block:

```markdown
---
🤖 **Agent** | <question-type> | <ISO-timestamp>
```

Where:
- `<question-type>` is one of: `question`, `status`, `completion`, `ack`
- `<ISO-timestamp>` is the current UTC time, e.g. `2026-04-14T10:30:00Z`

The `ack` type is used to acknowledge an incorporated human comment so it is not
re-processed on subsequent loop iterations.

Example agent question comment:

```markdown
I need clarification before proceeding:

1. Should the retry logic use exponential backoff or fixed intervals?
2. Is there a maximum number of retries?

---
🤖 **Agent** | question | 2026-04-14T10:30:00Z
```

## Description Checkpoint

When the agent posts a question and needs to wait for a human reply, it writes
a checkpoint marker into the issue description (append at the very end):

```markdown
<!-- agent-state: awaiting-response | comment-id:<comment-id> | since:<ISO-timestamp> -->
```

Where:
- `<comment-id>` is the ID of the agent's question comment
- `<ISO-timestamp>` matches the timestamp in the comment signature

## Resume Logic

On every skill run, BEFORE any other processing, check the issue description
for the `<!-- agent-state: awaiting-response ... -->` marker.

### If marker exists:

1. Extract `since` timestamp and `comment-id` from the marker.
2. Fetch all comments on the issue using `list_comments`.
3. Sort comments by `createdAt` ascending.
4. Find all comments created AFTER the `since` timestamp.
5. Among those, find the **first comment** that does NOT contain `🤖 **Agent**`
   in its body — this is the human reply.
6. **If a human reply is found:**
   - Read its content as the answer to the agent's question.
   - Remove the `<!-- agent-state: ... -->` marker from the issue description
     (update via `save_issue`).
   - Post a brief acknowledgment comment:
     ```
     Received your response — resuming work.
     ---
     🤖 **Agent** | status | <ISO-timestamp>
     ```
   - Continue with the skill's normal flow, using the reply as context.
7. **If no human reply is found:**
   - Stop and report: "Still waiting for your reply on the Linear comment. Skipping this issue."
   - Do NOT remove the marker. Do NOT proceed.
   - Move to the next project in the loop (if any).

### If marker does NOT exist:

Proceed with the skill's normal flow. The agent may post a question comment
at any defined pause point (see skill-specific sections below).

## Posting a Question

When the agent encounters ambiguity at a defined pause point:

1. Post a comment on the issue with the question + agent signature.
2. Note the returned comment ID.
3. Append the checkpoint marker to the issue description.
4. Stop processing this issue and report:
   > "Posted a question on <ID>: <title>. Waiting for your reply in Linear."
5. Move to the next project in the loop (if any).

## Pause Points by Skill

### brain-linear-process-idea

- **Before each pass** — if the issue context is ambiguous or insufficient.
- **After Pass 3** — if decisions are flagged that need human input before
  the idea can be promoted to a task.

### brain-linear-process-tasks

- **Before implementation (Step 4)** — if the task requirements are unclear.
- The agent should NOT pause mid-implementation. If stuck during
  implementation, complete what it can, note blockers in the commit/comment,
  and mark the issue for follow-up.

## General Comment Ingestion (Loop Mode)

When skills run in a loop, they perform a general comment ingestion on every
iteration, in addition to the agent-state resume check:

1. Fetch all comments on the issue.
2. Sort by `createdAt` ascending.
3. Find all human comments (NOT containing `🤖 **Agent**`) that appear AFTER
   the last agent comment. If no agent comments exist, all human comments since
   issue creation are candidates.
4. Incorporate the content of these unprocessed comments as additional context.
5. For each incorporated comment, post an `ack` acknowledgment:
   ```
   Incorporated your feedback — continuing work.
   ---
   🤖 **Agent** | ack | <ISO-timestamp>
   ```

This ensures unsolicited feedback (not just replies to agent questions) is
picked up and acted on during loop iterations.

### Question-Answer Cycle

The agent may go through multiple question-answer rounds on a single issue:

1. Agent posts a `question` comment + sets `agent-state` marker → stops.
2. Next iteration: agent finds the human reply → incorporates it → removes marker.
3. If the answer resolves all ambiguity → agent proceeds with the work.
4. If the answer raises new questions → agent posts another `question` → stops.
5. Cycle repeats until no open questions remain.

The issue is considered fully processed only when the work is complete AND no
`agent-state` marker exists.

## Edge Cases

- **Multiple comments before agent reads:** The agent reads ALL unsigned
  comments after the last agent comment, not just the first. Each one gets
  an `ack` acknowledgment.
- **User edits their reply:** The agent reads the comment body at fetch time,
  so edits before the next run are picked up automatically.
- **Agent posted question but skill re-runs with no reply yet:** The marker
  in the description prevents re-processing. The agent reports "still waiting"
  and moves on.
- **Unsolicited comments (no agent question pending):** Picked up by general
  comment ingestion and acknowledged with `ack`. The feedback is incorporated
  into the current or next processing step.
