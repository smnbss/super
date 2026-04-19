#!/usr/bin/env bash
# super/hooks/claude/session_start.sh
# Hook event: SessionStart
# Install: add to .claude/settings.json under "SessionStart"

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

# Determine if this is startup, resume, or clear
trigger="$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('trigger','startup'))" 2>/dev/null || echo "startup")"

session_append_turn "Claude Code" "session_start" "trigger=$trigger"

# Update terminal title from session metadata
if [[ -n "${SUPER_SESSION_FILE:-}" && -f "$SUPER_SESSION_FILE" ]]; then
  title="$(grep '^# Super Session:' "$SUPER_SESSION_FILE" 2>/dev/null | sed 's/# Super Session: //' | head -1 || true)"
  [[ -z "$title" ]] && title="untitled"

  cli="$(grep '^\*\*CLI:\*\*' "$SUPER_SESSION_FILE" 2>/dev/null | sed 's/\*\*CLI:\*\* //' | head -1 || true)"
  [[ -z "$cli" ]] && cli="claude"

  model="$(grep '^\*\*Model:\*\*' "$SUPER_SESSION_FILE" 2>/dev/null | sed 's/\*\*Model:\*\* //' | head -1 || true)"

  # Set icon based on CLI
  icon="🟠"
  [[ "$cli" == "gemini" ]] && icon="🔵"
  [[ "$cli" == "codex" ]] && icon="🟢"

  # Set terminal tab title (OSC 0 and OSC 2)
  model_suffix=""
  [[ -n "$model" ]] && model_suffix=" ($model)"
  printf '\033]0;%s %s%s\007' "$icon" "$title" "$model_suffix"
  printf '\033]2;%s %s%s\007' "$icon" "$title" "$model_suffix"
fi

# Exit 0 = allow session to continue normally
exit 0
