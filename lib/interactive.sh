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
# INSTALL INTERACTIVE MAIN ENTRY
# ═══════════════════════════════════════════════════════════════════════════════

cmd_install_interactive() {
  ui_banner
  
  if [[ "$GUM_AVAILABLE" == "true" ]]; then
    _install_with_gum
  else
    _install_with_bash_checkbox
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# GUM IMPLEMENTATION (Premium Experience)
# ═══════════════════════════════════════════════════════════════════════════════

_install_with_gum() {
  ui_print "  $(ui_bold "Select CLIs to install")"
  ui_muted "  Using gum for beautiful checkboxes"
  ui_muted "  SPACE to toggle, ENTER to confirm"
  ui_spacer
  
  local options=("🟠 Claude Code" "🔵 Gemini CLI" "🟢 Codex CLI" "🟡 Kimi Code CLI")
  
  # Pre-select all installed CLIs by default
  local selected
  selected=$(printf '%s\n' "${options[@]}" | gum choose --no-limit --height=6 --header="Select CLIs to install")
  
  # Handle cancel (ESC or no selection)
  if [[ -z "$selected" ]]; then
    ui_warn "No CLIs selected. Installation cancelled."
    return 1
  fi
  
  # Count selections
  local count
  count=$(echo "$selected" | wc -l | tr -d ' ')
  ui_spacer
  ui_info "Installing $count CLI(s)..."
  ui_spacer
  
  # Install selected
  local installed=0
  echo "$selected" | while read -r cli; do
    case "$cli" in
      *"Claude"*) 
        if _install_cli "claude"; then ((installed++)); fi
        ;;
      *"Gemini"*) 
        if _install_cli "gemini"; then ((installed++)); fi
        ;;
      *"Codex"*)  
        if _install_cli "codex"; then ((installed++)); fi
        ;;
      *"Kimi"*)   
        if _install_cli "kimi"; then ((installed++)); fi
        ;;
    esac
  done
  
  # Setup context files
  _setup_context_files
  mkdir -p "$(_super_sessions_dir)"
  
  ui_spacer
  ui_success "Installation complete!"
  ui_muted "Run $(ui_bold "super <cli>") to start (e.g., super claude)"
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
