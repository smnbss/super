#!/usr/bin/env bash
# ensure-repos.sh — run ON the session VM. Makes sure every repo a stack builds from
# is present and current, then prints the matching compose service names.
#
# Argument 1 is the repo-or-preset pattern. Everything the caller needs comes back on
# STDOUT as one service name per line. Progress goes to STDERR, so the caller can
# capture stdout directly.
#
# ⚠️ Why this exists: jungle-golden-20260827 carried 2 of the 72 repos, and
#    `session create` assumed the golden image held every one. It ran
#    `cd ~/jungle/<repo>` against a directory that was not there, printed
#    "No such file or directory", and still exited 0 with a state file claiming a
#    branch that never existed. See SIM-63.
#
# ⚠️ The golden image does NOT need the repos. Measured 2026-08-29: `docker compose
#    -f compose.yaml config` parses cleanly with 57 of 60 build contexts absent,
#    because compose.yaml is generated up front and lists every service whatever is
#    on disk. So the clone belongs here, per session, not in the image.
set -uo pipefail

PATTERN="${1:?usage: ensure-repos.sh <repo-or-preset>}"
JUNGLE="$HOME/jungle"

say() { printf '  %s\n' "$*" >&2; }

cd "$JUNGLE" || { printf 'error: no %s\n' "$JUNGLE" >&2; exit 1; }

SERVICES="$(docker compose -f compose.yaml config --services 2>/dev/null | grep -- "$PATTERN")"
[[ -n "$SERVICES" ]] || { printf 'error: no compose service matches %s\n' "$PATTERN" >&2; exit 1; }

# Resolve each matching service to its build context, then to the top-level directory
# under the jungle root. A context can sit deeper than one level (starter/backend), so
# take the FIRST path element, never the basename.
DIRS="$(docker compose -f compose.yaml config --format json 2>/dev/null \
  | jq -r --arg p "$PATTERN" '
      .services | to_entries
      | map(select(.key | contains($p)))
      | map(select(.value.build != null))
      | map(.value.build.context) | unique[]' \
  | sed -e "s#^${JUNGLE}/##" -e 's#/.*##' | sort -u)"

# The branch is cut in the pattern directory itself, so ensure it even when no service
# builds from it directly.
[[ -d "$JUNGLE/$PATTERN" || -z "$PATTERN" ]] || DIRS="$DIRS
$PATTERN"
DIRS="$(printf '%s\n' $DIRS | sort -u)"

# bin/repos.sh is the registry of record for clone URLs. Fall back to weroad/<dir> only
# when the directory is absent from it.
repo_url() {
  local dir="$1" url
  url="$(grep -oE "git@github.com:[A-Za-z0-9._-]+/${dir}\.git" bin/repos.sh 2>/dev/null | head -1)"
  printf '%s' "${url:-git@github.com:weroad/${dir}.git}"
}

for dir in $DIRS; do
  [[ -n "$dir" ]] || continue
  if [[ -d "$JUNGLE/$dir/.git" ]]; then
    say "refreshing $dir"
    git -C "$JUNGLE/$dir" fetch --quiet origin 2>/dev/null || say "WARNING: fetch failed for $dir"
    # Only fast-forward. A session VM can carry unpushed work, and a reset would
    # destroy it — `session rm` refuses to delete a VM for exactly that reason.
    git -C "$JUNGLE/$dir" pull --ff-only --quiet 2>/dev/null \
      || say "NOTE: $dir is not on a fast-forwardable branch. Left as it is."
  else
    say "cloning $dir"
    # ⚠️ repos.sh lists SSH URLs and the VM has no GitHub SSH key. inject_github_auth
    #    installs an insteadOf rewrite to token HTTPS, so the SSH form works here.
    git clone --quiet "$(repo_url "$dir")" "$JUNGLE/$dir" \
      || { printf 'error: cannot clone %s\n' "$dir" >&2; exit 1; }
  fi
done

printf '%s\n' "$SERVICES"
