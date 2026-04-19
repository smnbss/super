#!/usr/bin/env bash
# super/hooks/claude/user_prompt.sh
# Hook event: UserPromptSubmit
# Install: add to .claude/settings.json under "UserPromptSubmit"
# Fires: when the user submits a prompt, before Claude processes it

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

INPUT="$(cat)"

# Extract the user message from the JSON payload
PROMPT="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('message', d.get('prompt', '')))
except:
    print('')
" 2>/dev/null || echo "")"

if [[ -n "$PROMPT" ]]; then
  session_append_turn "Claude Code" "user" "$PROMPT"
fi

# Update terminal title with current session info (title may have changed)
if [[ -n "${SUPER_SESSION_FILE:-}" && -f "$SUPER_SESSION_FILE" ]]; then
  # Extract title and metadata from session file
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

# Must exit 0 and output no JSON to allow the prompt through
exit 0
