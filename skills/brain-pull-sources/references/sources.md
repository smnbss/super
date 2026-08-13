# Knowledge sources — exported into  src/<source>/  by `pull_sources`.
# GitHub repos go in the sibling sources.github.md file (they clone into github/).
# `pull_sources` (no args) reads BOTH files. Lines starting with `#` are ignored.
#
# Each line is `<tool> <args>`, where <tool> must name a real wrapper in bin/.
# An unknown tool name is a failed source, not a skipped line — check `ls bin/`.

confluence_space_to_md https://<your-org>.atlassian.net/wiki/spaces/<SPACE_KEY>/overview                     # Wiki space
drive_to_md https://drive.google.com/drive/folders/<your-folder-id> --mode full                              # Drive: full markdown
drive_to_md https://drive.google.com/drive/folders/<your-folder-id> --mode index                             # Drive: INDEX.md only (big/low-signal drives)

# Outline: ONE line for the whole workspace. With no collection URL (or just the base
# URL) the exporter enumerates every collection the token can see, so a collection
# created upstream is picked up on the next pull. Prefer this over one line per
# collection — a hand-maintained list silently misses new collections, and a missing
# collection is indistinguishable from one that does not exist.
# Collections named `[TEST] …` are skipped; pass --include-test to export them, or
# --exclude SUBSTR (repeatable) to drop others by name. Pass a /collection/ URL to
# export exactly one.
outline_to_md https://docs.<your-domain>.com/                                                                # Outline: ALL collections

linear_to_md https://linear.app/<your-org>/projects/all                                                      # Linear all projects
linear_issues_to_md https://linear.app/<your-org>/team/<TEAM_KEY>/projects/all                               # Team issues

metabase_index https://metabase.<your-domain>.io/                                                            # Metabase dashboard/card index

gmeet_to_md <your-email>@<your-domain>.com                                                                   # Google Meet/Calendar harvest (full-span re-harvest by default)
workflowly_to_md                                                                                             # WorkFlowy outline — needs WORKFLOWY_API_KEY in .env.local
medium_to_md https://medium.com/feed/@<your-handle>                                                          # Medium posts (RSS)
personio_to_md                                                                                               # Staff roster (Personio API) — needs PERSONIO_CLIENT/PERSONIO_SECRET in .env.local

# ClickUp — only if you still have content there; Outline/Confluence supersede it.
# clickup_doc_to_md https://app.clickup.com/<team-id>/v/dc/<doc-id>                                          # ClickUp doc
# clickup_prj_to_md https://app.clickup.com/<team-id>/v/li/<list-id>                                         # ClickUp list/project
