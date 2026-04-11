#!/usr/bin/env bash
# supercli/hooks/gemini/user_prompt.sh
# Gemini CLI hook event: UserPromptSubmit
# Fires: after user submits prompt, before agent planning

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"

PROMPT="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', d.get('user_input', d.get('message', ''))))
except:
    print('')
" 2>/dev/null || echo "")"

if [[ -n "$PROMPT" ]]; then
  session_append_turn "Gemini CLI" "user" "$PROMPT"
fi

# Gemini: empty JSON = allow, pass through unchanged
echo '{}'
