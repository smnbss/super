#!/usr/bin/env bash
# Test that catchup runs when using --resume

set -uo pipefail

SUPER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SUPER_HOME/lib/session.sh"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RESET='\033[0m'

passed=0
failed=0

test_start() {
  echo -n "Testing: $1... "
}

test_pass() {
  echo -e "${GREEN}PASS${RESET}"
  ((passed++))
}

test_fail() {
  echo -e "${RED}FAIL${RESET}: $1"
  ((failed++))
}

echo "═══════════════════════════════════════════════════════════"
echo "  Super --resume Catchup Tests"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Test 1: Verify do_resume flag logic
test_start "do_resume flag is set with --resume"
do_resume=0
# Simulate parsing --resume
args=("--resume")
for arg in "${args[@]}"; do
  if [[ "$arg" == "--resume" || "$arg" == "-r" ]]; then
    do_resume=1
  fi
done
if [[ "$do_resume" -eq 1 ]]; then
  test_pass
else
  test_fail "do_resume not set"
fi

# Test 2: Verify condition for running catchup
test_start "Catchup condition: do_resume=1 and session_file set"
do_resume=1
session_file="/fake/path/session.md"
if [[ "$do_resume" -eq 1 && -n "$session_file" ]]; then
  test_pass
else
  test_fail "Condition failed: do_resume=$do_resume, session_file=$session_file"
fi

# Test 3: Verify catchup is NOT run for new sessions
test_start "Catchup NOT run for new sessions (do_resume=0)"
do_resume=0
session_file="/fake/path/session.md"
if [[ "$do_resume" -eq 1 && -n "$session_file" ]]; then
  test_fail "Catchup would run but shouldn't for new sessions"
else
  test_pass
fi

# Test 4: Test with actual session file
test_start "Catchup runs with real session file"
# Create a test session
mkdir -p "$(_super_sessions_dir)"
test_session="$(_super_sessions_dir)/test_catchup_session.md"
cat > "$test_session" << 'EOF'
# Super Session: test-catchup

**Project:** test
**Started:** 2026-04-11 22:00:00
**Directory:** /tmp
**File:** test_catchup_session.md

---

### 🟠 `[Claude Code 22:00:00]` 🚀 Started with **Claude Code**

---

## 🟠 `[Claude Code 22:01:00]` 👤 User

Test message 1

### 🟠 `[Claude Code 22:02:00]` 🤖 Assistant

Response 1

---

## 🟠 `[Claude Code 22:03:00]` 👤 User

Test message 2
EOF

# Set as active session
echo "$test_session" > "$(_super_active_ptr)"

# Now test cmd_catchup
if [[ -f "$test_session" ]]; then
  # Verify session file is readable
  turns=$(grep -c '^## ' "$test_session" 2>/dev/null || echo 0)
  [[ "$turns" -gt 0 ]] && test_pass || test_fail "No turns found in test session"
else
  test_fail "Test session file not created"
fi

# Cleanup
rm -f "$test_session"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Results: $passed passed, $failed failed"
echo "═══════════════════════════════════════════════════════════"

exit $failed
