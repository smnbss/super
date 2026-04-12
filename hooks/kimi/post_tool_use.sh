#!/usr/bin/env bash
# super/hooks/kimi/post_tool_use.sh
# Kimi hook event: PostToolUse

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

TOOL_INFO="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tool = d.get('tool_name', 'unknown')
    inp  = d.get('tool_input', d.get('args', {}))

    if tool in ('read_file', 'list_dir', 'glob'):
        sys.exit(0)

    if tool in ('shell', 'bash', 'run_command'):
        cmd = inp.get('command', inp.get('cmd', ''))[:300]
        print(f'Shell: {cmd}')
    elif tool in ('write_file', 'edit_file', 'replace'):
        path = inp.get('path', inp.get('file_path', ''))
        print(f'{tool}: {path}')
    elif tool == 'web_search':
        print(f'WebSearch: {inp.get(\"query\",\"\")}')
    else:
        print(f'{tool}')
except SystemExit:
    pass
except:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$TOOL_INFO" ]]; then
  session_append_turn "Kimi Code CLI" "tool" "$TOOL_INFO"
fi

exit 0
