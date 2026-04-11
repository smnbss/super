#!/usr/bin/env bash
# super/lib/interactive.sh
# Interactive UI components for super CLI
# Supports: gum (charm.sh) > pure bash checkboxes > numbered fallback
#
# Usage: source "$SUPER_HOME/lib/interactive.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

GUM_AVAILABLE=false
if command -v gum &>/dev/null; then
  GUM_AVAILABLE=true
fi

# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED MENU SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════
# All menus use consistent keybindings:
#   ↑/↓     Navigate
#   SPACE   Toggle (multi-select) or Select (single)
#   ENTER   Confirm
#   A       Select all (multi-select only)
#   N       Select none (multi-select only)
#   Q       Quit/Cancel
# ═══════════════════════════════════════════════════════════════════════════════

# Display standard menu help
_ui_menu_help() {
  local mode="${1:-single}"  # single or multi
  
  if [[ "$mode" == "multi" ]]; then
    ui_muted "  ↑↓ navigate  SPACE toggle  ENTER confirm  A=all  N=none  Q=quit"
  else
    ui_muted "  ↑↓ navigate  SPACE/ENTER select  Q=quit"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# SINGLE SELECT MENU (for main menu, CLI picker, etc.)
# Returns: index (0-based) or empty if cancelled
# ═══════════════════════════════════════════════════════════════════════════════

ui_select_single() {
  local title="$1"
  local default_idx="${2:-0}"
  shift 2
  local options=("$@")
  
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    _ui_select_single_gum "$title" "$default_idx" "${options[@]}"
  else
    _ui_select_single_bash "$title" "$default_idx" "${options[@]}"
  fi
}

_ui_select_single_gum() {
  local title="$1"
  local default_idx="$2"
  shift 2
  local options=("$@")
  
  local result
  result=$(printf '%s\n' "${options[@]}" | gum choose --height=10 --header "$title")
  
  # Find index of selection
  local i=0
  for opt in "${options[@]}"; do
    [[ "$opt" == "$result" ]] && echo "$i" && return 0
    ((i++))
  done
  
  echo ""  # Cancelled
}

_ui_select_single_bash() {
  local title="$1"
  local cursor="$2"
  shift 2
  local options=("$@")
  local total=${#options[@]}
  
  # Hide cursor
  printf '\033[?25l'
  
  while true; do
    # Clear and redraw
    printf '\033[J'
    
    ui_bold "$title"
    echo ""
    _ui_menu_help "single"
    echo ""
    
    # Draw options
    for ((i=0; i<total; i++)); do
      if [[ $i -eq $cursor ]]; then
        printf " $(_c $UI_PRIMARY)>${UI_RESET} %s\n" "${options[$i]}"
      else
        printf "   %s\n" "${options[$i]}"
      fi
    done
    
    # Read key
    read -rs -n1 key
    
    case "$key" in
      $'\x1b')  # Escape sequence
        read -rs -n2 key
        case "$key" in
          '[A') ((cursor > 0)) && ((cursor--)) ;;  # Up
          '[B') ((cursor < total - 1)) && ((cursor++)) ;;  # Down
        esac
        ;;
      ' '|'')  # Space or Enter - select
        printf '\033[?25h'  # Show cursor
        echo "$cursor"
        return 0
        ;;
      'q'|'Q')  # Quit
        printf '\033[?25h'
        echo ""
        return 1
        ;;
    esac
    
    # Move cursor back up for redraw
    printf '\033[%dA' $((total + 3))
  done
}

# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-SELECT MENU (for install, etc.)
# Returns: space-separated indices (0-based) or empty if cancelled
# ═══════════════════════════════════════════════════════════════════════════════

ui_select_multi() {
  local title="$1"
  shift
  local options=("$@")
  local defaults="${2:-}"  # space-separated default selections
  
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    _ui_select_multi_gum "$title" "${options[@]}"
  else
    _ui_select_multi_bash "$title" "$defaults" "${options[@]}"
  fi
}

