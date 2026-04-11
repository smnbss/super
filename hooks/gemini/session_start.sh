#!/usr/bin/env bash
# super/hooks/gemini/session_start.sh
# Gemini CLI hook event: SessionStart
# Install: add to .gemini/settings.json under "hooks.SessionStart"

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"
session_init > /dev/null

trigger="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('trigger', 'startup'))
except:
    print('startup')
" 2>/dev/null || echo "startup")"

session_append_turn "Gemini CLI" "session_start" "trigger=$trigger"

# Gemini expects JSON output - empty object = allow
echo '{}'
