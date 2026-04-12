#!/usr/bin/env bash
# lib/catalog.sh — Read skills/plugins/MCPs from super.config.yaml
#
# Uses lib/yaml_parse.py (stdlib only, no PyYAML needed).

_yaml_parse() {
  python3 "$SUPER_HOME/lib/yaml_parse.py" "$@" 2>/dev/null || true
}

# ─────────────────────────────────────────────────────────────────────────────
# CATALOG READERS — return newline-separated "name|source|desc|enabled"
# ─────────────────────────────────────────────────────────────────────────────

catalog_skills() {
  local cfg; cfg="$(_super_find_config)"
  [[ -f "$cfg" ]] && _yaml_parse read "$cfg" skills
}

catalog_plugins() {
  local cfg; cfg="$(_super_find_config)"
  [[ -f "$cfg" ]] && _yaml_parse read "$cfg" plugins
}

catalog_mcps() {
  local cfg; cfg="$(_super_find_config)"
  [[ -f "$cfg" ]] && _yaml_parse read "$cfg" mcps
}

# ─────────────────────────────────────────────────────────────────────────────
# TOGGLE — comment/uncomment lines in config file
# ─────────────────────────────────────────────────────────────────────────────

_catalog_toggle() {
  local section="$1" name="$2"
  local cfg; cfg="$(_super_find_config)"
  [[ -f "$cfg" ]] || return 1
  
  # Check current state
  if _super_config_item_enabled "$section" "$name"; then
    # Currently enabled -> disable (comment out)
    _super_config_comment "$section" "$name"
    echo "disabled"
  else
    # Currently disabled -> enable (uncomment)
    _super_config_uncomment "$section" "$name"
    echo "enabled"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# INSTALL ACTIONS — per-CLI native mechanisms
# ─────────────────────────────────────────────────────────────────────────────

# Clone a skill repo to a destination, handling owner/repo/subpath sources.
# Runs setup script if present.
_clone_skill_source() {
  local name="$1" source="$2" dest="$3"

  if [[ -d "$dest" ]]; then
    ui_muted "    $name already installed"
    return 0
  fi

  local parts
  IFS='/' read -ra parts <<< "$source"
  local owner="${parts[0]}" repo="${parts[1]}"
  local subpath=""
  [[ ${#parts[@]} -gt 2 ]] && subpath="${parts[*]:2}" && subpath="${subpath// //}"

  if [[ -z "$subpath" ]]; then
    git clone --depth 1 "https://github.com/${owner}/${repo}.git" "$dest" 2>/dev/null || {
      ui_warn "    Failed to clone $name"; return 1
    }
  else
    local tmpdir; tmpdir=$(mktemp -d)
    git clone --depth 1 "https://github.com/${owner}/${repo}.git" "$tmpdir" 2>/dev/null || {
      ui_warn "    Failed to clone $name"; rm -rf "$tmpdir"; return 1
    }
    if [[ -d "$tmpdir/$subpath" ]]; then
      mv "$tmpdir/$subpath" "$dest"
    else
      ui_warn "    Path $subpath not found in ${owner}/${repo}"
      rm -rf "$tmpdir"; return 1
    fi
    rm -rf "$tmpdir"
  fi

  # Run setup if present
  if [[ -x "$dest/setup" ]]; then
    (cd "$dest" && ./setup) 2>/dev/null || true
  elif [[ -f "$dest/setup.sh" ]]; then
    (cd "$dest" && bash setup.sh) 2>/dev/null || true
  fi
  return 0
}

# Install skill — each CLI has a different discovery path
_catalog_install_skill_for_cli() {
  local name="$1" source="$2" cli="$3"
  local dest=""

  case "$cli" in
    claude)
      # Claude discovers skills from .agents/skills/ (project-level)
      local root; root="$(_super_find_root)"
      local skills_dir="$root/.agents/skills"
      mkdir -p "$skills_dir"
      dest="$skills_dir/$name"
      ;;
    gemini)
      # Gemini uses ~/.gemini/skills/ (symlinks)
      mkdir -p "$HOME/.gemini/skills"
      dest="$HOME/.gemini/skills/$name"
      ;;
    codex)
      # Codex uses ~/.codex/skills/
      mkdir -p "$HOME/.codex/skills"
      dest="$HOME/.codex/skills/$name"
      ;;
    kimi)
      # Kimi uses ~/.kimi/skills/ (copied)
      mkdir -p "$HOME/.kimi/skills"
      dest="$HOME/.kimi/skills/$name"
      ;;
    *) return 1 ;;
  esac

  ui_info "  [$cli]"
  _clone_skill_source "$name" "$source" "$dest" && \
    ui_success "    $name installed"
}

