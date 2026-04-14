#!/usr/bin/env bash
# super/hooks/claude/post_tool_use.sh
# Post-tool session logging + optional validation

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"
source "$SUPER_HOME/hooks/config.sh"

INPUT="$(cat)"

TOOL_INFO="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tool = d.get('tool_name', 'unknown')
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
  session_append_turn "Claude Code" "tool" "$TOOL_INFO"
fi

# Run validators if configured (opt-in via hooks.postToolUse.runValidators)
if _super_config_enabled "hooks.postToolUse.runValidators"; then
  source "$SUPER_HOME/hooks/validators.sh"
  if _super_should_validate "$TOOL_NAME"; then
    _super_run_validators || true  # Don't block on validation failure
  fi
fi

exit 0
