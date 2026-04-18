---
name: brain-push-reports
description: >
  Push the latest agent report outputs to their matching ClickUp document pages.
  Use when the user says "push reports", "sync reports to clickup",
  "update clickup reports", or asks to publish agent outputs.
---

# Push Reports

Push the latest agent report outputs to their matching ClickUp document pages (create or update).

## Steps

1. **List ClickUp pages** — call `clickup_list_document_pages` with
   `document_id: "29fzc-67895"` and `max_page_depth: 3`.
   The response is large. Parse the JSON to find page `"29fzc-360855"`
   (named "Reports") and extract only its direct children (the subpages).
   For each child, also note any grandchildren (existing report pages).

2. **Match with local agents** — for each subpage name (e.g. `seo`,
   `tech-post-mortem-summary`), check if a matching folder exists under
   `.claude/agents/<name>/` AND a corresponding `outputs/agents/<name>/` folder.

3. **Find latest output** — in each matched `outputs/agents/<name>/` folder,
   find the `.md` file that sorts last alphabetically (files are named
   `YYYY-MM-DD-*.md`, so alphabetical = chronological). Ignore `.bak.md`
   files.

4. **Create or update** — for each matched report:
   - Derive the page name from the filename without `.md`
     (e.g. `2026-03-24-seoreport`).
   - If a grandchild page with that exact name already exists under the
     subpage, **update** it:
     ```
     clickup_update_document_page
       document_id: "29fzc-67895"
       page_id: <existing grandchild id>
       name: <filename without .md>
       content_format: "text/md"
       content: <full file contents>
     ```
   - If no matching grandchild exists, **create** it:
     ```
     clickup_create_document_page
       document_id: "29fzc-67895"
       parent_page_id: <subpage id>
       name: <filename without .md>
       content_format: "text/md"
       content: <full file contents>
     ```

5. **Report results** — summarize which pages were created and which were
   updated (include the subpage name and report filename for each).
