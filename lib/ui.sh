#!/usr/bin/env bash
# super/lib/ui.sh
# Design system for super CLI — colors, spacing, typography, and UI components
#
# Usage: source "$SUPER_HOME/lib/ui.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# COLOR SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

# Brand colors
UI_PRIMARY="36"      # cyan — super brand color (🔀)
UI_SUCCESS="32"      # green — success states only
UI_WARNING="33"      # yellow — warnings, attention needed
UI_ERROR="31"        # red — errors only
UI_MUTED="90"        # bright black — secondary info
UI_ACCENT="35"       # magenta — highlights, special

# Text styles
UI_BOLD="\033[1m"
UI_DIM="\033[2m"
UI_UNDERLINE="\033[4m"
UI_RESET="\033[0m"

# Convenience helpers
_c() { echo "\033[${1}m"; }  # _c $UI_PRIMARY
_reset() { echo -e "${UI_RESET}"; }

# ═══════════════════════════════════════════════════════════════════════════════
# SPACING SYSTEM (Tailwind-inspired)
# ═══════════════════════════════════════════════════════════════════════════════

UI_SPACE_1=1   # tight — single space
UI_SPACE_2=2   # default — small gap
UI_SPACE_3=4   # loose — section padding
UI_SPACE_4=6   # major break — between sections
UI_SPACE_5=8   # page break — major sections

# ═══════════════════════════════════════════════════════════════════════════════
# ICONOGRAPHY
# ═══════════════════════════════════════════════════════════════════════════════

UI_ICON_OK="✓"
UI_ICON_ERROR="✗"
UI_ICON_WARNING="⚠"
UI_ICON_INFO="ℹ"
UI_ICON_ARROW="→"
UI_ICON_ARROW_LEFT="←"
UI_ICON_BULLET="•"
UI_ICON_DIAMOND="◆"
UI_ICON_CIRCLE="●"
UI_ICON_CIRCLE_EMPTY="○"
UI_ICON_STAR="★"
UI_ICON_CLOCK="◷"
UI_ICON_FOLDER="📁"
UI_ICON_FILE="📄"
UI_ICON_BRIDGE="🔀"
UI_ICON_HANDOFF="↩"
UI_ICON_CHECKPOINT="💾"
UI_ICON_ACTIVE="◀"
UI_ICON_NEW="🆕"
UI_ICON_RESUME="↩️"
UI_ICON_SWITCH="🔀"

# ═══════════════════════════════════════════════════════════════════════════════
# CORE OUTPUT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Print styled text
ui_print() {
  echo -e "$*"
}

# Primary brand output
ui_brand() {
  echo -e "$(_c $UI_PRIMARY)${UI_ICON_BRIDGE}${UI_RESET} $*"
}

# Success message
ui_success() {
  echo -e "$(_c $UI_SUCCESS)${UI_ICON_OK}${UI_RESET} $*"
}

# Error message  
ui_error() {
  echo -e "$(_c $UI_ERROR)${UI_ICON_ERROR}${UI_RESET} $*" >&2
}

# Warning message
ui_warn() {
  echo -e "$(_c $UI_WARNING)${UI_ICON_WARNING}${UI_RESET} $*"
}

# Info message
ui_info() {
  echo -e "$(_c $UI_MUTED)${UI_ICON_INFO}${UI_RESET} $*"
}

# Muted/secondary text
ui_muted() {
  echo -e "$(_c $UI_MUTED)$*${UI_RESET}"
}

# Bold text
ui_bold() {
  echo -e "${UI_BOLD}$*${UI_RESET}"
}

# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

# Empty line
ui_spacer() {
  local n="${1:-1}"
  for ((i=0; i<n; i++)); do echo ""; done
}

# Horizontal rule
ui_rule() {
  local width="${1:-60}"
  local char="${2:-─}"
  printf "%${width}s\n" "" | tr " " "$char"
}

# Section header
ui_section() {
  ui_spacer
  ui_bold "$*"
  ui_rule 40
}

