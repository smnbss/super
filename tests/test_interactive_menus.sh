#!/usr/bin/env bash
# test_interactive_menus.sh — Run this in a REAL terminal to diagnose menu issues
# Usage: bash tests/test_interactive_menus.sh
set -euo pipefail

cd "$(dirname "$0")/.."
source lib/ui.sh
source lib/interactive.sh

echo "═══════════════════════════════════════════════════════════"
echo "  Interactive Menu Diagnostic"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Environment ──────────────────────────────────────────────
echo "--- Environment ---"
echo "  bash:     $(bash --version | head -1)"
echo "  gum:      $(command -v gum 2>/dev/null && gum --version || echo 'NOT INSTALLED')"
echo "  /dev/tty: $(test -r /dev/tty && test -w /dev/tty && echo 'OK' || echo 'NOT AVAILABLE')"
echo "  stdin tty: $(test -t 0 && echo 'YES' || echo 'NO')"
echo "  stderr tty: $(test -t 2 && echo 'YES' || echo 'NO')"
echo ""

# ── Test 1: gum choose with args (no pipe) ──────────────────
echo "--- Test 1: gum choose with positional args ---"
echo "  Pick any option and press enter..."
result=$(gum choose --height=6 --header "Test 1: gum args" -- "🟠 Claude Code" "🔵 Gemini CLI" "🟢 Codex CLI" "🟡 Kimi Code CLI" 2>/dev/null) || true
echo "  Result: [$result]"
if [[ -n "$result" ]]; then
  echo "  ✓ PASS"
else
  echo "  ✗ FAIL — gum returned empty"
fi
echo ""

# ── Test 2: gum choose via pipe ──────────────────────────────
echo "--- Test 2: gum choose via pipe ---"
echo "  Pick any option and press enter..."
result=$(printf '%s\n' "🟠 Claude Code" "🔵 Gemini CLI" "🟢 Codex CLI" "🟡 Kimi Code CLI" | gum choose --height=6 --header "Test 2: gum pipe" 2>/dev/null) || true
echo "  Result: [$result]"
if [[ -n "$result" ]]; then
  echo "  ✓ PASS"
else
  echo "  ✗ FAIL — gum returned empty"
fi
echo ""

# ── Test 3: gum inside nested $() ────────────────────────────
echo "--- Test 3: gum inside nested command substitution ---"
echo "  Pick any option and press enter..."
_test_nested() {
  local r
  r=$(gum choose --height=6 --header "Test 3: nested" -- "Option A" "Option B" "Option C")
  [[ -z "$r" ]] && return 1
  echo "picked"
  return 0
}
outer=$(  _test_nested  ) || true
echo "  Outer result: [$outer]"
if [[ "$outer" == "picked" ]]; then
  echo "  ✓ PASS"
else
  echo "  ✗ FAIL — nested gum failed"
fi
echo ""

# ── Test 4: ui_select_single (full path) ─────────────────────
echo "--- Test 4: ui_select_single (full stack) ---"
echo "  Pick any option and press enter..."
choice=$(ui_select_single "Test 4: ui_select_single" 0 "🟠 Claude Code" "🔵 Gemini CLI" "🟢 Codex CLI" "🟡 Kimi Code CLI") || true
echo "  Choice index: [$choice]"
if [[ -n "$choice" ]]; then
  echo "  ✓ PASS"
else
  echo "  ✗ FAIL — ui_select_single returned empty"
fi
echo ""

# ── Test 5: Simulate _pick_cli_and_launch flow ───────────────
echo "--- Test 5: Simulated _pick_cli_and_launch ---"
echo "  This mimics the exact code path that's failing."
echo "  Pick a CLI..."
options=("🟠 Claude Code" "🔵 Gemini CLI" "🟢 Codex CLI" "🟡 Kimi Code CLI")
cli_keys=(claude gemini codex kimi)

choice=$(ui_select_single "Which CLI would you like to use?" 0 "${options[@]}") || true
echo "  Choice: [$choice]"
if [[ -n "$choice" ]]; then
  echo "  Would launch: ${cli_keys[$choice]}"
  echo "  ✓ PASS"
else
  echo "  ✗ FAIL — this is the bug"
fi
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "  Done. Share the output above to diagnose the issue."
echo "═══════════════════════════════════════════════════════════"
