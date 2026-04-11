#!/usr/bin/env bash
# supercli/hooks/kimi/session_start.sh
# Kimi hook event: SessionStart

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../lib/session.sh"

INPUT="$(cat)"
session_init > /dev/null

session_append_turn "Kimi Code CLI" "session_start" "startup"

exit 0
