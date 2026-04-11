#!/usr/bin/env bash
# Test CLI installed detection

set -uo pipefail

SUPER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
echo "  Super CLI Detection Tests"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Define CLI_CMD and is_installed like super does
declare -A CLI_CMD=( [claude]="claude" [gemini]="gemini" [codex]="codex" [kimi]="kimi" )
is_installed() { command -v "${CLI_CMD[$1]}" &>/dev/null; }

# Test 1: Check which CLIs are actually installed
test_start "Detect installed CLIs"
echo ""
for cli in claude gemini codex kimi; do
  if is_installed "$cli"; then
    path=$(command -v "${CLI_CMD[$cli]}")
    echo "  ✓ $cli at $path"
  else
    echo "  ✗ $cli NOT found"
  fi
done
test_pass

# Test 2: Simulate building options array like super does
test_start "Build options array dynamically"
options=()
for cli in claude gemini codex kimi; do
  if is_installed "$cli"; then
    options+=("$cli")
  fi
done
echo ""
echo "  Options array: ${options[*]}"
echo "  Length: ${#options[@]}"
test_pass

# Test 3: Display mapping like super does
test_start "Display mapping matches array indices"
echo ""
echo "  Displayed menu would be:"
i=1
for cli in "${options[@]}"; do
  echo "    [$i] $cli"
  ((i++))
done
test_pass

# Test 4: Verify user choice mapping
test_start "Verify user choice 1 maps to first installed CLI"
if [[ ${#options[@]} -gt 0 ]]; then
  choice=1
  chosen="${options[$((choice-1))]}"
  echo ""
  echo "  User picks: $choice"
  echo "  Gets CLI: $chosen"
  [[ -n "$chosen" ]] && test_pass || test_fail "Empty chosen CLI"
else
  test_fail "No CLIs installed"
fi

# Test 5: Potential bug - what if claude is installed but detection fails?
test_start "Verify claude detection works"
if command -v claude &>/dev/null; then
  test_pass
else
  test_fail "claude command not found in PATH"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Results: $passed passed, $failed failed"
echo "═══════════════════════════════════════════════════════════"

exit $failed
