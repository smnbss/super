#!/usr/bin/env bash
# super/hooks/gemini/after_agent.sh
# Gemini CLI hook event: AfterAgent
# Fires: when the agent completes its turn

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"

# Extract the agent's final response text
RESPONSE="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    # Gemini AfterAgent payload structure
    response = d.get('response', d.get('output', d.get('text', '')))
    if isinstance(response, dict):
        # May be nested under candidates
        candidates = response.get('candidates', [])
        if candidates:
            parts = candidates[0].get('content', {}).get('parts', [])
            texts = [p.get('text','') for p in parts if 'text' in p]
            print(' '.join(texts)[:2000])
        else:
            print(str(response)[:2000])
    else:
        print(str(response)[:2000])
except:
    pass
" 2>/dev/null || echo "")"

if [[ -n "$RESPONSE" ]]; then
  session_append_turn "Gemini CLI" "assistant" "$RESPONSE"
fi

echo '{}'
