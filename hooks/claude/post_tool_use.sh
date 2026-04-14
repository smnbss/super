#!/usr/bin/env bash
# super/hooks/claude/post_tool_use.sh
# Post-tool session logging + optional validation

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"
source "$SUPER_HOME/hooks/config.sh"

INPUT="$(cat)"

# Extract tool info
TOOL_NAME="$(echo "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("tool_name",""))' 2>/dev/null || echo "")"

# Log the tool use to session
if [[ -n "$TOOL_NAME" ]]; then
  session_append_turn "Claude Code" "tool" "$TOOL_NAME"
fi

# Run validators if configured (opt-in via hooks.postToolUse.runValidators)
if _super_config_enabled "hooks.postToolUse.runValidators"; then
  source "$SUPER_HOME/hooks/validators.sh"
  if _super_should_validate "$TOOL_NAME"; then
    _super_run_validators || true  # Don't block on validation failure
  fi
fi

exit 0
