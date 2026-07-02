#!/usr/bin/env bash
# super/hooks/antigravity/post_tool_use.sh
# Antigravity CLI (agy) hook event: PostToolUse
# Fires: after a tool call completes.
# Maps to super's "tool" turn (the old Gemini AfterTool).
#
# Payload uses agy's nested shape (documented): toolCall.args.CommandLine for
# shell runs, toolCall.args.ToolName for MCP tool calls. Flat fallbacks kept
# for safety until a live payload is captured.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

TOOL_INFO="$(echo "$INPUT" | python3 -c "
import sys, json
def dig(d, *path):
    for k in path:
        if isinstance(d, dict): d = d.get(k)
        else: return None
    return d
try:
    d = json.load(sys.stdin)
    args = dig(d, 'toolCall', 'args') or d.get('args') or {}
    name = (dig(d, 'toolCall', 'name')
            or (args.get('ToolName') if isinstance(args, dict) else None)
            or d.get('tool_name')
            or 'tool')

    cmd = ''
    if isinstance(args, dict):
        cmd = args.get('CommandLine') or args.get('command') or ''
    path = ''
    if isinstance(args, dict):
        path = args.get('FilePath') or args.get('file_path') or args.get('path') or ''

    # Skip noisy read-only tools
    if str(name) in ('read_file', 'list_directory', 'glob', 'ReadFile', 'ListDirectory'):
        sys.exit(0)

    if cmd:
        print(f'Shell: {str(cmd)[:300]}')
    elif path:
        print(f'{name}: {path}')
    else:
        print(str(name))
except SystemExit:
    pass
except Exception:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$TOOL_INFO" ]]; then
  session_append_turn "Antigravity CLI" "tool" "$TOOL_INFO"
fi

echo '{"decision":"allow"}'
exit 0
