---
name: brain-linear-create-project-context
description: >
  Create a new Linear project or enrich an existing one with structured context from
  its issues and user-provided information. Use when the user says "create project context",
  "update project context", "new project", "enrich project description", or passes a
  Linear project URL and asks to add context to it.
---

# Linear — Create Project Context

Create a new Linear project or update an existing one's Description with structured
context derived from its issues, current description, and any extra context the user
provides.

## Input

The Linear org slug is read from `$BRAIN_CONFIG` (default `~/.super/brain.config.yml`) → `linear.org`. The user MAY provide a Linear project URL, e.g.:
```
https://linear.app/<org>/project/super-edc40903e247/overview
```

The user MAY also provide additional context as free text (project name, architecture
notes, goals, constraints, links). This gets merged into the final description.

## Step 1 — Determine mode (create or update)

**If a Linear project URL is provided:**
- Extract the project slug from the URL (segment after `/project/`, before next `/`)
- Examples:
  - `https://linear.app/<org>/project/super-edc40903e247/overview` → `super-edc40903e247`
  - `https://linear.app/<org>/project/super-edc40903e247/issues` → `super-edc40903e247`
- Proceed to **Step 2A** (update existing project).

**If NO URL is provided:**
- Proceed to **Step 2B** (create new project).

## Step 2A — Fetch existing project and issues

**Important:** The Linear MCP `list_issues` tool does NOT resolve project slugs
reliably. Always fetch the project first, then use the returned project **name**
for `list_issues`.

1. **Get the project** using the `get_project` Linear MCP tool with `query: "<slug>"`,
   `includeResources: true`, `includeMembers: true`. Note the returned `name` and `id`.
2. **List all issues** using the `list_issues` Linear MCP tool with `project: "<project name from step 1>"`,
   `limit: 250`. If `hasNextPage` is true, paginate with the cursor until all issues
   are fetched.

Then proceed to **Step 3**.

## Step 2B — Create a new project

Derive a project **name** from the user's input. If the user provided a clear name or
topic, use it. If the input is vague, ask: *"What should I name this project?"*

**Find the user's private team:**
Use the `list_teams` Linear MCP tool to fetch all teams. Look for a team whose name
matches the user's name (e.g., "Simon", "Simone Basso") — this is the private team.
Heuristic: match against the `lead` name on existing projects, or pick a team with a
single-person feel (short key like "SIM", name matches a person not a department).

**Create the project** using the `save_project` Linear MCP tool:
- `name`: the derived project name
- `lead`: `"me"` (assigns to the current user)
- `addTeams`: `["<private team name>"]` (the team found above)
- `description`: empty for now (Step 4 will populate it)
- `state`: `"Planned"`

Record the returned project `id` and `url`.

Since this is a brand new project there are no issues yet — proceed to **Step 3** with
an empty issue list. The context will be built entirely from the user's input.

## Step 3 — Analyze and build context

Read the existing project description (if any). Then analyze all issues to extract:

- **Issue categories:** Group issues by prefix convention (e.g., "Task:", "Idea:", "Bug:")
  or by label. Summarize what types of work this project contains.
- **Key themes:** What recurring topics, components, or goals appear across issues?
- **Current state:** How many issues per status (Backlog, Todo, In Progress, Done)?
  What's the overall momentum?
- **Architecture/technical notes:** If issues reference specific files, repos, tools,
  or technical concepts, collect these into a coherent technical context section.
- **Processing guidance:** Extract key file paths, repo references, conventions,
  constraints, and related projects/resources that downstream skills need when
  processing individual issues in this project.
- **Open questions:** Issues that are ideas or have unresolved questions.

## Step 4 — Compose the description

Build a new project description in Markdown. Structure:

```markdown
## Context

<One paragraph: what this project is, its goal, and current state.>

<If the user provided extra context, integrate it here naturally — don't dump it
in a separate section. Weave it into the narrative.>

## Scope

<Bullet list of the main work streams / categories derived from issue analysis.
Include issue counts per category.>

## Technical Notes

<Architecture, key files, tools, dependencies, constraints — derived from issues
and user-provided context. Only include if there's meaningful technical content.>

## Processing Guidance

<For downstream skills: key files/repos to reference, project conventions,
constraints, and related projects/resources. Be specific: include absolute paths,
file names, and commands when they appear in issues.>

## Open Questions & Ideas

<Unresolved ideas or questions from issues. Reference issue IDs (e.g., SIM-3).>

## Status Snapshot

<Quick stats: total issues, by status, any overdue items. Date-stamp this section.>
<!-- snapshot: YYYY-MM-DD -->
```

**Rules:**
- Preserve any content from the existing description that is still accurate — don't
  discard prior work. Merge and update rather than replace.
- If the existing description already has good structure, evolve it rather than
  rewriting from scratch.
- Keep it concise. This is a reference document, not a novel.
- Use issue identifiers (e.g., SIM-5) when referencing specific issues.
- In **Processing Guidance**, optimize for an agent that will later pick up a single
  issue from this project. Give it the exact paths, conventions, and guardrails it
  needs to succeed.

## Step 5 — Update the project

Use the `save_project` Linear MCP tool to update the description:
- `id`: the project ID from Step 2
- `description`: the composed Markdown
- `summary`: a one-line summary (max 255 chars) if the current one is empty or generic

Also post a project status update with `save_status_update`:
- `type`: `"project"`
- `project`: the project ID or slug
- `health`: `"onTrack"`
- `body`: a brief summary of what changed in the description and any next steps

## Step 6 — Report

Print:
- The project name and URL
- How many issues were analyzed
- A brief summary of what changed in the description
- The full updated description for the user to review
