#!/usr/bin/env bash
# super/hooks/codex/stop.sh
# Codex hook event: Stop

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

# Debug: Log the full Codex Stop payload to identify correct field paths
DEBUG_DIR="$SUPER_HOME/.debug"
mkdir -p "$DEBUG_DIR"
echo "$INPUT" > "$DEBUG_DIR/codex-stop-payload-$(date +%s).json"

# Note: Codex Stop payload structure is being debugged.
# The payload is saved to .debug/ for analysis.
# Assistant capture remains disabled pending payload verification.

session_append_turn "Codex CLI" "session_end" ""

exit 0
