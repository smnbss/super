#!/usr/bin/env bash
# super/hooks/codex/post_tool_use.sh
# Codex hook event: PostToolUse (currently Bash only)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/lib/session.sh"

INPUT="$(cat)"

TOOL_INFO="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tool = d.get('tool_name', 'Bash')
    inp  = d.get('tool_input', {})
    if tool == 'Bash':
        cmd = inp.get('command', '')[:300]
        print(f'Bash: {cmd}')
    else:
        print(f'{tool}')
except:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$TOOL_INFO" ]]; then
  session_append_turn "Codex CLI" "tool" "$TOOL_INFO"
fi

exit 0
