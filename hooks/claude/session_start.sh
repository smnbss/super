#!/usr/bin/env bash
# super/hooks/claude/session_start.sh
# Hook event: SessionStart
# Install: add to .claude/settings.json under "SessionStart"

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

# Determine if this is startup, resume, or clear
trigger="$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('trigger','startup'))" 2>/dev/null || echo "startup")"

session_append_turn "Claude Code" "session_start" "trigger=$trigger"

# Exit 0 = allow session to continue normally
exit 0
