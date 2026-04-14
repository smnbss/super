#!/usr/bin/env bash
# super/hooks/gemini/stop.sh
# Gemini CLI hook event: Stop (session end)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

session_append_turn "Gemini CLI" "session_end" ""

exit 0
