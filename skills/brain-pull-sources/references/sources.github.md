# GitHub source repos — cloned into  github/<owner>/<repo>/  by `pull_sources`.
# Non-GitHub sources go in the sibling sources.md file (they export into src/).
# `pull_sources` (no args) reads BOTH files. Lines starting with `#` are ignored.

github_clone https://github.com/<org>/repo1                       # service-a
github_clone https://github.com/<org>/repo2                       # service-b
github_clone https://github.com/<org>/repo3                       # service-c
