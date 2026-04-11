#!/usr/bin/env bash
# super/lib/interactive.sh

ui_select_single() {
  local title="$1" default_idx="${2:-0}"
  shift 2; local options=("$@")
  
  if command -v gum >/dev/null 2>&1; then
    local result=$(printf '%s\n' "${options[@]}" | gum choose --height=10 --header "$title")
    local i=0; for opt in "${options[@]}"; do [[ "$opt" == "$result" ]] && echo "$i" && return; ((i++)); done; echo ""
  else
    _ui_select_simple "$title" "$default_idx" "${options[@]}"
  fi
}

_ui_select_simple() {
  local title="$1" default="$2"; shift 2; local options=("$@")
  local total=${#options[@]}
  
  echo "$title" >&2
  echo "" >&2
  for ((i=0; i<total; i++)); do
    local marker="  "
    [[ $i -eq $default ]] && marker="> "
    echo "$marker$((i+1)). ${options[$i]}" >&2
  done
  echo "" >&2
  echo -n "Select (1-$total, or Q to quit): " >&2
  
  while true; do
    read -r input
    [[ "$input" == "q" || "$input" == "Q" ]] && echo "" && return 1
    [[ "$input" =~ ^[0-9]+$ ]] && ((input >= 1 && input <= total)) && echo "$((input-1))" && return 0
    echo -n "Invalid selection. Try again (1-$total): " >&2
  done
}

ui_select_multi() {
  local title="$1"; shift; local options=("$@")
  local defaults="${2:-}"
  
  if command -v gum >/dev/null 2>&1; then
    local result=$(printf '%s\n' "${options[@]}" | gum choose --no-limit --height=10 --header "$title")
    [[ -z "$result" ]] && return 1
    local indices=(); while IFS= read -r sel; do local i=0; for opt in "${options[@]}"; do [[ "$opt" == "$sel" ]] && indices+=("$i") && break; ((i++)); done; done <<< "$result"
    printf '%s\n' "${indices[@]}"
  else
    _ui_multi_simple "$title" "$defaults" "${options[@]}"
  fi
}

_ui_multi_simple() {
  local title="$1" defaults="$2"; shift 2; local options=("$@")
  local total=${#options[@]} selected=()
  
  for ((i=0; i<total; i++)); do selected[$i]=0; done
  for idx in $defaults; do [[ "$idx" =~ ^[0-9]+$ ]] && ((idx<total)) && selected[$idx]=1; done
  
  while true; do
    clear >&2 || printf '\033[2J\033[H' >&2
    echo "$title" >&2
    echo "" >&2
    echo "SPACE to toggle, A=all, N=none, ENTER to confirm, Q=quit" >&2
    echo "" >&2
    for ((i=0; i<total; i++)); do
      local marker="○"
      [[ ${selected[$i]} -eq 1 ]] && marker="◉"
      echo "  $marker $((i+1)). ${options[$i]}" >&2
    done
    echo "" >&2
    echo -n "Command (SPACE/A/N/ENTER/Q): " >&2
    
    IFS= read -rs -n1 key
    case "$key" in
      ' ')
        echo "Toggle not supported in simple mode. Use numbers (e.g., '1 3') or: " >&2
        echo -n "Enter selections (space-separated, e.g., '1 3'): " >&2
        read -r nums
        for n in $nums; do [[ "$n" =~ ^[0-9]+$ ]] && ((n>=1 && n<=total)) && selected[$((n-1))]=1; done
        ;;
      'a'|'A') for ((i=0; i<total; i++)); do selected[$i]=1; done ;;
      'n'|'N') for ((i=0; i<total; i++)); do selected[$i]=0; done ;;
      '')
        local any=0 result=""
        for ((i=0; i<total; i++)); do [[ ${selected[$i]} -eq 1 ]] && any=1 && result="$result$i "; done
        echo "$result"
        [[ $any -eq 0 ]] && return 1
        return 0
        ;;
      'q'|'Q') echo "" && return 1 ;;
    esac
  done
}

cmd_install_interactive() {
  ui_banner
  local available_clis=() cli_keys=()
  for cli in claude gemini codex kimi; do
    if is_installed "$cli" 2>/dev/null; then
      cli_keys+=("$cli")
      available_clis+=("${CLI_ICON[$cli]} ${CLI_LABEL[$cli]}")
    fi
  done
  
  if [[ ${#available_clis[@]} -eq 0 ]]; then
    ui_warn "No supported CLIs detected."
    return 1
  fi
  
  if command -v gum >/dev/null 2>&1; then
    _install_with_gum "${available_clis[@]}" "${cli_keys[@]}"
  else
    _install_simple "$title" "${available_clis[@]}" "${cli_keys[@]}"
  fi
}

_install_with_gum() {
  local options=() keys=()
  while [[ "$1" != "" && ! "$1" =~ ^[a-z]+$ ]]; do options+=("$1"); shift; done
  keys=("$@")
  
  ui_print "Select CLIs to install:"
  local selected=$(printf '%s\n' "${options[@]}" | gum choose --no-limit --height=6)
  [[ -z "$selected" ]] && { ui_warn "Cancelled."; return 1; }
  
  echo "$selected" | while read -r line; do
    for i in "${!options[@]}"; do
      [[ "${options[$i]}" == "$line" ]] && _install_cli "${keys[$i]}"
    done
  done
}

_install_simple() {
  shift; local options=() keys=()
  while [[ "$1" != "" && ! "$1" =~ ^claude|gemini|codex|kimi$ ]]; do options+=("$1"); shift; done
  keys=("$@")
  
  local indices=$(ui_select_multi "Select CLIs to install:" "" "${options[@]}")
  [[ -z "$indices" ]] && { ui_warn "Cancelled."; return 1; }
  
  for idx in $indices; do
    [[ "$idx" =~ ^[0-9]+$ ]] && ((idx < ${#keys[@]})) && _install_cli "${keys[$idx]}"
  done
}

_install_cli() {
  local cli="$1" label="${CLI_LABEL[$cli]}"
  printf "Installing %s... " "$label"
  case "$cli" in
    claude) install_hooks_claude 2>/dev/null ;;
    gemini) install_hooks_gemini 2>/dev/null ;;
    codex) install_hooks_codex 2>/dev/null ;;
    kimi) install_hooks_kimi 2>/dev/null ;;
  esac && printf "✓\n" || printf "✗\n"
}
