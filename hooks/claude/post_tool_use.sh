#!/usr/bin/env bash
# super/hooks/claude/post_tool_use.sh
# Hook event: PostToolUse
# Install: add to .claude/settings.json under "PostToolUse"
# Fires: after each tool call completes

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"

# Extract tool name and key input fields
TOOL_INFO="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tool = d.get('tool_name', 'unknown')
    inp  = d.get('tool_input', {})

    # Format depending on tool type
    if tool == 'Bash':
        cmd = inp.get('command', '')[:300]
        print(f'Bash: {cmd}')
    elif tool in ('Write', 'Edit', 'MultiEdit'):
        path = inp.get('file_path', inp.get('path', ''))
        print(f'{tool}: {path}')
    elif tool == 'Read':
        path = inp.get('file_path', inp.get('path', ''))
        # Skip logging reads - too noisy
        sys.exit(0)
    elif tool == 'WebSearch':
        q = inp.get('query', '')
        print(f'WebSearch: {q}')
    else:
        print(f'{tool}')
except SystemExit:
    pass
except:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$TOOL_INFO" ]]; then
  session_append_turn "Claude Code" "tool" "$TOOL_INFO"
fi

exit 0
