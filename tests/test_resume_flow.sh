#!/usr/bin/env bash
# Test the full resume flow with catchup

set -uo pipefail

SUPER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SUPER_HOME/lib/session.sh"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; RESET='\033[0m'

echo "═══════════════════════════════════════════════════════════"
echo "  Super Resume Flow Test with Debug"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Create a test session
mkdir -p "$(_super_sessions_dir)"
test_session="$(_super_sessions_dir)/2026-04-11_test_resume.md"

cat > "$test_session" << 'EOF'
# Super Session: test-resume

**Project:** test
**Started:** 2026-04-11 22:00:00
**Directory:** /tmp
**File:** 2026-04-11_test_resume.md

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

echo -e "${BLUE}Created test session:${RESET} $test_session"
echo ""

# Simulate cmd_launch with --resume
echo -e "${BLUE}Simulating: super claude --resume${RESET}"
echo ""

cli="claude"
do_resume=1
resume_file=""

# Simulate the logic from cmd_launch
echo "Step 1: Parse arguments"
echo "  do_resume = $do_resume"
echo "  resume_file = $resume_file"
echo ""

echo "Step 2: Determine session file"
if [[ -n "$resume_file" ]]; then
  echo "  Branch: Specific resume file provided"
  session_file="$test_session"
elif [[ "$do_resume" -eq 1 ]]; then
  echo "  Branch: --resume flag set, would show session picker"
  # Simulate user picking session #1
  picked="$test_session"
  echo "  User picked: $picked"
  
  if [[ "$picked" == "QUIT" ]]; then
    echo "  User cancelled"
    exit 1
  elif [[ -n "$picked" ]]; then
    echo "  Resuming session..."
    session_file="$picked"
  else
    echo "  No session picked, creating new"
    session_file="$test_session"
  fi
else
  echo "  Branch: New session"
  session_file="$test_session"
fi

echo ""
echo "Step 3: Check catchup condition"
echo "  do_resume = $do_resume"
echo "  session_file = $session_file"
echo "  Condition: [[ \"$do_resume\" -eq 1 && -n \"$session_file\" ]]"

if [[ "$do_resume" -eq 1 && -n "$session_file" ]]; then
  echo -e "  ${GREEN}✓ Condition TRUE - would run cmd_catchup${RESET}"
  echo ""
  echo -e "${BLUE}Step 4: Running catchup...${RESET}"
  echo ""
  
  # Simulate cmd_catchup
  echo "📋 Session Catchup"
  echo ""
  basename="$(basename "$session_file")"
  turns="$(grep -c '^## ' "$session_file" 2>/dev/null || echo 0)"
  echo "  Session: $basename"
  echo "  Turns: $turns"
  echo ""
  echo "  Recent activity:"
  grep -E '^## .*User' "$session_file" | tail -3 | while read -r line; do
    echo "  👤 User message"
  done
  echo ""
  
else
  echo -e "  ${RED}✗ Condition FALSE - catchup would NOT run${RESET}"
fi

# Cleanup
rm -f "$test_session"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test Complete"
echo "═══════════════════════════════════════════════════════════"
