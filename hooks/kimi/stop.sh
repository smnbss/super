#!/usr/bin/env bash
# super/hooks/kimi/stop.sh
# Kimi hook event: Stop

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

RESPONSE="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    # Kimi Stop payload - extract last assistant content
    transcript = d.get('transcript', d.get('messages', []))
    for msg in reversed(transcript):
        if msg.get('role') == 'assistant':
            content = msg.get('content', '')
            if isinstance(content, list):
                texts = [p.get('text','') for p in content if p.get('type') == 'text']
                print(' '.join(texts)[:2000])
            else:
                print(str(content)[:2000])
            break
except:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$RESPONSE" ]]; then
  session_append_turn "Kimi Code CLI" "assistant" "$RESPONSE"
fi

exit 0
