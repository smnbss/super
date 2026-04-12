#!/usr/bin/env bash
# super/hooks/gemini/after_tool.sh
# Gemini CLI hook event: AfterTool
# Fires: after each tool call

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

TOOL_INFO="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tool = d.get('tool_name', d.get('function_name', 'unknown'))
    args = d.get('tool_args', d.get('args', {}))

    # Skip noisy read tools
    if tool in ('read_file', 'list_directory', 'glob'):
        sys.exit(0)

    if tool == 'run_shell_command':
        cmd = args.get('command', args.get('cmd', ''))[:300]
        print(f'Shell: {cmd}')
    elif tool in ('write_file', 'replace'):
        path = args.get('path', args.get('filename', ''))
        print(f'{tool}: {path}')
    elif tool == 'web_search':
        q = args.get('query', '')
        print(f'WebSearch: {q}')
    else:
        print(f'{tool}')
except SystemExit:
    pass
except:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$TOOL_INFO" ]]; then
  session_append_turn "Gemini CLI" "tool" "$TOOL_INFO"
fi

echo '{}'
