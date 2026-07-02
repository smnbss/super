#!/usr/bin/env bash
# super/hooks/antigravity/pre_invocation.sh
# Antigravity CLI (agy) hook event: PreInvocation
# Fires: before the agent processes a turn — carries the user message.
# Maps to super's "user" turn (the old Gemini BeforeAgent / Claude UserPromptSubmit).
#
# NOTE: payload field names below are provisional (documented, not yet live-verified).
# Candidate keys tried in order; adjust once a real payload is captured.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

PROMPT="$(echo "$INPUT" | python3 -c "
import sys, json
def dig(d, *path):
    for k in path:
        if isinstance(d, dict): d = d.get(k)
        else: return None
    return d
try:
    d = json.load(sys.stdin)
    # Try nested agy shapes first, then flat fallbacks.
    txt = (dig(d, 'userMessage', 'text')
           or dig(d, 'userMessage', 'content')
           or dig(d, 'invocation', 'userMessage')
           or d.get('userMessage')
           or d.get('user_message')
           or d.get('message')
           or d.get('prompt')
           or d.get('user_input')
           or '')
    if isinstance(txt, (dict, list)):
        txt = json.dumps(txt)
    print(str(txt)[:4000])
except Exception:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$PROMPT" ]]; then
  session_append_turn "Antigravity CLI" "user" "$PROMPT"
fi

echo '{"decision":"allow"}'
exit 0