_catalog_install_skill() {
  local name="$1" source="$2"
  for cli in claude gemini codex kimi; do
    is_installed "$cli" && _catalog_install_skill_for_cli "$name" "$source" "$cli" || true
  done
}

# Install plugin — only Claude has a native plugin system
_catalog_install_plugin_for_cli() {
  local name="$1" source="$2" cli="$3"

  case "$cli" in
    claude)
      # Delegate to Claude's native plugin system
      if ! command -v claude >/dev/null 2>&1; then
        ui_warn "  [$cli] claude command not found — cannot install plugin"
        return 1
      fi
      # Check if already installed via installed_plugins.json
      local registry="$HOME/.claude/plugins/installed_plugins.json"
      if [[ -f "$registry" ]] && python3 -c "
import json, sys
with open('$registry') as f:
    d = json.load(f)
# source format: marketplace/plugin — check if any key matches
for k in d.get('plugins', {}):
    if '$name' in k or '$source' in k:
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
        ui_muted "  [$cli] $name already installed"
        return 0
      fi
      ui_info "  [$cli] Installing via: claude plugins install $source"
      claude plugins install "$source" 2>/dev/null || {
        ui_warn "  [$cli] Failed — run manually: claude plugins install $source"
        return 1
      }
      ui_success "  [$cli] $name installed"
      ;;
    *)
      # No native plugin system for Gemini, Codex, Kimi
      ui_muted "  [$cli] No plugin system — $name listed as reference only"
      ;;
  esac
}

_catalog_install_plugin() {
  local name="$1" source="$2"
  for cli in claude gemini codex kimi; do
    is_installed "$cli" && _catalog_install_plugin_for_cli "$name" "$source" "$cli" || true
  done
}

# Install MCP — each CLI has a different config file, format, and path
_catalog_install_mcp_for_cli() {
  local name="$1" cli="$2"
  local cfg; cfg="$(_super_find_config)"
  [[ -f "$cfg" ]] || return 1

  # Get full MCP config as JSON from the YAML
  local item_json
  item_json=$(_yaml_parse item "$cfg" mcps "$name") || return 1
  [[ -z "$item_json" || "$item_json" == "{}" ]] && return 1

  case "$cli" in
    claude)  _install_mcp_claude  "$name" "$item_json" ;;
    gemini)  _install_mcp_gemini  "$name" "$item_json" ;;
    codex)   _install_mcp_codex   "$name" "$item_json" ;;
    kimi)    _install_mcp_kimi    "$name" "$item_json" ;;
    *) return 1 ;;
  esac
}

