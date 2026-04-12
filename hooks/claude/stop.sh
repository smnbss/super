#!/usr/bin/env bash
# super/hooks/claude/stop.sh
# Hook event: Stop
# Install: add to .claude/settings.json under "Stop"
# Fires: when Claude finishes responding (end of turn)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

# Prevent infinite loop: if stop_hook_active is true, a previous Stop hook
# triggered this - don't recurse
HOOK_ACTIVE="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(str(d.get('stop_hook_active', False)).lower())
except:
    print('false')
" 2>/dev/null || echo "false")"

if [[ "$HOOK_ACTIVE" == "true" ]]; then
  exit 0
fi

# Extract assistant response text
RESPONSE="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    # Claude Code Stop payload has transcript with the last assistant turn
    transcript = d.get('transcript', [])
    # Find the last assistant message
    for msg in reversed(transcript):
        if msg.get('role') == 'assistant':
            content = msg.get('content', '')
            if isinstance(content, list):
                # Extract text blocks
                texts = [b.get('text','') for b in content if b.get('type') == 'text']
                print(' '.join(texts)[:2000])
            else:
                print(str(content)[:2000])
            break
except Exception as e:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$RESPONSE" ]]; then
  session_append_turn "Claude Code" "assistant" "$RESPONSE"
fi

exit 0
