#!/usr/bin/env bash
# supercli/hooks/codex/user_prompt.sh
# Codex hook event: UserPromptSubmit

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"

PROMPT="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', d.get('message', d.get('content', ''))))
except:
    print('')
" 2>/dev/null || echo "")"

if [[ -n "$PROMPT" ]]; then
  session_append_turn "Codex CLI" "user" "$PROMPT"
fi

exit 0
