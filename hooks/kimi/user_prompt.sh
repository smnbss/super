#!/usr/bin/env bash
# supercli/hooks/kimi/user_prompt.sh
# Kimi hook event: UserPromptSubmit

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"

PROMPT="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('message', d.get('prompt', d.get('content', ''))))
except:
    print('')
" 2>/dev/null || echo "")"

if [[ -n "$PROMPT" ]]; then
  session_append_turn "Kimi Code CLI" "user" "$PROMPT"
fi

exit 0
