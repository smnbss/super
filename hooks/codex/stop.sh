#!/usr/bin/env bash
# super/hooks/codex/stop.sh
# Codex hook event: Stop

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"

# Note: Codex Stop payload is simpler than Claude's - it doesn't
# include full transcript, so we capture what we can
REASON="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('stopReason', d.get('reason', 'turn_complete')))
except:
    print('turn_complete')
" 2>/dev/null || echo "turn_complete")"

# Log turn end - actual response text captured via agent output if available
OUTPUT="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    out = d.get('output', d.get('response', d.get('text', '')))
    if out:
        print(str(out)[:2000])
except:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$OUTPUT" ]]; then
  session_append_turn "Codex CLI" "assistant" "$OUTPUT"
fi

exit 0
