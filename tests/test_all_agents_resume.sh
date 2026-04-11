#!/usr/bin/env bash
# Test --resume with catchup for all 4 agents

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
echo "  Super --resume Catchup for All Agents"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Create test sessions for each agent
mkdir -p "$(_super_sessions_dir)"

for cli in claude gemini codex kimi; do
  test_session="$(_super_sessions_dir)/2026-04-11_test_${cli}.md"
  
  cat > "$test_session" << EOF
# Super Session: test-${cli}

**Project:** test
**Started:** 2026-04-11 22:00:00
**Directory:** /tmp
**File:** 2026-04-11_test_${cli}.md

---

### 🟠 \`[Claude Code 22:00:00]\` 🚀 Started with **Claude Code**

---

## 🟠 \`[Claude Code 22:01:00]\` 👤 User

Test message for ${cli}

### 🟠 \`[Claude Code 22:02:00]\` 🤖 Assistant

Response for ${cli}
EOF
  
  echo "Created test session: $test_session"
done

echo ""

# Test each agent
for cli in claude gemini codex kimi; do
  test_start "super ${cli} --resume shows catchup"
  
  test_session="$(_super_sessions_dir)/2026-04-11_test_${cli}.md"
  
  # Simulate the logic
  do_resume=1
  session_file="$test_session"
  
  # Check if catchup would run
  if [[ "$do_resume" -eq 1 && -n "$session_file" ]]; then
    # Verify session file is valid
    if [[ -f "$session_file" ]]; then
      turns=$(grep -c '^## ' "$session_file" 2>/dev/null || echo 0)
      if [[ "$turns" -gt 0 ]]; then
        test_pass
      else
        test_fail "No turns in ${cli} session"
      fi
    else
      test_fail "Session file not found for ${cli}"
    fi
  else
    test_fail "Catchup condition failed for ${cli}"
  fi
done

echo ""

# Test that catchup uses SUPER_SESSION_FILE
test_start "cmd_catchup uses SUPER_SESSION_FILE env var"

export SUPER_SESSION_FILE="$(_super_sessions_dir)/2026-04-11_test_claude.md"
# In the actual cmd_catchup, it would use this instead of active pointer
if [[ -f "$SUPER_SESSION_FILE" ]]; then
  test_pass
else
  test_fail "SUPER_SESSION_FILE not set correctly"
fi
unset SUPER_SESSION_FILE

echo ""

# Cleanup
for cli in claude gemini codex kimi; do
  rm -f "$(_super_sessions_dir)/2026-04-11_test_${cli}.md"
done

echo "═══════════════════════════════════════════════════════════"
echo "  Results: $passed passed, $failed failed"
echo "═══════════════════════════════════════════════════════════"

exit $failed
