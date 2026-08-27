#!/usr/bin/env bash
# Preflight gate for brain-work-on-claude-cloud.
#
# This skill only works from inside a wr-cloud container whose main git repo is
# weroad/jungle. Every other starting position — a laptop, a cloud session on a
# different repo, a wr-cloud container without the setup script — fails here.
#
# Exit 0 = safe to continue. Exit 1 = STOP, report, run nothing.
#
# Usage:  ./preflight.sh          # checks $PWD, then /home/user/jungle
#         ./preflight.sh <path>   # checks that path

set -uo pipefail

FATAL=()
WARN=()
JUNGLE=""

# --- 1. Host kind -----------------------------------------------------------
OS="$(uname -s)"
if [ "$OS" != "Linux" ]; then
  FATAL+=("host is $OS ($(hostname 2>/dev/null)) — wr-cloud containers are Linux. This looks like a laptop session.")
fi

# --- 2. The jungle repo -----------------------------------------------------
find_jungle() {
  for c in "$@"; do
    [ -n "$c" ] || continue
    if [ -f "$c/bin/jungle.up.sh" ] && [ -f "$c/scripts/compose.merge.js" ] \
       && [ -f "$c/compose.jungle.yaml" ]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

JUNGLE="$(find_jungle "${1:-}" "$PWD" "$(git rev-parse --show-toplevel 2>/dev/null)" /home/user/jungle)" || true

if [ -z "$JUNGLE" ]; then
  FATAL+=("no weroad/jungle checkout found (looked for bin/jungle.up.sh + scripts/compose.merge.js + compose.jungle.yaml in \$PWD, the enclosing git repo, and /home/user/jungle).")
else
  REMOTE="$(git -C "$JUNGLE" remote get-url origin 2>/dev/null || echo '')"
  case "$REMOTE" in
    *weroad/jungle*) : ;;
    "")  WARN+=("$JUNGLE has the jungle layout but no origin remote — continuing on layout alone.") ;;
    *)   FATAL+=("$JUNGLE has the jungle layout but origin is '$REMOTE', not weroad/jungle.") ;;
  esac
fi

# --- 3. wr-cloud setup-script markers ---------------------------------------
# jungle-ca-inject is written by the wr-cloud setup script and exists nowhere
# else. It is what separates a wr-cloud container from a laptop jungle checkout.
command -v jungle-ca-inject >/dev/null 2>&1 \
  || FATAL+=("jungle-ca-inject is not on PATH — the wr-cloud setup script has not run here. Without it, containers never trust the egress-proxy CA (Step 5a).")

# --- Repairable, not fatal --------------------------------------------------
if [ -n "$JUNGLE" ]; then
  [ -f "$JUNGLE/dbt/compose.yaml" ] && [ -f "$JUNGLE/dlt-pipelines/compose.yaml" ] \
    || WARN+=("the two compose extends: stubs are missing — compose.yaml will not parse (Step 4).")
fi
command -v gcloud >/dev/null 2>&1 || WARN+=("gcloud is not on PATH.")
[ -f /root/.config/gcloud/application_default_credentials.json ] \
  || [ -f "$HOME/.config/gcloud/application_default_credentials.json" ] \
  || WARN+=("no application_default_credentials.json found — the GCS dump fallback in Step 6 needs it.")
docker info >/dev/null 2>&1 || WARN+=("dockerd is not responding — Step 1 restarts it.")

# --- Verdict ----------------------------------------------------------------
if [ ${#FATAL[@]} -gt 0 ]; then
  echo "PREFLIGHT FAILED — this is not a wr-cloud jungle session. STOP."
  for f in "${FATAL[@]}"; do echo "  ✗ $f"; done
  echo
  echo "Run this skill from a Claude Code session on the wr-cloud environment,"
  echo "where the main git repo is weroad/jungle. Do not adapt the steps to run here."
  exit 1
fi

echo "PREFLIGHT PASSED — wr-cloud jungle session."
echo "  jungle: $JUNGLE"
for w in "${WARN[@]}"; do echo "  ! $w"; done
exit 0
