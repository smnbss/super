---
name: brain-git-sync
description: Sync the local brain repo with git — stage all changes, commit, push, and save a recap. Use after any session that modified brain files, or as a quick end-of-session save.
---

# /git-sync

Sync the local brain repo with git — stage all changes, commit, push, and save a recap.

## Steps

1. **Check status** — run `git status` to see staged, unstaged, and untracked files. If there are no changes at all, report "nothing to sync" and stop.

2. **Review changes** — run `git diff --stat` (unstaged) and `git diff --cached --stat` (staged) to understand what changed. Briefly summarize the categories of changes (e.g. "3 L2 files updated, 1 new outputs/agents report, 2 agent configs modified").

3. **Save recap** — BEFORE staging, create `outputs/agents/brain-git-sync/YYYY-MM-DD-HHMMSS.md` with:
   - Timestamp of sync
   - Summary of files changed (counts by category: memory, src, agents, outputs, etc.)
   - Brief description of the sync purpose
   - Any issues encountered
   - Note: commit hash will be added after commit

4. **Stage everything** — run `git add -A` to stage all changes including the newly created recap file.

5. **Commit** — write a concise commit message that summarizes the changes. Follow the repo's existing commit style (conventional commits: `chore:`, `docs:`, `fix:`, etc.). Use `docs:` for memory/content updates, `chore:` for config/agent/housekeeping changes, or a combined message if mixed. Include the Co-Authored-By trailer.

6. **Update recap with commit hash** — edit the recap file to add the commit hash from Step 5.

7. **Push** — run `git push` to sync with the remote. If the push fails due to diverged history, run `git pull --rebase` first, then retry the push. Never force-push.

8. **Report** — summarize what was committed and pushed (files changed, insertions, deletions).

## When to use
After any session that modified brain files, or as a quick end-of-session save.
