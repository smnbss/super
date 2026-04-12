#!/usr/bin/env bash
# lib/validators.sh - Project validators (lint/typecheck) for super

source "$SUPER_HOME/lib/config.sh"

# Run lint command if configured
_super_run_lint() {
  local lint_cmd="$(_super_lint_command)"
  [[ -z "$lint_cmd" ]] && return 0
  
  echo ""
  echo "🔍 Running lint..."
  if eval "$lint_cmd"; then
    echo "✓ Lint passed"
    return 0
  else
    echo "✗ Lint failed"
    return 1
  fi
}

# Run typecheck command if configured
_super_run_typecheck() {
  local typecheck_cmd="$(_super_typecheck_command)"
  [[ -z "$typecheck_cmd" ]] && return 0
  
  echo ""
  echo "🔍 Running type check..."
  if eval "$typecheck_cmd"; then
    echo "✓ Type check passed"
    return 0
  else
    echo "✗ Type check failed"
    return 1
  fi
}

# Run all validators
_super_run_validators() {
  local lint_ok=0
  local typecheck_ok=0
  
  _super_run_lint || lint_ok=$?

  _super_run_typecheck || typecheck_ok=$?
  
  if [[ $lint_ok -eq 0 && $typecheck_ok -eq 0 ]]; then
    return 0
  else
    return 1
  fi
}

# Check if validators should run after a file write
_super_should_validate() {
  local tool="$1"
  [[ "$tool" == "Write" || "$tool" == "Edit" || "$tool" == "MultiEdit" ]]
}
