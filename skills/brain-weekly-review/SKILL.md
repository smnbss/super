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
1. Read the latest file from `outputs/agents/my-workflowy/` (this week's daily notes)
2. Read the latest weekly file from `outputs/agents/my-x.com/` (weekly-YYYY-WNN.md)
3. Read the latest file from `outputs/agents/linear-project-updates/`
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
