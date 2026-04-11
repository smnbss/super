#!/usr/bin/env bash
# super/lib/fzf.sh
# Fuzzy finder integration for super CLI
# Provides graceful fallback when fzf is not installed
#
# Usage: source "$SUPER_HOME/lib/fzf.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

FZF_AVAILABLE=false
if command -v fzf &>/dev/null; then
  FZF_AVAILABLE=true
fi

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION PICKER (fzf version)
# ═══════════════════════════════════════════════════════════════════════════════

_fzf_pick_session() {
  local sessions_dir; sessions_dir="$(_super_sessions_dir)"
  [[ -d "$sessions_dir" ]] || { echo ""; return; }
  
  local active; active="$(_super_session_file)"
  local active_name=""
  [[ -n "$active" ]] && active_name="$(basename "$active")"
  
  # Build list for fzf with preview
  local list=""
  local i=1
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    
    local name turns cli_icon age
    name="$(basename "$f" .md)"
    turns="$(grep -c '^## ' "$f" 2>/dev/null || echo 0)"
    
    # Extract CLI from first turn
    local first_cli
    first_cli="$(grep -m1 '^## ' "$f" 2>/dev/null | grep -oE '\[([🔵🟠🟢🟡])' | head -1)"
    
    # Calculate age
    local mtime age_str
    mtime="$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null)"
    local now; now=$(date +%s)
    local age_hours=$(((now - mtime) / 3600))
    
    if ((age_hours < 1)); then
      age_str="just now"
    elif ((age_hours < 24)); then
      age_str="${age_hours}h ago"
    else
      local age_days=$((age_hours / 24))
      age_str="${age_days}d ago"
    fi
    
    # Mark active
    local marker=""
    [[ "$f" == "$active" ]] && marker=" ◀ ACTIVE"
    
    # Format for fzf
    printf -v line "%s|%s|%s turns|%s%s" "$name" "$age_str" "$turns" "$age_str" "$marker"
    list="${list}${line}\n"
    
    ((i++))
  done < <(ls -t "$sessions_dir"/*.md 2>/dev/null)
  
  [[ -z "$list" ]] && { echo ""; return; }
  
  # Preview function shows last 3 turns
  local preview_cmd="echo {1}.md | xargs -I {} tail -50 '$sessions_dir/{}' | grep -A5 '^## ' | head -30"
  
  local selected
  selected="$(echo -e "$list" | fzf \
    --header="Select session (ctrl-n for new, ctrl-r for recent first)" \
    --preview="$preview_cmd" \
    --preview-window=right:50%:wrap \
    --bind='ctrl-n:abort' \
    --bind='ctrl-r:toggle-sort' \
    --delimiter='|' \
    --with-nth=1,2,3 \
    --tac \
    --height=60% \
    --border=rounded \
    --prompt="Session > " \
    2>/dev/null)"
  
  # Handle abort (ctrl-n = new session)
  if [[ -z "$selected" ]]; then
    echo "NEW"
    return
  fi
  
  # Extract filename from selection
  local filename
  filename="$(echo "$selected" | cut -d'|' -f1).md"
  echo "$sessions_dir/$filename"
}

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION PICKER (fallback version)
# ═══════════════════════════════════════════════════════════════════════════════

_fallback_pick_session() {
  # Use the existing session_pick from session.sh
  session_pick
}

# ═══════════════════════════════════════════════════════════════════════════════
# CLI SELECTOR (fzf version)
# ═══════════════════════════════════════════════════════════════════════════════

_fzf_pick_cli() {
  local options=()
  local icons=()
  local labels=()
  
  for cli in claude gemini codex kimi; do
    if is_installed "$cli"; then
      options+=("$cli")
      labels+=("${CLI_LABEL[$cli]}")
      icons+=("${CLI_ICON[$cli]}")
    fi
  done
  
  [[ ${#options[@]} -eq 0 ]] && { echo ""; return; }
  [[ ${#options[@]} -eq 1 ]] && { echo "${options[0]}"; return; }
  
  # Build fzf list
  local list=""
  for i in "${!options[@]}"; do
    printf -v line "%s|%s|%s" "${options[$i]}" "${icons[$i]}" "${labels[$i]}"
    list="${list}${line}\n"
  done
  
  local selected
  selected="$(echo -e "$list" | fzf \
    --header="Select CLI to launch" \
    --delimiter='|' \
    --with-nth=2,3 \
    --height=40% \
    --border=rounded \
    --prompt="CLI > " \
    2>/dev/null)"
  
  [[ -z "$selected" ]] && { echo ""; return; }
  
  echo "$selected" | cut -d'|' -f1
}

# ═══════════════════════════════════════════════════════════════════════════════
# CLI SELECTOR (fallback version)
# ═══════════════════════════════════════════════════════════════════════════════

_fallback_pick_cli() {
  echo ""
  echo -e "${BOLD}Which CLI would you like to use?${RESET}"
  echo ""
  
  local options=() i=1
  for cli in claude gemini codex kimi; do
    if is_installed "$cli"; then
      options+=("$cli")
      echo -e "  ${BOLD}[$i]${RESET}  ${CLI_ICON[$cli]}  ${CLI_LABEL[$cli]}"
      ((i++))
    fi
  done
  
  echo ""
  ui_prompt "Choice (or q):"
  read -r choice
  
  [[ "$choice" == "q" || -z "$choice" ]] && { echo "QUIT"; return; }
  
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
    echo "${options[$((choice-1))]}"
  else
    echo ""
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED API
# ═══════════════════════════════════════════════════════════════════════════════

# Pick session with automatic fallback
fzf_pick_session() {
  if [[ "$FZF_AVAILABLE" == "true" ]]; then
    _fzf_pick_session
  else
    _fallback_pick_session
  fi
}

# Pick CLI with automatic fallback  
fzf_pick_cli() {
  if [[ "$FZF_AVAILABLE" == "true" ]]; then
    _fzf_pick_cli
  else
    _fallback_pick_cli
  fi
}

# Check if fzf is available
fzf_is_available() {
  [[ "$FZF_AVAILABLE" == "true" ]]
}

# Show fzf status in UI
fzf_status() {
  if fzf_is_available; then
    ui_success "fzf integration ready"
  else
    ui_info "fzf not installed — using fallback menus"
    ui_muted "      Install fzf for fuzzy search: brew install fzf"
  fi
}
