---
name: brain-git-sync
description: Sync the local brain repo with git — stage all changes, commit, and push. Use after any session that modified brain files, or as a quick end-of-session save.
---

# /git-sync

Sync the local brain repo with git — stage all changes, commit, and push.

## Steps

1. **Check status** — run `git status` to see staged, unstaged, and untracked files. If there are no changes at all, report "nothing to sync" and stop.

2. **Review changes** — run `git diff --stat` (unstaged) and `git diff --cached --stat` (staged) to understand what changed. Briefly summarize the categories of changes (e.g. "3 L2 files updated, 1 new outputs/agents report, 2 agent configs modified").

3. **Stage everything** — run `git add -A` to stage all changes (this repo is a private knowledge base, no secrets risk).

4. **Commit** — write a concise commit message that summarizes the changes. Follow the repo's existing commit style (conventional commits: `chore:`, `docs:`, `fix:`, etc.). Use `docs:` for memory/content updates, `chore:` for config/agent/housekeeping changes, or a combined message if mixed. Include the Co-Authored-By trailer.

5. **Push** — run `git push` to sync with the remote. If the push fails due to diverged history, run `git pull --rebase` first, then retry the push. Never force-push.

6. **Report** — summarize what was committed and pushed (files changed, insertions, deletions).

## When to use
After any session that modified brain files, or as a quick end-of-session save.