# Claude: project-level .claude/settings.local.json, dict format
_install_mcp_claude() {
  local name="$1" item_json="$2"
  local root; root="$(_super_find_root)"
  local settings="$root/.claude/settings.local.json"
  mkdir -p "$root/.claude"
  [[ -f "$settings" ]] || echo '{}' > "$settings"

  python3 -c "
import json, sys
item = json.loads('''$item_json''')
with open('$settings') as f:
    d = json.load(f)
servers = d.setdefault('mcpServers', {})
if '$name' in servers:
    print('already configured', file=sys.stderr)
    sys.exit(2)
# Build Claude-format entry
entry = {}
if item.get('type') == 'http' or 'url' in item:
    entry['url'] = item['url']
else:
    entry['command'] = item.get('command', '')
    if 'args' in item:
        entry['args'] = item['args'] if isinstance(item['args'], list) else json.loads(item['args'])
if 'env' in item and isinstance(item['env'], dict):
    entry['env'] = item['env']
servers['$name'] = entry
with open('$settings', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null
  local rc=$?
  if [[ $rc -eq 2 ]]; then
    ui_muted "  [claude] $name already configured"
  elif [[ $rc -eq 0 ]]; then
    ui_success "  [claude] $name configured"
  else
    ui_warn "  [claude] Failed to configure $name"
  fi
}

# Gemini: project-level .gemini/settings.json, dict format
_install_mcp_gemini() {
  local name="$1" item_json="$2"
  local root; root="$(_super_find_root)"
  local settings="$root/.gemini/settings.json"
  mkdir -p "$root/.gemini"
  [[ -f "$settings" ]] || echo '{}' > "$settings"

  python3 -c "
import json, sys
item = json.loads('''$item_json''')
with open('$settings') as f:
    d = json.load(f)
servers = d.setdefault('mcpServers', {})
if '$name' in servers:
    print('already configured', file=sys.stderr)
    sys.exit(2)
entry = {}
if item.get('type') == 'http' or 'url' in item:
    entry['url'] = item['url']
else:
    entry['command'] = item.get('command', '')
    if 'args' in item:
        entry['args'] = item['args'] if isinstance(item['args'], list) else json.loads(item['args'])
if 'env' in item and isinstance(item['env'], dict):
    entry['env'] = item['env']
servers['$name'] = entry
with open('$settings', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null
  local rc=$?
  if [[ $rc -eq 2 ]]; then
    ui_muted "  [gemini] $name already configured"
  elif [[ $rc -eq 0 ]]; then
    ui_success "  [gemini] $name configured"
  else
    ui_warn "  [gemini] Failed to configure $name"
  fi
}

# Codex: project-level .codex/config.json, ARRAY format [{name, type, url/command, args}]
_install_mcp_codex() {
  local name="$1" item_json="$2"
  local root; root="$(_super_find_root)"
  local settings="$root/.codex/config.json"
  mkdir -p "$root/.codex"
  [[ -f "$settings" ]] || echo '{}' > "$settings"

  python3 -c "
import json, sys
item = json.loads('''$item_json''')
with open('$settings') as f:
    d = json.load(f)
servers = d.setdefault('mcpServers', [])
# Check if already configured (array — search by name)
for s in servers:
    if s.get('name') == '$name':
        print('already configured', file=sys.stderr)
        sys.exit(2)
# Build Codex-format entry (array element with name + type)
entry = {'name': '$name'}
if item.get('type') == 'http' or 'url' in item:
    entry['type'] = 'http'
    entry['url'] = item['url']
    if 'auth' in item:
        entry['auth'] = item['auth'] if isinstance(item['auth'], dict) else {'type': item['auth']}
else:
    entry['type'] = 'stdio'
    entry['command'] = item.get('command', '')
    if 'args' in item:
        entry['args'] = item['args'] if isinstance(item['args'], list) else json.loads(item['args'])
if 'env' in item and isinstance(item['env'], dict):
    entry['env'] = item['env']
servers.append(entry)
with open('$settings', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null
  local rc=$?
  if [[ $rc -eq 2 ]]; then
    ui_muted "  [codex] $name already configured"
  elif [[ $rc -eq 0 ]]; then
    ui_success "  [codex] $name configured"
  else
    ui_warn "  [codex] Failed to configure $name"
  fi
}

# Kimi: project-level .kimi/mcp.json, dict format with transport field
_install_mcp_kimi() {
  local name="$1" item_json="$2"
  local root; root="$(_super_find_root)"
  local settings="$root/.kimi/mcp.json"
  mkdir -p "$root/.kimi"
  [[ -f "$settings" ]] || echo '{"mcpServers":{}}' > "$settings"

  python3 -c "
import json, sys
item = json.loads('''$item_json''')
with open('$settings') as f:
    d = json.load(f)
servers = d.setdefault('mcpServers', {})
if '$name' in servers:
    print('already configured', file=sys.stderr)
    sys.exit(2)
# Build Kimi-format entry (uses 'transport' field)
entry = {}
if item.get('type') == 'http' or 'url' in item:
    entry['url'] = item['url']
    entry['transport'] = 'http'
    if 'auth' in item:
        entry['auth'] = item['auth']
else:
    entry['command'] = item.get('command', '')
    if 'args' in item:
        entry['args'] = item['args'] if isinstance(item['args'], list) else json.loads(item['args'])
if 'env' in item and isinstance(item['env'], dict):
    entry['env'] = item['env']
servers['$name'] = entry
with open('$settings', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null
  local rc=$?
  if [[ $rc -eq 2 ]]; then
    ui_muted "  [kimi] $name already configured"
  elif [[ $rc -eq 0 ]]; then
    ui_success "  [kimi] $name configured"
  else
    ui_warn "  [kimi] Failed to configure $name"
  fi
}

_catalog_install_mcp() {
  local name="$1"
  for cli in claude gemini codex kimi; do
    is_installed "$cli" && _catalog_install_mcp_for_cli "$name" "$cli" || true
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# BATCH INSTALL
# ─────────────────────────────────────────────────────────────────────────────

catalog_install_enabled() {
  local cfg; cfg="$(_super_find_config)"
  [[ -f "$cfg" ]] || return

  ui_brand "Installing enabled skills..."
  ui_spacer
  while IFS='|' read -r name source desc enabled; do
    [[ -z "$name" || "$enabled" != "true" ]] && continue
    _catalog_install_skill "$name" "$source" || true
  done <<< "$(catalog_skills)"

  ui_spacer
  ui_brand "Installing enabled plugins..."
  ui_spacer
  while IFS='|' read -r name source desc enabled; do
    [[ -z "$name" || "$enabled" != "true" ]] && continue
    _catalog_install_plugin "$name" "$source" || true
  done <<< "$(catalog_plugins)"

  ui_spacer
  ui_brand "Configuring enabled MCPs..."
  ui_spacer
  while IFS='|' read -r name _command desc enabled; do
    [[ -z "$name" || "$enabled" != "true" ]] && continue
    _catalog_install_mcp "$name" || true
  done <<< "$(catalog_mcps)"
}

# ─────────────────────────────────────────────────────────────────────────────
# UNINSTALL ACTIONS — across all active CLIs
# ─────────────────────────────────────────────────────────────────────────────

_catalog_uninstall_skill() {
  local name="$1"
  local any_removed=0

  for cli in claude gemini codex kimi; do
    local dest=""
    case "$cli" in
      claude)
        local root; root="$(_super_find_root)"
        dest="$root/.agents/skills/$name"
        ;;
      gemini) dest="$HOME/.gemini/skills/$name" ;;
      codex)  dest="$HOME/.codex/skills/$name" ;;
      kimi)   dest="$HOME/.kimi/skills/$name" ;;
    esac

    if [[ -d "$dest" || -L "$dest" ]]; then
      rm -rf "$dest"
      ui_success "  [$cli] $name uninstalled"
      any_removed=1
    fi
  done

  [[ $any_removed -eq 0 ]] && ui_muted "  $name not found"
}

_catalog_uninstall_plugin() {
  local name="$1"

  # Only Claude has a native plugin system
  if command -v claude >/dev/null 2>&1; then
    ui_info "  [claude] To uninstall: claude plugins uninstall $name"
  fi
  ui_muted "  Plugin uninstall is manual — use each CLI's native commands"
}

_catalog_uninstall_mcp() {
  local name="$1"
  local any_removed=0

  # Claude: project-level .claude/settings.local.json
  local root; root="$(_super_find_root)"
  local claude_settings="$root/.claude/settings.local.json"
  if [[ -f "$claude_settings" ]]; then
    if python3 -c "
import json
with open('$claude_settings') as f:
    d = json.load(f)
if '$name' in d.get('mcpServers', {}):
    del d['mcpServers']['$name']
    with open('$claude_settings', 'w') as f:
        json.dump(d, f, indent=2)
    exit(0)
exit(1)
" 2>/dev/null; then
      ui_success "  [claude] $name removed"
      any_removed=1
    fi
  fi

  # Gemini: project-level .gemini/settings.json (dict)
  local gemini_settings="$root/.gemini/settings.json"
  if [[ -f "$gemini_settings" ]]; then
    if python3 -c "
import json
with open('$gemini_settings') as f:
    d = json.load(f)
if '$name' in d.get('mcpServers', {}):
    del d['mcpServers']['$name']
    with open('$gemini_settings', 'w') as f:
        json.dump(d, f, indent=2)
    exit(0)
exit(1)
" 2>/dev/null; then
      ui_success "  [gemini] $name removed"
      any_removed=1
    fi
  fi

  # Codex: project-level .codex/config.json (array)
  local codex_settings="$root/.codex/config.json"
  if [[ -f "$codex_settings" ]]; then
    if python3 -c "
import json
with open('$codex_settings') as f:
    d = json.load(f)
servers = d.get('mcpServers', [])
new = [s for s in servers if s.get('name') != '$name']
if len(new) < len(servers):
    d['mcpServers'] = new
    with open('$codex_settings', 'w') as f:
        json.dump(d, f, indent=2)
    exit(0)
exit(1)
" 2>/dev/null; then
      ui_success "  [codex] $name removed"
      any_removed=1
    fi
  fi

  # Kimi: project-level .kimi/mcp.json (dict)
  local kimi_settings="$root/.kimi/mcp.json"
  if [[ -f "$kimi_settings" ]]; then
    if python3 -c "
import json
with open('$kimi_settings') as f:
    d = json.load(f)
if '$name' in d.get('mcpServers', {}):
    del d['mcpServers']['$name']
    with open('$kimi_settings', 'w') as f:
        json.dump(d, f, indent=2)
    exit(0)
exit(1)
" 2>/dev/null; then
      ui_success "  [kimi] $name removed"
      any_removed=1
    fi
  fi

  [[ $any_removed -eq 0 ]] && ui_muted "  $name not configured"
}