_ui_select_multi_gum() {
  local title="$1"
  shift
  local options=("$@")
  
  local result
  result=$(printf '%s\n' "${options[@]}" | gum choose --no-limit --height=10 --header "$title")
  
  [[ -z "$result" ]] && return 1
  
  # Convert selections to indices
  local indices=()
  while IFS= read -r selected; do
    local i=0
    for opt in "${options[@]}"; do
      [[ "$opt" == "$selected" ]] && indices+=("$i") && break
      ((i++))
    done
  done <<< "$result"
  
  printf '%s\n' "${indices[@]}"
}

_ui_select_multi_bash() {
  local title="$1"
  local defaults="$2"
  shift 2
  local options=("$@")
  local total=${#options[@]}
  
  # Initialize selections from defaults
  local selected=()
  for ((i=0; i<total; i++)); do
    selected[$i]=0
  done
  for idx in $defaults; do
    [[ "$idx" =~ ^[0-9]+$ ]] && ((idx < total)) && selected[$idx]=1
  done
  
  local cursor=0
  
  # Hide cursor
  printf '\033[?25l'
  
  while true; do
    # Clear and redraw
    printf '\033[J'
    
    ui_bold "$title"
    echo ""
    _ui_menu_help "multi"
    echo ""
    
    # Draw options
    for ((i=0; i<total; i++)); do
      local marker="○"
      local color="$UI_MUTED"
      
      [[ ${selected[$i]} -eq 1 ]] && marker="◉" && color="$UI_SUCCESS"
      
      if [[ $i -eq $cursor ]]; then
        printf " $(_c $UI_PRIMARY)>${UI_RESET} $(_c $color)${marker}${UI_RESET} %s\n" "${options[$i]}"
      else
        printf "   $(_c $color)${marker}${UI_RESET} %s\n" "${options[$i]}"
      fi
    done
    
    # Read key
    read -rs -n1 key
    
    case "$key" in
      $'\x1b')  # Escape sequence
        read -rs -n2 key
        case "$key" in
          '[A') ((cursor > 0)) && ((cursor--)) ;;
          '[B') ((cursor < total - 1)) && ((cursor++)) ;;
        esac
        ;;
      ' ')  # Space - toggle
        selected[$cursor]=$((1 - ${selected[$cursor]}))
        ;;
      'a'|'A')  # Select all
        for ((i=0; i<total; i++)); do selected[$i]=1; done
        ;;
      'n'|'N')  # Select none
        for ((i=0; i<total; i++)); do selected[$i]=0; done
        ;;
      '')  # Enter - confirm
        # Check if anything selected
        local any=0
        for ((i=0; i<total; i++)); do
          [[ ${selected[$i]} -eq 1 ]] && any=1 && printf '%d ' "$i"
        done
        printf '\033[?25h'  # Show cursor
        echo ""  # Newline
        [[ $any -eq 0 ]] && return 1
        return 0
        ;;
      'q'|'Q')  # Quit
        printf '\033[?25h'
        echo ""
        return 1
        ;;
    esac
    
    # Move cursor back up for redraw
    printf '\033[%dA' $((total + 3))
  done
}

# ═══════════════════════════════════════════════════════════════════════════════
# INSTALL INTERACTIVE MAIN ENTRY
# ═══════════════════════════════════════════════════════════════════════════════

