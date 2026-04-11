#!/usr/bin/env bash
# super/hooks/claude/pre_tool_use.sh
# Security enforcement hook for PreToolUse

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/config.sh"
source "$SCRIPT_DIR/../../lib/security.sh"

INPUT="$(cat)"

# Only process if security hook is enabled
if ! _super_config_enabled "hooks.preToolUse.enabled"; then
  exit 0
fi

# Extract tool name and input
TOOL_NAME="$(echo "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("tool_name",""))' 2>/dev/null || echo "")"
TOOL_INPUT="$(echo "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get("tool_input",{})))' 2>/dev/null || echo "{}")"

# Run security check
_super_security_check "$TOOL_NAME" "$TOOL_INPUT"
RESULT=$?

if [[ $RESULT -eq 1 ]]; then
  # Block
  _super_security_block_reason "$TOOL_NAME" "$TOOL_INPUT" "Security policy violation"
  exit 1
fi

# exit 0 = allow (including ask mode - let Claude handle the prompt)
exit 0
