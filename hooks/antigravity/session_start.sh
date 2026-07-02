#!/usr/bin/env bash
# super/hooks/antigravity/session_start.sh
# Antigravity CLI (agy) hook event: SessionStart
# Fires: at session initialization.
#
# NOTE: agy hook stdin payloads are documented but not yet byte-for-byte
# verified (interactive TUI capture required — see
# outputs/projects/super/antigravity-cli-support.md). Field parsing here is
# defensive: unknown shapes degrade to logging the event without a payload.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat 2>/dev/null || true)"

session_append_turn "Antigravity CLI" "session_start" ""

# agy expects a JSON decision object on stdout; always exit 0 (non-zero = deny).
echo '{"decision":"allow"}'
exit 0
