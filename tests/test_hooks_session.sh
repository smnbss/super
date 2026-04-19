#!/usr/bin/env bash
# tests/test_hooks_session.sh
#
# Parity check for hooks/session.sh: `session_inject_context` must behave
# identically to `sessionInjectContext` in lib/session.mjs — write to
# <root>/.super/session-context.md and never touch root CLAUDE.md /
# GEMINI.md / AGENTS.md.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPER_HOME="$(cd "$SCRIPT_DIR/.." && pwd)"
export SUPER_HOME

# shellcheck disable=SC1091
source "$SUPER_HOME/hooks/session.sh"

passed=0
failed=0
fail_reasons=()

_pass() { passed=$((passed + 1)); echo "  ✓ $1"; }
_fail() { failed=$((failed + 1)); echo "  ✗ $1: $2"; fail_reasons+=("$1"); }

# Per-test tempdir so state is isolated from the developer's real project.
tmp="$(mktemp -d -t super-hooks-session.XXXXXX)"
trap 'rm -rf "$tmp"' EXIT

export SUPER_PROJECT_DIR="$tmp"
mkdir -p "$tmp/.super/sessions"

# Fixture: a single active session. session_new depends on SUPER_SESSION_FILE
# being exported so later calls pick it up.
fixture_session="$tmp/.super/sessions/2026-01-01_000000.md"
cat > "$fixture_session" <<'EOF'
# Super Session: test

**Project:** test
**Started:** 2026-01-01 00:00:00
**Directory:** /tmp
**File:** 2026-01-01_000000.md

---

## 🟠 `[claude 00:00:00]` 👤 User

hello
EOF
export SUPER_SESSION_FILE="$fixture_session"

echo "Bash hooks/session.sh parity tests"
echo "=================================================="

# Pre-seed sentinels on root dotfiles so we can detect any accidental write.
for f in CLAUDE.md GEMINI.md AGENTS.md; do
  printf 'SENTINEL-%s\n' "$f" > "$tmp/$f"
done

# ─── Test: inject writes to .super/session-context.md ──────────────────────
session_inject_context claude
ctx="$tmp/.super/session-context.md"
if [[ -f "$ctx" ]]; then
  _pass "session_inject_context writes to .super/session-context.md"
else
  _fail "session_inject_context writes to .super/session-context.md" \
        "expected file at $ctx"
fi

# ─── Test: header/footer + CLI line ────────────────────────────────────────
if grep -q '<!-- super:session-context -->' "$ctx" \
   && grep -q '<!-- /super:session-context -->' "$ctx" \
   && grep -q 'CLI: `claude`' "$ctx"; then
  _pass "session_inject_context body includes header, footer, and CLI line"
else
  _fail "session_inject_context body includes header, footer, and CLI line" \
        "missing marker in $ctx"
fi

# ─── Test: root CLAUDE/GEMINI/AGENTS are not touched ───────────────────────
untouched=true
for f in CLAUDE.md GEMINI.md AGENTS.md; do
  expected="SENTINEL-${f}"
  if [[ "$(cat "$tmp/$f")" != "$expected" ]]; then
    untouched=false
    break
  fi
done
if $untouched; then
  _pass "session_inject_context never writes to root CLAUDE/GEMINI/AGENTS"
else
  _fail "session_inject_context never writes to root CLAUDE/GEMINI/AGENTS" \
        "a sentinel file was mutated"
fi

# ─── Test: repeat call overwrites (no duplication) ─────────────────────────
session_inject_context codex
header_count="$(grep -c '<!-- super:session-context -->' "$ctx")"
if [[ "$header_count" == "1" ]] && grep -q 'CLI: `codex`' "$ctx" \
   && ! grep -q 'CLI: `claude`' "$ctx"; then
  _pass "repeat inject overwrites rather than appends"
else
  _fail "repeat inject overwrites rather than appends" \
        "header count=$header_count, CLI lines unexpected"
fi

# ─── Test: clear removes .super/session-context.md ─────────────────────────
session_clear_injections
if [[ ! -f "$ctx" ]]; then
  _pass "session_clear_injections removes .super/session-context.md"
else
  _fail "session_clear_injections removes .super/session-context.md" \
        "file still exists"
fi

# ─── Test: clear is idempotent ─────────────────────────────────────────────
if session_clear_injections 2>/dev/null; then
  _pass "session_clear_injections is idempotent"
else
  _fail "session_clear_injections is idempotent" "non-zero exit"
fi

echo ""
echo "=================================================="
echo "Results: $passed passed, $failed failed"
exit "$failed"
