#!/usr/bin/env bash
# lib/config.sh - Configuration management for super

SUPER_CONFIG_FILE="${SUPER_CONFIG_FILE:-super.config.yaml}"

# Find config file (search up from cwd)
_super_find_config() {
  local dir="$(pwd)"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/$SUPER_CONFIG_FILE" ]]; then
      echo "$dir/$SUPER_CONFIG_FILE"
      return 0
    fi
    if [[ -d "$dir/.super" ]]; then
      # Stop at super project root if no config found
      break
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
project:
  lintCommand: ""
  typeCheckCommand: ""
  autoLintOnSave: false
hooks:
  preToolUse:
    enabled: true
    enforceSecurity: true
  permissionRequest:
    enabled: true
    autoAllowReads: true
    autoAllowSafeBash: true
  userPromptSubmit:
    enabled: true
    logPrompts: true
  postToolUse:
    enabled: true
    runValidators: true
  sessionStart:
    enabled: true
  sessionEnd:
    enabled: true
    saveTranscript: true
  stop:
    enabled: true
    saveTranscript: true
EOF
}

# Get config value (path like "security.yoloMode")
_super_config_get() {
  local path="$1"
  local config_file="$(_super_find_config)"
  
  if [[ -z "$config_file" ]]; then
    # Use defaults
    default_config | python3 -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d.get('$path', ''))" 2>/dev/null || true
    return
  fi
  
  if command -v yq &>/dev/null; then
    yq -r ".${path}" "$config_file" 2>/dev/null || true
  else
    python3 -c "import yaml; d=yaml.safe_load(open('$config_file')); print(d.get('$path', ''))" 2>/dev/null || true
  fi
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

# Initialize config file in current directory
_super_config_init() {
  local config_file="$(pwd)/$SUPER_CONFIG_FILE"
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
  
  # Create config if it doesn't exist
  if [[ -z "$config_file" ]]; then
    config_file="$(pwd)/$SUPER_CONFIG_FILE"
    default_config > "$config_file"
  fi
  
  if command -v yq &>/dev/null; then
    yq -i ".${path} = ${value}" "$config_file" 2>/dev/null || \
    yq -i ".${path} = \"${value}\"" "$config_file" 2>/dev/null
  else
    # Fallback to Python
    python3 -c "
import yaml
import sys

with open('$config_file') as f:
    d = yaml.safe_load(f)

# Set nested value
keys = '$path'.split('.')
current = d
for key in keys[:-1]:
    if key not in current:
        current[key] = {}
    current = current[key]

# Try to parse as boolean/number, else string
val = '$value'
if val.lower() == 'true':
    val = True
elif val.lower() == 'false':
    val = False
elif val.isdigit():
    val = int(val)

current[keys[-1]] = val

with open('$config_file', 'w') as f:
    yaml.dump(d, f, default_flow_style=False, sort_keys=False)
" 2>/dev/null
  fi
}