# Box/container
ui_box() {
  local content=("$@")
  local max_width=0
  
  # Calculate max width
  for line in "${content[@]}"; do
    local len=${#line}
    (( len > max_width )) && max_width=$len
  done
  
  local width=$((max_width + 4))
  local border="┌$(printf '%*s' $((width-2)) '' | tr ' ' '─')┐"
  local bottom="└$(printf '%*s' $((width-2)) '' | tr ' ' '─')┘"
  
  echo "$border"
  for line in "${content[@]}"; do
    printf "│ %-${max_width}s │\n" "$line"
  done
  echo "$bottom"
}

# ═══════════════════════════════════════════════════════════════════════════════
# PROGRESS & FEEDBACK
# ═══════════════════════════════════════════════════════════════════════════════

# Spinner for long operations
# Usage: long_command &; ui_spinner $! "Doing something..."
ui_spinner() {
  local pid=$1
  local msg="${2:-Working...}"
  local spin='⣾⣽⣻⢿⡿⣟⣯⣷'
  local i=0
  
  # Hide cursor
  printf '\033[?25l'
  
  while kill -0 $pid 2>/dev/null; do
    printf "\r$(_c $UI_MUTED)%s${UI_RESET} %s" "${spin:$i:1}" "$msg"
    ((i=(i+1)%8))
    sleep 0.08
  done
  
  # Clear line and show cursor
  printf "\r%*s\r" $((${#msg}+2)) ""
  printf '\033[?25h'
}

# Progress bar
# Usage: ui_progress 50 100 "Installing"
ui_progress() {
  local current=$1
  local total=$2
  local label="${3:-Progress}"
  local width=30
  
  local pct=$((current * 100 / total))
  local filled=$((current * width / total))
  local empty=$((width - filled))
  
  printf "\r%s [%s%s] %d%%" \
    "$label" \
    "$(printf '%*s' $filled '' | tr ' ' '█')" \
    "$(printf '%*s' $empty '' | tr ' ' '░')" \
    "$pct"
  
  ((current == total)) && echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

# Styled prompt
ui_prompt() {
  local text="$1"
  echo -en "$(_c $UI_PRIMARY)${UI_BOLD}>${UI_RESET} $text "
}

# Menu item
ui_menu_item() {
  local key="$1"
  local icon="$2"
  local text="$3"
  local desc="${4:-}"
  
  if [[ -n "$desc" ]]; then
    printf "  ${UI_BOLD}[%s]${UI_RESET}  %s  %-20s  $(_c $UI_MUTED)%s${UI_RESET}\n" \
      "$key" "$icon" "$text" "$desc"
  else
    printf "  ${UI_BOLD}[%s]${UI_RESET}  %s  %s\n" \
      "$key" "$icon" "$text"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════

# Format session for display
ui_session_line() {
  local num="$1"
  local name="$2"
  local time="$3"
  local turns="$4"
  local cli="$5"
  local is_active="${6:-false}"
  
  local icon_color=""
  local marker=""
  
  case "${cli,,}" in
    claude*) icon_color="33" ;;  # orange-ish
    gemini*) icon_color="34" ;;  # blue
    codex*)  icon_color="32" ;;  # green
    kimi*)   icon_color="93" ;;  # yellow
    *)       icon_color="90" ;;  # gray
  esac
  
  if [[ "$is_active" == "true" ]]; then
    marker=" $(_c $UI_SUCCESS)${UI_ICON_ACTIVE}${UI_RESET}"
  fi
  
  printf "  ${UI_BOLD}%2s${UI_RESET}  $(_c $icon_color)●${UI_RESET}  %-28s  %-16s  %s turns%s\n" \
    "$num" "$name" "$time" "$turns" "$marker"
}

# Format file size for humans
ui_human_size() {
  local bytes=$1
  if (( bytes < 1024 )); then
    echo "${bytes}B"
  elif (( bytes < 1048576 )); then
    echo "$(( (bytes + 512) / 1024 ))KB"
  else
    echo "$(( (bytes + 524288) / 1048576 ))MB"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# BRAND VOICE MESSAGES
# ═══════════════════════════════════════════════════════════════════════════════

ui_msg_handoff() {
  local from="$1"
  local to="$2"
  echo -e "${UI_ICON_BRIDGE}  $(_c $UI_MUTED)Handing off from${UI_RESET} $from $(_c $UI_MUTED)→${UI_RESET} $to"
}

ui_msg_resuming() {
  local session="$1"
  echo -e "${UI_ICON_RESUME}  $(_c $UI_MUTED)Picking up where you left off...${UI_RESET}"
  ui_muted "   Session: $session"
}

ui_msg_checkpoint() {
  echo -e "${UI_ICON_CHECKPOINT}  Checkpoint saved"
}

ui_msg_switching() {
  local cli="$1"
  echo -e "${UI_ICON_BRIDGE}  $(_c $UI_MUTED)Crossing the bridge to${UI_RESET} $cli..."
}
