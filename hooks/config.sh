#!/usr/bin/env bash
# lib/config.sh - Configuration management for super

SUPER_CONFIG_FILE="${SUPER_CONFIG_FILE:-super.config.yaml}"

# Project root discovery (also defined in session.sh — duplicated here so
# config.sh can be sourced standalone by hooks without session.sh)
if ! declare -f _super_find_root >/dev/null 2>&1; then
  _super_find_root() {
    local dir="${SUPER_PROJECT_DIR:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
      if [[ -d "$dir/.super" ]]; then echo "$dir"; return; fi
      if [[ -d "$dir/.git" ]]; then echo "$dir"; return; fi
      dir="$(dirname "$dir")"
    done
    echo "$(pwd)"
  }
fi

# Find config file (prefer .super/super.config.yaml, fall back to project root)
_super_find_config() {
  local root; root="$(_super_find_root)"
  
  # First priority: .super/super.config.yaml (new standard location)
  if [[ -f "$root/.super/$SUPER_CONFIG_FILE" ]]; then
    echo "$root/.super/$SUPER_CONFIG_FILE"
    return 0
  fi
  
  # Second priority: project root super.config.yaml (legacy)
  if [[ -f "$root/$SUPER_CONFIG_FILE" ]]; then
    echo "$root/$SUPER_CONFIG_FILE"
    return 0
  fi
  
  # Third priority: search up from cwd (legacy behavior)
  local dir="$(pwd)"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.super/$SUPER_CONFIG_FILE" ]]; then
      echo "$dir/.super/$SUPER_CONFIG_FILE"
      return 0
    fi
    if [[ -f "$dir/$SUPER_CONFIG_FILE" ]]; then
      echo "$dir/$SUPER_CONFIG_FILE"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  
  # Fall back to home directory config
  if [[ -f "$HOME/.super/$SUPER_CONFIG_FILE" ]]; then
    echo "$HOME/.super/$SUPER_CONFIG_FILE"
    return 0
  fi
  
  echo ""
}

# Get config value using yq or python
default_config() {
  # If the template exists in SUPER_HOME, use it
  if [[ -f "$SUPER_HOME/super.config.yaml" ]]; then
    cat "$SUPER_HOME/super.config.yaml"
  else
    cat << 'EOF'
version: "1.0"
security:
  yoloMode: false
  writesOutsideProject: ask
  readsOutsideProject: allow
  bashExternalCalls: ask
  changeOwner: block
  githubCommands: allow
  dangerousRm: block
  envAccess: block
  sensitivePaths: block
session:
  autoName: true
  sessionLog: true
  transcriptLog: true
  cleanupOnStart: true
  maxAgeDays: 7
  injectContext: true
skills: {}
plugins: {}
mcps: {}
project:
  lintCommand: ""
  typeCheckCommand: ""
hooks:
  preToolUse:
    enabled: true
  permissionRequest:
    enabled: true
    autoAllowReads: true
    autoAllowSafeBash: true
  sessionStart:
    enabled: true
  sessionEnd:
    enabled: true
    saveTranscript: true
  stop:
    enabled: true
    saveTranscript: true
EOF
  fi
}

# Get config value (path like "security.yoloMode")
_super_config_get() {
  local path="$1"
  local config_file="$(_super_find_config)"

  if [[ -z "$config_file" || ! -f "$config_file" ]]; then
    # No config file — return empty
    return
  fi

  python3 "$SUPER_HOME/lib/yaml_parse.py" get "$config_file" "$path" 2>/dev/null || true
}

# Check if a feature is enabled
_super_config_enabled() {
  local path="$1"
  local value="$(_super_config_get "$path")"
  [[ "$value" == "true" ]] || [[ "$value" == "True" ]] || [[ "$value" == "yes" ]]
}

# Get security setting (block/allow/ask)
_super_security_setting() {
  local key="$1"
  _super_config_get "security.${key}"
}

