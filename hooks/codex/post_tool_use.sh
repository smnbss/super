#!/usr/bin/env bash
# super/hooks/codex/post_tool_use.sh
# Codex hook event: PostToolUse

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

TOOL_INFO="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tool = d.get('tool_name', 'Bash')
    inp  = d.get('tool_input', {})

    # Skip noisy read tools
    if tool in ('read_file', 'list_directory', 'glob'):
        sys.exit(0)

    if tool == 'Bash':
        cmd = inp.get('command', '')[:300]
        print(f'Bash: {cmd}')
    elif tool in ('Write', 'Edit', 'MultiEdit'):
        path = inp.get('file_path', inp.get('path', ''))
        print(f'{tool}: {path}')
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
  session_append_turn "Codex CLI" "tool" "$TOOL_INFO"
fi

exit 0
