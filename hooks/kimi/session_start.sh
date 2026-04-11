#!/usr/bin/env bash
# super/hooks/kimi/session_start.sh
# Kimi hook event: SessionStart

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/lib/session.sh"

INPUT="$(cat)"

session_append_turn "Kimi Code CLI" "session_start" "startup"

exit 0
