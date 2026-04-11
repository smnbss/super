#!/usr/bin/env bash
# Integration test - simulate super menu flow

set -uo pipefail

SUPER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; RESET='\033[0m'

echo "═══════════════════════════════════════════════════════════"
echo "  Super Integration Test - Menu Flow Simulation"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Simulate _pick_cli_and_launch logic
declare -A CLI_CMD=( [claude]="claude" [gemini]="gemini" [codex]="codex" [kimi]="kimi" )
declare -A CLI_ICON=( [claude]="🟠" [gemini]="🔵" [codex]="🟢" [kimi]="🟡" )
declare -A CLI_LABEL=( [claude]="Claude Code" [gemini]="Gemini CLI" [codex]="Codex CLI" [kimi]="Kimi Code CLI" )
is_installed() { command -v "${CLI_CMD[$1]}" &>/dev/null; }

echo -e "${BLUE}Step 1: User runs 'super' and sees main menu${RESET}"
echo ""
echo "What would you like to do?"
echo ""
echo "  [1]  🆕  Start a new session"
echo "  [2]  ↩️   Resume a previous session"
echo ""

echo -e "${BLUE}Step 2: User enters '1' for new session${RESET}"
main_choice="1"
echo "  User input: $main_choice"
echo ""

if [[ "$main_choice" == "1" ]]; then
  echo -e "${BLUE}Step 3: _pick_cli_and_launch is called${RESET}"
  echo ""
  echo "Which CLI would you like to use?"
  echo ""
  
  # Build options array exactly like super does
  options=()
  i=1
  for cli in claude gemini codex kimi; do
    if is_installed "$cli"; then
      options+=("$cli")
      echo -e "  [$i]  ${CLI_ICON[$cli]}  ${CLI_LABEL[$cli]}"
      ((i++))
    fi
  done
  echo ""
  echo "  (options array: [${options[*]}])"
  echo ""
  
  echo -e "${BLUE}Step 4: User enters '1' for Claude${RESET}"
  cli_choice="1"
  echo "  User input: $cli_choice"
  echo ""
  
  # Validate and map choice
  if [[ "$cli_choice" =~ ^[0-9]+$ ]] && (( cli_choice >= 1 && cli_choice <= ${#options[@]} )); then
    chosen="${options[$((cli_choice-1))]}"
    echo -e "${BLUE}Step 5: Mapping choice to CLI${RESET}"
    echo "  cli_choice = $cli_choice"
    echo "  array index = $((cli_choice-1))"
    echo "  options[$((cli_choice-1))] = ${options[$((cli_choice-1))]}"
    echo "  chosen = $chosen"
    echo ""
    
    if [[ "$chosen" == "claude" ]]; then
      echo -e "${GREEN}✓ CORRECT: User picked 1 and got Claude${RESET}"
      exit 0
    else
      echo -e "${RED}✗ BUG: User picked 1 but got $chosen instead of claude!${RESET}"
      echo ""
      echo "Debugging:"
      echo "  options[0] = ${options[0]}"
      echo "  options[1] = ${options[1]}"
      echo "  is_installed claude = $(is_installed claude && echo 'true' || echo 'false')"
      exit 1
    fi
  else
    echo -e "${RED}✗ Invalid choice: $cli_choice${RESET}"
    exit 1
  fi
else
  echo "Resume flow not tested in this integration test"
fi