# Check if yolo mode is on
_super_yolo_mode() {
  _super_config_enabled "security.yoloMode"
}

# Check if a tool is yolo-allowed
_super_yolo_allowed() {
  local tool="$1"
  local allowed="$(_super_config_get "security.yoloAllowedTools")"
  [[ -z "$allowed" ]] && return 0  # Empty means all allowed
  echo "$allowed" | grep -q "\"$tool\"" 2>/dev/null || return 1
}

# Get project validators
_super_lint_command() {
  _super_config_get "project.lintCommand"
}

_super_typecheck_command() {
  _super_config_get "project.typeCheckCommand"
}

# Session settings
_super_session_max_age() {
  _super_config_get "session.maxAgeDays"
}

_super_session_cleanup() {
  _super_config_enabled "session.cleanupOnStart"
}

# Initialize config file in .super directory
_super_config_init() {
  local root; root="$(_super_find_root)"
  local super_dir="$root/.super"
  local config_file="$super_dir/$SUPER_CONFIG_FILE"
  
  mkdir -p "$super_dir"
  
  if [[ -f "$config_file" ]]; then
    echo "Config already exists at $config_file"
    return 1
  fi
  default_config > "$config_file"
  echo "$config_file"
}

# Set config value (path like "security.yoloMode", value like "true")
_super_config_set() {
  local path="$1"
  local value="$2"
  local config_file="$(_super_find_config)"
  
  # Create config if it doesn't exist (in .super directory)
  if [[ -z "$config_file" ]]; then
    config_file="$(_super_config_init)"
  fi
  
  python3 "$SUPER_HOME/lib/yaml_parse.py" set "$config_file" "$path" "$value" 2>/dev/null || true
}

# Comment out a config block (for disabling skills/plugins/MCPs)
# Comments out from "  name:" until the next item at same indent or section end
_super_config_comment() {
  local section="$1"
  local name="$2"
  local config_file="$(_super_find_config)"
  [[ -f "$config_file" ]] || return 1
  
  # Use awk to comment out the block starting with "  name:" under the section
  awk -v sec="${section}:" -v n="  ${name}:" '
    $0 ~ sec { in_section=1 }
    in_section && $0 ~ n { in_block=1 }
    in_block && /^  [a-zA-Z0-9_-]+:/ && $0 !~ n { in_block=0 }  # Next item at same level
    in_block && /^[a-zA-Z0-9_-]+:/ && $0 !~ sec { in_block=0; in_section=0 }  # New section
    in_block { print "#" $0; next }
    { print }
  ' "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
}

# Uncomment a config block (for enabling skills/plugins/MCPs)
_super_config_uncomment() {
  local section="$1"
  local name="$2"
  local config_file="$(_super_find_config)"
  [[ -f "$config_file" ]] || return 1
  
  # Use awk to uncomment the block starting with "#  name:" under the section
  awk -v sec="${section}:" -v n="  ${name}:" '
    $0 ~ sec { in_section=1 }
    in_section && $0 ~ "^#" n { in_block=1; sub(/^#/, "", $0); print; next }
    in_block && /^#?  [a-zA-Z0-9_-]+:/ { in_block=0 }  # Next item at same level
    in_block && /^#?[a-zA-Z0-9_-]+:/ && $0 !~ sec { in_block=0; in_section=0 }  # New section
    in_block { sub(/^#/, "", $0); print; next }
    { print }
  ' "$config_file" > "${config_file}.tmp" && mv "${config_file}.tmp" "$config_file"
}

# Check if a skill/plugin/MCP is enabled (not commented out)
_super_config_item_enabled() {
  local section="$1"
  local name="$2"
  local config_file="$(_super_find_config)"
  [[ -f "$config_file" ]] || return 1
  
  # Check if the item line is NOT commented out
  grep -E "^  ${name}:" "$config_file" >/dev/null 2>&1
}