cmd_install_interactive() {
  ui_banner
  
  # Detect installed CLIs
  local available_clis=()
  local cli_labels=()
  local cli_keys=()
  
  for cli in claude gemini codex kimi; do
    if is_installed "$cli"; then
      cli_keys+=("$cli")
      cli_labels+=("${CLI_LABEL[$cli]}")
      available_clis+=("${CLI_ICON[$cli]} ${CLI_LABEL[$cli]}")
    fi
  done
  
  # Check if any CLIs are installed
  if [[ ${#available_clis[@]} -eq 0 ]]; then
    ui_warn "No supported CLIs detected on this system."
    ui_spacer
    ui_print "$(ui_bold "Supported CLIs:")"
    ui_print "  🟠 Claude Code  — https://claude.ai/code"
    ui_print "  🔵 Gemini CLI   — https://gemini.google.com/cli"
    ui_print "  🟢 Codex CLI    — https://openai.com/codex"
    ui_print "  🟡 Kimi Code    — https://kimi.moonshot.cn"
    ui_spacer
    ui_muted "Install one of the above and run 'super install' again."
    return 1
  fi
  
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    _install_with_gum "${available_clis[@]}" "${cli_keys[@]}"
  else
    _install_with_bash_checkbox "${available_clis[@]}" "${cli_keys[@]}"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# PURE BASH CHECKBOX IMPLEMENTATION (Zero Dependencies)
# ═══════════════════════════════════════════════════════════════════════════════

_install_with_bash_checkbox() {
  ui_print "  $(ui_bold "Select CLIs to install")"
  ui_muted "  Arrow keys to navigate, SPACE to toggle, ENTER to confirm"
  ui_muted "  [A]ll  [N]one  [Q]uit"
  ui_spacer
  
  local options=("🟠 Claude Code" "🔵 Gemini CLI" "🟢 Codex CLI" "🟡 Kimi Code CLI")
  local selected=(1 1 1 1)  # Default: all selected
  local cursor=0
  local total=${#options[@]}
  
  # Hide cursor
  printf '\033[?25l'
  
  # Clear screen below current position for drawing
  printf '\033[J'
  
  while true; do
    # Redraw all options
    for ((i=0; i<total; i++)); do
      # Move to line
      printf '\033[%dA\r' $((total - i))
      
      local marker="○"  # Empty circle
      local color="$UI_MUTED"
      
      if [[ ${selected[$i]} -eq 1 ]]; then
        marker="◉"  # Filled circle
        color="$UI_SUCCESS"
      fi
      
      if [[ $i -eq $cursor ]]; then
        # Cursor row - highlight
        printf " $(_c $UI_PRIMARY)>${UI_RESET} $(_c $color)${marker}${UI_RESET} %s\n" "${options[$i]}"
      else
        # Normal row
        printf "   $(_c $color)${marker}${UI_RESET} %s\n" "${options[$i]}"
      fi
    done
    
    # Position cursor at bottom for help text
    printf '\n'
    ui_muted "  ↑↓ navigate  SPACE toggle  ENTER confirm  A=all N=none Q=quit"
    printf '\033[1A'  # Move back up one line
    
    # Read key
    read -rs -n1 key
    
    case "$key" in
      $'\x1b')  # Escape sequence
        read -rs -n2 key
        case "$key" in
          '[A')  # Up arrow
            ((cursor > 0)) && ((cursor--))
            ;;
          '[B')  # Down arrow  
            ((cursor < total - 1)) && ((cursor++))
            ;;
        esac
        ;;
      ' ')  # Space - toggle
        selected[$cursor]=$((1 - ${selected[$cursor]}))
        ;;
      'a'|'A')  # Select all
        for ((i=0; i<total; i++)); do selected[$i]=1; done
        ;;
      'n'|'N')  # Select none
        for ((i=0; i<total; i++)); do selected[$i]=0; done
        ;;
      '')  # Enter - confirm
        break
        ;;
      'q'|'Q')  # Quit
        printf '\033[?25h'  # Show cursor
        printf '\n'
        ui_warn "Installation cancelled."
        return 1
        ;;
    esac
  done
  
  # Show cursor
  printf '\033[?25h'
  printf '\n'
  
  # Check if anything selected
  local any_selected=0
  for ((i=0; i<total; i++)); do
    [[ ${selected[$i]} -eq 1 ]] && any_selected=1 && break
  done
  
  if [[ $any_selected -eq 0 ]]; then
    ui_warn "No CLIs selected. Installation cancelled."
    return 1
  fi
  
  # Install selected
  ui_spacer
  ui_info "Installing..."
  ui_spacer
  
  for ((i=0; i<total; i++)); do
    if [[ ${selected[$i]} -eq 1 ]]; then
      case $i in
        0) _install_cli "claude" ;;
        1) _install_cli "gemini" ;;
        2) _install_cli "codex" ;;
        3) _install_cli "kimi" ;;
      esac
    fi
  done
  
  # Setup context files
  _setup_context_files
  mkdir -p "$(_super_sessions_dir)"
  
  ui_spacer
  ui_success "Installation complete!"
  ui_muted "Run $(ui_bold "super <cli>") to start"
}

# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

_install_cli() {
  local cli="$1"
  local label="${CLI_LABEL[$cli]}"
  
  # Show spinner in background
  (
    while :; do
      for s in '⣾' '⣽' '⣻' '⢿' '⡿' '⣟' '⣯' '⣷'; do
        printf "\r  $(_c $UI_MUTED)%s${UI_RESET} Installing %s..." "$s" "$label"
        sleep 0.1
      done
    done
  ) &
  local spinner_pid=$!
  
  # Run install
  local result=0
  case "$cli" in
    claude) install_hooks_claude ;;
    gemini) install_hooks_gemini ;;
    codex)  install_hooks_codex ;;
    kimi)   install_hooks_kimi ;;
  esac || result=1
  
  # Kill spinner
  kill $spinner_pid 2>/dev/null
  wait $spinner_pid 2>/dev/null
  
  # Clear line and show result
  printf '\r%*s\r' 60 ""
  
  if [[ $result -eq 0 ]]; then
    ui_success "${CLI_ICON[$cli]} ${label} installed"
  else
    ui_error "${CLI_ICON[$cli]} ${label} failed"
  fi
  
  return $result
}

# ═══════════════════════════════════════════════════════════════════════════════
# GUM STATUS
# ═══════════════════════════════════════════════════════════════════════════════

gum_status() {
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    ui_success "gum integration ready ($(gum --version 2>/dev/null | head -1))"
  else
    ui_info "gum not installed — using fallback menus"
    ui_muted "      For better UI: brew install gum"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# OTHER GUM-ENHANCED INTERACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Input with gum or fallback
ui_input() {
  local prompt="$1"
  local placeholder="${2:-}"
  local default="${3:-}"
  
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    gum input --prompt "$prompt " --placeholder "$placeholder" --value "$default"
  else
    ui_prompt "$prompt"
    [[ -n "$placeholder" ]] && ui_muted "($placeholder)"
    read -r input
    echo "${input:-$default}"
  fi
}

# Confirm with gum or fallback
ui_confirm() {
  local message="$1"
  local default="${2:-yes}"  # yes/no
  
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    if [[ "$default" == "yes" ]]; then
      gum confirm "$message" --default="Yes"
    else
      gum confirm "$message" --default="No"
    fi
  else
    local prompt="$message"
    if [[ "$default" == "yes" ]]; then
      prompt="$prompt [Y/n]: "
    else
      prompt="$prompt [y/N]: "
    fi
    
    ui_prompt "$prompt"
    read -r response
    
    [[ "$default" == "yes" && -z "$response" ]] && return 0
    [[ "$default" == "no" && -z "$response" ]] && return 1
    [[ "${response,,}" == "y" || "${response,,}" == "yes" ]] && return 0
    return 1
  fi
}

# Choose single from list
ui_choose() {
  local prompt="$1"
  shift
  local options=("$@")
  
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    printf '%s\n' "${options[@]}" | gum choose --header "$prompt"
  else
    ui_print "  $(ui_bold "$prompt")"
    ui_spacer
    
    local i=1
    for opt in "${options[@]}"; do
      ui_menu_item "$i" "" "$opt"
      ((i++))
    done
    
    ui_spacer
    ui_prompt "Choice:"
    read -r choice
    
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
      echo "${options[$((choice-1))]}"
    else
      echo ""
    fi
  fi
}
