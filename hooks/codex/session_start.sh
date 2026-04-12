#!/usr/bin/env bash
# super/hooks/codex/session_start.sh
# Codex hook event: SessionStart
# Install: add to hooks.json under "SessionStart"

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

trigger="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('trigger', 'startup'))
except:
    print('startup')
" 2>/dev/null || echo "startup")"

session_append_turn "Codex CLI" "session_start" "trigger=$trigger"

# Codex: exit 0 = allow
exit 0
