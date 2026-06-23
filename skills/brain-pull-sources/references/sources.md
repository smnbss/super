# Knowledge sources — exported into  src/<source>/  by `pull_sources`.
# GitHub repos go in the sibling sources.github.md file (they clone into github/).
# `pull_sources` (no args) reads BOTH files. Lines starting with `#` are ignored.

confluence_space_to_md https://<your-org>.atlassian.net/wiki/spaces/<SPACE_KEY>/overview   # Wiki space
gdrive_to_md https://drive.google.com/drive/folders/<your-folder-id>                       # e.g. top-level team folder

linear_to_md https://linear.app/<your-org>/projects/all                                                         # Linear all projects
linear_issues_to_md https://linear.app/<your-org>/team/<TEAM_KEY>/projects/all                                   # Team issues

metabase_index https://metabase.<your-domain>.io/                                                            # Metabase
