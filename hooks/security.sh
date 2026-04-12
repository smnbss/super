#!/usr/bin/env bash
# lib/security.sh - Security enforcement for super hooks

source "$SUPER_HOME/hooks/config.sh"

# Check if a path is outside the project
_super_is_outside_project() {
  local path="$1"
  local project_root="$(_super_find_root)"
  [[ "$path" != "$project_root"* ]] && [[ "$path" != "/tmp"* ]] && [[ "$path" != "$HOME/.super"* ]]
}

# Check if path is sensitive
_super_is_sensitive_path() {
  local path="$1"
  local sensitive_patterns=(
    "~/.ssh"
    "~/.aws"
    "~/.kube"
    "~/.docker"
    "~/.npmrc"
    "~/.pypirc"
    "~/.git-credentials"
    "/etc/passwd"
    "/etc/shadow"
    ".env"
    ".env.local"
  )
  for pattern in "${sensitive_patterns[@]}"; do
    [[ "$path" == *"$pattern"* ]] && return 0
  done
  return 1
}

# Check if a bash command is safe
_super_is_safe_bash() {
  local cmd="$1"
  # List of safe command patterns
  local safe_patterns=(
    "^ls "
    "^ls$"
    "^cd "
    "^pwd$"
    "^cat "
    "^head "
    "^tail "
    "^grep "
    "^find "
    "^git status"
    "^git log"
    "^git diff"
    "^git branch"
    "^git remote"
    "^git config --local"
    "^echo "
    "^mkdir -p "
    "^which "
    "^command -v"
  )
  for pattern in "${safe_patterns[@]}"; do
    if echo "$cmd" | grep -qE "$pattern"; then
      return 0
    fi
  done
  return 1
}

# Check if command has dangerous rm
_super_is_dangerous_rm() {
  local cmd="$1"
  # Match rm -rf / or rm -rf ~ or rm -rf /*
  if echo "$cmd" | grep -qE "rm\s+-(r|f|rf|fr).*(/\s*|\s+/|~|\$HOME)"; then
    return 0
  fi
  return 1
}

# Check if command makes external calls
_super_is_external_call() {
  local cmd="$1"
  local external_patterns=(
    "curl.*-X POST"
    "curl.*--data"
    "curl.*-d "
    "npm publish"
    "npm unpublish"
    "docker push"
    "docker rm"
    "kubectl apply"
    "kubectl delete"
    "gh pr create"
    "gh release create"
    "git push"
    "git push --force"
    "git push -f"
  )
  for pattern in "${external_patterns[@]}"; do
    if echo "$cmd" | grep -qE "$pattern"; then
      return 0
    fi
  done
  return 1
}

# Main security check function
# Returns: 0 = allow, 1 = block, 2 = ask
_super_security_check() {
  local tool="$1"
  local input="$2"
  local yolo="$(_super_yolo_mode)"
  
  # In yolo mode, still enforce hard blocks
  if [[ "$yolo" == "0" ]]; then
    # Check if tool is specifically allowed in yolo mode
    if ! _super_yolo_allowed "$tool"; then
      return 2  # ask
    fi
  fi
  
  case "$tool" in
    Bash)
      # Extract command from input JSON
      local cmd="$(echo "$input" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("command",""))' 2>/dev/null)"
      
      # Always block dangerous rm
      if _super_is_dangerous_rm "$cmd"; then
        local setting="$(_super_security_setting "dangerousRm")"
        [[ "$setting" == "block" ]] && return 1
        [[ "$setting" == "ask" ]] && return 2
      fi
      
      # Check for external calls
      if _super_is_external_call "$cmd"; then
        local setting="$(_super_security_setting "bashExternalCalls")"
        [[ "$setting" == "block" ]] && return 1
        [[ "$setting" == "ask" ]] && return 2
        [[ "$setting" == "allow" ]] && return 0
      fi
      
      # Auto-allow safe commands if configured
      if _super_is_safe_bash "$cmd"; then
        if _super_config_enabled "hooks.permissionRequest.autoAllowSafeBash"; then
          return 0
        fi
      fi
      ;;
      
    Write|Edit|MultiEdit)
      # Extract path from input
      local path="$(echo "$input" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("path",""))' 2>/dev/null)"
      
      # Check for writes outside project
      if _super_is_outside_project "$path"; then
        local setting="$(_super_security_setting "writesOutsideProject")"
        [[ "$setting" == "block" ]] && return 1
        [[ "$setting" == "ask" ]] && return 2
      fi
      
      # Check for sensitive paths
      if _super_is_sensitive_path "$path"; then
        local setting="$(_super_security_setting "sensitivePaths")"
        [[ "$setting" == "block" ]] && return 1
        [[ "$setting" == "ask" ]] && return 2
      fi
      
      # Check for .env access
      if [[ "$path" == *".env"* ]]; then
        local setting="$(_super_security_setting "envAccess")"
        [[ "$setting" == "block" ]] && return 1
        [[ "$setting" == "ask" ]] && return 2
      fi
      ;;
      
    Read|Glob|Grep)
      # Auto-allow reads if configured
      if _super_config_enabled "hooks.permissionRequest.autoAllowReads"; then
        return 0
      fi
      
      # Extract path/pattern from input
      local path="$(echo "$input" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("path",d.get("pattern","")))' 2>/dev/null)"
      
      # Check for sensitive paths
      if _super_is_sensitive_path "$path"; then
        local setting="$(_super_security_setting "sensitivePaths")"
        [[ "$setting" == "block" ]] && return 1
        [[ "$setting" == "ask" ]] && return 2
      fi
      ;;
  esac
  
  return 0  # allow by default
}

# Format security block reason
_super_security_block_reason() {
  local tool="$1"
  local input="$2"
  local reason="$3"
  
  echo ""
  echo "╔════════════════════════════════════════════════════════════════╗"
  echo "║  🔒 SUPER SECURITY BLOCK                                       ║"
  echo "╠════════════════════════════════════════════════════════════════╣"
  echo "║  Tool: $tool"
  echo "║  Reason: $reason"
  echo "╚════════════════════════════════════════════════════════════════╝"
  echo ""
  echo "This action was blocked by super security settings."
  echo "Edit super.config.yaml to change security settings."
}
