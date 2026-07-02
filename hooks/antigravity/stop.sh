#!/usr/bin/env bash
# super/hooks/antigravity/stop.sh
# Antigravity CLI (agy) hook event: Stop
# Fires: on agent termination / session end.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SUPER_HOME="${SUPER_HOME:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
source "$SUPER_HOME/hooks/session.sh"

# Drain stdin (agy pipes a payload even when unused) to avoid SIGPIPE.
cat >/dev/null 2>&1 || true

session_append_turn "Antigravity CLI" "session_end" ""

echo '{"decision":"allow"}'
exit 0
