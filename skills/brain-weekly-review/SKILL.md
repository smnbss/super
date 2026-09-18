---
name: brain-weekly-review
description: >
  Compile a weekly summary from Workflowy notes, X posts, and Linear project updates.
  Use when the user says "weekly review", "week summary", "what happened this week",
  or asks for a weekly retrospective of their activity.
---

# Weekly Review

Compile a weekly summary from Workflowy notes, X posts, and Linear project updates into a single review.

## Steps
1. Read this week's notes from `src/workflowly/`.
   ⚠️ **NOT `outputs/agents/my-workflowy/`. That directory DOES NOT EXIST and never did.**
   A read of it returns nothing, and the "what I was thinking about" section comes out empty with
   no warning. Measured 2026-09-18.
   ⚠️ **Note the spelling: the directory is `workflowly`, the topic is `workflowy`.**
2. Read the latest weekly file from `outputs/agents/my-x.com/` (weekly-YYYY-WNN.md)
3. Read the latest file from `outputs/agents/.old/tech-linear-project-updates/`.
   ⚠️ **CLOSED CORPUS. The producer is RETIRED and nothing writes to it**, so the newest report is
   from the date it was archived. **Say that date in the review**, or a stale project update reads
   as this week's news. ⚠️ **`outputs/agents/linear-project-updates/` NEVER EXISTED under that
   name** — the archived folder carries the `tech-` prefix.

⚠️ **STATE THE SCOPE OF AN EMPTY SECTION.** If a source yields nothing, write that it yielded
nothing and name the path you read. **A section silently omitted is indistinguishable from a quiet
week.**
4. Synthesize into a weekly review covering:
   - What shipped / key decisions made
   - What I was thinking about (from workflowy)
   - What I shared publicly (from x.com)
   - Project status changes (from linear)
5. Print to terminal — do not save to file unless asked

## Output format
- **Shipped / decided**: bullet list
- **On my mind**: bullet list from workflowy
- **Public**: tweets or threads worth noting
- **Projects**: status changes only (not the full report)
