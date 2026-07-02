#!/usr/bin/env bash
# super/hooks/antigravity/post_invocation.sh
# Antigravity CLI (agy) hook event: PostInvocation
# Fires: after the agent finishes a turn — carries the assistant response.
# Maps to super's "assistant" turn (the old Gemini AfterAgent).
#
# NOTE: payload field names below are provisional (documented, not yet live-verified).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

RESPONSE="$(echo "$INPUT" | python3 -c "
import sys, json
def dig(d, *path):
    for k in path:
        if isinstance(d, dict): d = d.get(k)
        else: return None
    return d
try:
    d = json.load(sys.stdin)
    txt = (dig(d, 'assistantMessage', 'text')
           or dig(d, 'assistantMessage', 'content')
           or dig(d, 'invocation', 'assistantMessage')
           or d.get('assistantMessage')
           or d.get('response')
           or d.get('output')
           or d.get('text')
           or '')
    if isinstance(txt, (dict, list)):
        txt = json.dumps(txt)
    print(str(txt)[:4000])
except Exception:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$RESPONSE" ]]; then
  session_append_turn "Antigravity CLI" "assistant" "$RESPONSE"
fi

echo '{"decision":"allow"}'
exit 0
