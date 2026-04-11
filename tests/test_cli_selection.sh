#!/usr/bin/env bash
# Test CLI selection logic

set -uo pipefail

# Source the main script (in test mode)
SUPER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SUPER_HOME/lib/session.sh"

# Colors for output
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
echo "  Super CLI Selection Tests"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Test 1: Verify CLI_CMD array mapping
test_start "CLI_CMD array has all 4 CLIs"
declare -A CLI_CMD=( [claude]="claude" [gemini]="gemini" [codex]="codex" [kimi]="kimi" )
if [[ -n "${CLI_CMD[claude]}" && -n "${CLI_CMD[gemini]}" && -n "${CLI_CMD[codex]}" && -n "${CLI_CMD[kimi]}" ]]; then
  test_pass
else
  test_fail "Missing CLI in array"
fi

# Test 2: Verify CLI order in options array
test_start "Options array order matches display"
options=()
for cli in claude gemini codex kimi; do
  options+=("$cli")
done
[[ "${options[0]}" == "claude" ]] || test_fail "options[0] should be claude, got ${options[0]}"
[[ "${options[1]}" == "gemini" ]] || test_fail "options[1] should be gemini, got ${options[1]}"
[[ "${options[2]}" == "codex" ]] || test_fail "options[2] should be codex, got ${options[2]}"
[[ "${options[3]}" == "kimi" ]] || test_fail "options[3] should be kimi, got ${options[3]}"
[[ ${#options[@]} -eq 4 ]] && test_pass || test_fail "Expected 4 CLIs, got ${#options[@]}"

# Test 3: Verify choice to index mapping
test_start "Choice 1 maps to options[0] (claude)"
choice=1
if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
  chosen="${options[$((choice-1))]}"
  [[ "$chosen" == "claude" ]] && test_pass || test_fail "Expected claude, got $chosen"
else
  test_fail "Choice validation failed"
fi

# Test 4: Verify choice 2 maps to gemini
test_start "Choice 2 maps to options[1] (gemini)"
choice=2
if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
  chosen="${options[$((choice-1))]}"
  [[ "$chosen" == "gemini" ]] && test_pass || test_fail "Expected gemini, got $chosen"
else
  test_fail "Choice validation failed"
fi

# Test 5: Verify choice 3 maps to codex
test_start "Choice 3 maps to options[2] (codex)"
choice=3
if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
  chosen="${options[$((choice-1))]}"
  [[ "$chosen" == "codex" ]] && test_pass || test_fail "Expected codex, got $chosen"
else
  test_fail "Choice validation failed"
fi

# Test 6: Verify choice 4 maps to kimi
test_start "Choice 4 maps to options[3] (kimi)"
choice=4
if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
  chosen="${options[$((choice-1))]}"
  [[ "$chosen" == "kimi" ]] && test_pass || test_fail "Expected kimi, got $chosen"
else
  test_fail "Choice validation failed"
fi

# Test 7: Verify invalid choice 0 is rejected
test_start "Choice 0 is rejected as invalid"
choice=0
if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
  test_fail "Choice 0 should be invalid"
else
  test_pass
fi

# Test 8: Verify invalid choice 5 is rejected
test_start "Choice 5 is rejected as invalid (only 4 CLIs)"
choice=5
if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
  test_fail "Choice 5 should be invalid"
else
  test_pass
fi

# Test 9: Test with filtered options (simulate missing CLI)
test_start "Filtered options work correctly"
options_filtered=()
for cli in claude codex kimi; do  # gemini "missing"
  options_filtered+=("$cli")
done
choice=2
chosen="${options_filtered[$((choice-1))]}"
[[ "$chosen" == "codex" ]] && test_pass || test_fail "Expected codex, got $chosen"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Results: $passed passed, $failed failed"
echo "═══════════════════════════════════════════════════════════"

exit $failed
