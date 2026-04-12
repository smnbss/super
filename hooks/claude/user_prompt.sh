#!/usr/bin/env bash
# super/hooks/claude/user_prompt.sh
# Hook event: UserPromptSubmit
# Install: add to .claude/settings.json under "UserPromptSubmit"
# Fires: when the user submits a prompt, before Claude processes it

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

# Extract the user message from the JSON payload
PROMPT="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('message', d.get('prompt', '')))
except:
    print('')
" 2>/dev/null || echo "")"

if [[ -n "$PROMPT" ]]; then
  session_append_turn "Claude Code" "user" "$PROMPT"
fi

# Must exit 0 and output no JSON to allow the prompt through
exit 0
