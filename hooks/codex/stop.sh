#!/usr/bin/env bash
# super/hooks/codex/stop.sh
# Codex hook event: Stop

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

# Note: Codex Stop payload does not include full assistant response transcript,
# so assistant capture is disabled to avoid empty/misleading entries.
# We still log the session end marker.

session_append_turn "Codex CLI" "session_end" ""

exit 0
