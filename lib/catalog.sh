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
# TOGGLE — flip enabled flag for an item
# ─────────────────────────────────────────────────────────────────────────────

_catalog_toggle() {
  local section="$1" name="$2" new_state="$3"
  local cfg; cfg="$(_super_find_config)"
  [[ -f "$cfg" ]] && _yaml_parse set "$cfg" "${section}.${name}.enabled" "$new_state"
}

# ─────────────────────────────────────────────────────────────────────────────
# INSTALL ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

_catalog_install_skill() {
  local name="$1" source="$2"
  local skills_dir="$HOME/.claude/skills"
  mkdir -p "$skills_dir"

  local dest="$skills_dir/$name"
  if [[ -d "$dest" ]]; then
    ui_muted "  $name already installed"
    return 0
  fi

  local parts
  IFS='/' read -ra parts <<< "$source"
  local owner="${parts[0]}" repo="${parts[1]}"
  local subpath=""
  [[ ${#parts[@]} -gt 2 ]] && subpath="${parts[*]:2}" && subpath="${subpath// //}"

  if [[ -z "$subpath" ]]; then
    git clone --depth 1 "https://github.com/${owner}/${repo}.git" "$dest" 2>/dev/null || {
      ui_warn "  Failed to clone $name"
      return 1
    }
  else
    local tmpdir; tmpdir=$(mktemp -d)
    git clone --depth 1 "https://github.com/${owner}/${repo}.git" "$tmpdir" 2>/dev/null || {
      ui_warn "  Failed to clone $name"; rm -rf "$tmpdir"; return 1
    }
    if [[ -d "$tmpdir/$subpath" ]]; then
      mv "$tmpdir/$subpath" "$dest"
    else
      ui_warn "  Path $subpath not found in ${owner}/${repo}"
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

  ui_success "  $name installed"
}

_catalog_install_plugin() {
  local name="$1" source="$2"
  local plugins_dir="$HOME/.claude/plugins"
  mkdir -p "$plugins_dir"

  local dest="$plugins_dir/$name"
  if [[ -d "$dest" ]]; then
    ui_muted "  $name already installed"
    return 0
  fi

  git clone --depth 1 "https://github.com/${source}.git" "$dest" 2>/dev/null || {
    ui_warn "  Failed to clone $name"; return 1
  }

  # Symlink skills and commands
  local claude_dir="$HOME/.claude"
  if [[ -d "$dest/skills" ]]; then
    mkdir -p "$claude_dir/skills"
    for skill in "$dest/skills"/*; do
      [[ -d "$skill" ]] || continue
      ln -sf "$skill" "$claude_dir/skills/$(basename "$skill")" 2>/dev/null || true
    done
  fi
  if [[ -d "$dest/commands" ]]; then
    mkdir -p "$claude_dir/commands"
    for cmd_file in "$dest/commands"/*; do
      ln -sf "$cmd_file" "$claude_dir/commands/$(basename "$cmd_file")" 2>/dev/null || true
    done
  fi

  ui_success "  $name installed"
}

_catalog_install_mcp() {
  local name="$1" command="$2" args_str="$3"
  local settings="$HOME/.claude/settings.json"
  [[ -f "$settings" ]] || echo '{}' > "$settings"

  # Check if already configured
  if python3 -c "
import json
with open('$settings') as f:
    d = json.load(f)
exit(0 if '$name' in d.get('mcpServers', {}) else 1)
" 2>/dev/null; then
    ui_muted "  $name already configured"
    return 0
  fi

  python3 -c "
import json
with open('$settings') as f:
    d = json.load(f)
d.setdefault('mcpServers', {})['$name'] = {'command': '$command', 'args': $args_str}
with open('$settings', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null || { ui_warn "  Failed to configure $name"; return 1; }

  ui_success "  $name configured"
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
  while IFS='|' read -r name command desc enabled; do
    [[ -z "$name" || "$enabled" != "true" ]] && continue
    local args_str
    args_str=$(_yaml_parse args "$cfg" mcps "$name")
    _catalog_install_mcp "$name" "$command" "$args_str" || true
  done <<< "$(catalog_mcps)"
}
