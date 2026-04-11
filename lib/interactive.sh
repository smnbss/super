#!/usr/bin/env bash
# super/lib/interactive.sh — Interactive selection menus
#
# Three tiers: gum (if installed) → arrow-key TUI → plain numbered prompt
#
# KEY DESIGN CHOICE: All interactive I/O goes through /dev/tty, not
# stdin/stderr. This is critical because these functions are called inside
# command substitutions — choice=$(ui_select_single ...) — where stdin/stdout
# are redirected. Reading/writing /dev/tty bypasses that, just like gum and
# fzf do.

# ─────────────────────────────────────────────────────────────────────────────
# SINGLE SELECT
# ─────────────────────────────────────────────────────────────────────────────
# Usage: idx=$(ui_select_single "Title" default_idx "opt1" "opt2" ...)
# Returns: 0-based index on stdout, exit 0 on confirm, exit 1 on quit/cancel

ui_select_single() {
  local title="$1" default_idx="${2:-0}"
  shift 2; local options=("$@")

  if command -v gum >/dev/null 2>&1; then
    _ui_single_gum "$title" "$default_idx" "${options[@]}"
  elif [[ -r /dev/tty && -w /dev/tty ]]; then
    _ui_single_arrows "$title" "$default_idx" "${options[@]}"
  else
    _ui_single_numbered "$title" "$default_idx" "${options[@]}"
  fi
}

# ── gum ───────────────────────────────────────────────────────────────────────

_ui_single_gum() {
  local title="$1" default_idx="$2"; shift 2; local options=("$@")
  local result
  result=$(printf '%s\n' "${options[@]}" | gum choose --height=10 --header "$title" < /dev/tty)
  [[ -z "$result" ]] && return 1
  local i=0
  for opt in "${options[@]}"; do
    [[ "$opt" == "$result" ]] && { echo "$i"; return 0; }
    ((i++))
  done
  return 1
}

# ── arrow-key TUI ─────────────────────────────────────────────────────────────

_ui_single_arrows() {
  local title="$1" cur="$2"; shift 2; local options=("$@")
  local total=${#options[@]}
  ((cur < 0)) && cur=0
  ((cur >= total)) && cur=$((total - 1))

  # lines to move up when redrawing (title + blank + N options + help)
  local up=$((total + 2))

  printf '\033[?25l' > /dev/tty              # hide cursor
  trap 'printf "\033[?25h" > /dev/tty' RETURN  # show cursor on any return

  _render_single "$title" "$cur" "${options[@]}"

  while true; do
    _read_key
    case "$_KEY" in
      up)    ((cur > 0)) && ((cur--)) ;;
      down)  ((cur < total-1)) && ((cur++)) ;;
      home)  cur=0 ;;
      end)   cur=$((total-1)) ;;
      enter) echo "$cur"; return 0 ;;
      quit)  return 1 ;;
      [1-9]) ((${_KEY} >= 1 && ${_KEY} <= total)) && cur=$((_KEY-1)) ;;
    esac
    printf '\033[%dA\r' "$up" > /dev/tty
    _render_single "$title" "$cur" "${options[@]}"
  done
}

_render_single() {
  local title="$1" cur="$2"; shift 2; local options=("$@")
  local total=${#options[@]}

  {
    printf '\033[2K%s\n'  "$title"
    printf '\033[2K\n'
    for ((i=0; i<total; i++)); do
      if ((i == cur)); then
        printf '\033[2K  \033[36m❯ %s\033[0m\n' "${options[$i]}"
      else
        printf '\033[2K    %s\n' "${options[$i]}"
      fi
    done
    printf '\033[2K\033[90m  ↑/↓ navigate · enter confirm · q quit\033[0m'
  } > /dev/tty
}

# ── plain numbered (no TTY) ──────────────────────────────────────────────────

_ui_single_numbered() {
  local title="$1" default="$2"; shift 2; local options=("$@")
  local total=${#options[@]}

  {
    echo "$title"; echo ""
    for ((i=0; i<total; i++)); do
      local m="  "; ((i == default)) && m="> "
      echo "$m$((i+1)). ${options[$i]}"
    done
    echo ""
    printf "Select (1-%d): " "$total"
  } > /dev/tty

  while true; do
    read -r input < /dev/tty
    [[ "$input" == [qQ] ]] && return 1
    [[ "$input" =~ ^[0-9]+$ && $input -ge 1 && $input -le $total ]] && {
      echo "$((input-1))"; return 0
    }
    printf "Invalid. (1-%d): " "$total" > /dev/tty
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# MULTI SELECT
# ─────────────────────────────────────────────────────────────────────────────
# Usage: indices=$(ui_select_multi "Title" "opt1" "opt2" ...)
# Returns: space-separated 0-based indices on stdout

ui_select_multi() {
  local title="$1"; shift; local options=("$@")

  if command -v gum >/dev/null 2>&1; then
    _ui_multi_gum "$title" "${options[@]}"
  elif [[ -r /dev/tty && -w /dev/tty ]]; then
    _ui_multi_arrows "$title" "${options[@]}"
  else
    _ui_multi_numbered "$title" "${options[@]}"
  fi
}

# ── gum ───────────────────────────────────────────────────────────────────────

_ui_multi_gum() {
  local title="$1"; shift; local options=("$@")
  local result
  result=$(printf '%s\n' "${options[@]}" | gum choose --no-limit --height=10 --header "$title" < /dev/tty)
  [[ -z "$result" ]] && return 1
  local indices=()
  while IFS= read -r sel; do
    local i=0
    for opt in "${options[@]}"; do
      [[ "$opt" == "$sel" ]] && { indices+=("$i"); break; }
      ((i++))
    done
  done <<< "$result"
  echo "${indices[*]}"
}

# ── arrow-key TUI ─────────────────────────────────────────────────────────────

_ui_multi_arrows() {
  local title="$1"; shift; local options=("$@")
  local total=${#options[@]} cur=0
  # _sel is used by _render_multi via bash dynamic scoping
  local _sel=()
  for ((i=0; i<total; i++)); do _sel[$i]=0; done

  local up=$((total + 2))

  printf '\033[?25l' > /dev/tty
  trap 'printf "\033[?25h" > /dev/tty' RETURN

  _render_multi "$title" "$cur" "${options[@]}"

  while true; do
    _read_key
    case "$_KEY" in
      up)    ((cur > 0)) && ((cur--)) ;;
      down)  ((cur < total-1)) && ((cur++)) ;;
      home)  cur=0 ;;
      end)   cur=$((total-1)) ;;
      space) ((_sel[cur] ^= 1)) ;;
      a|A)   for ((i=0; i<total; i++)); do _sel[$i]=1; done ;;
      n|N)   for ((i=0; i<total; i++)); do _sel[$i]=0; done ;;
      enter)
        local result="" any=0
        for ((i=0; i<total; i++)); do
          ((_sel[i])) && { result+="$i "; any=1; }
        done
        echo "$result"
        ((any)) && return 0 || return 1
        ;;
      quit) return 1 ;;
    esac
    printf '\033[%dA\r' "$up" > /dev/tty
    _render_multi "$title" "$cur" "${options[@]}"
  done
}

_render_multi() {
  local title="$1" cur="$2"; shift 2; local options=("$@")
  local total=${#options[@]}

  {
    printf '\033[2K%s\n'  "$title"
    printf '\033[2K\n'
    for ((i=0; i<total; i++)); do
      local ck="○"; ((_sel[i])) && ck="◉"
      if ((i == cur)); then
        printf '\033[2K  \033[36m❯ %s %s\033[0m\n' "$ck" "${options[$i]}"
      else
        printf '\033[2K    %s %s\n' "$ck" "${options[$i]}"
      fi
    done
    printf '\033[2K\033[90m  ↑/↓ navigate · space toggle · a all · n none · enter confirm · q quit\033[0m'
  } > /dev/tty
}

# ── plain numbered (no TTY) ──────────────────────────────────────────────────

_ui_multi_numbered() {
  local title="$1"; shift; local options=("$@")
  local total=${#options[@]}

  {
    echo "$title"; echo ""
    for ((i=0; i<total; i++)); do
      echo "  $((i+1)). ${options[$i]}"
    done
    echo ""
    printf "Enter selections (space-separated, e.g. '1 3'), q to quit: "
  } > /dev/tty

  read -r nums < /dev/tty
  [[ "$nums" == [qQ] || -z "$nums" ]] && return 1
  local result=""
  for n in $nums; do
    [[ "$n" =~ ^[0-9]+$ ]] && ((n >= 1 && n <= total)) && result+="$((n-1)) "
  done
  [[ -z "$result" ]] && return 1
  echo "$result"
}

# ─────────────────────────────────────────────────────────────────────────────
# KEY READER
# ─────────────────────────────────────────────────────────────────────────────
# Sets global $_KEY to one of:
#   up  down  left  right  home  end  enter  space  quit  escape
#   or the literal character (a, n, 1, 2, ...)
#
# Reads from /dev/tty so it works inside command substitutions.

_read_key() {
  _KEY=""
  local byte

  IFS= read -rsn1 byte < /dev/tty 2>/dev/null

  case "$byte" in
    $'\e')
      # Escape sequence: read up to 2 more bytes with tight timeout
      local s1="" s2=""
      IFS= read -rsn1 -t 0.05 s1 < /dev/tty 2>/dev/null
      IFS= read -rsn1 -t 0.05 s2 < /dev/tty 2>/dev/null
      case "${s1}${s2}" in
        '[A') _KEY=up    ;;
        '[B') _KEY=down  ;;
        '[C') _KEY=right ;;
        '[D') _KEY=left  ;;
        '[H') _KEY=home  ;;
        '[F') _KEY=end   ;;
        *)    _KEY=escape ;;
      esac
      ;;
    '')   _KEY=enter ;;
    ' ')  _KEY=space ;;
    q|Q)  _KEY=quit  ;;
    k)    _KEY=up    ;;   # vim
    j)    _KEY=down  ;;   # vim
    *)    _KEY="$byte" ;;
  esac
}

# ─────────────────────────────────────────────────────────────────────────────
# INSTALL INTERACTIVE
# ─────────────────────────────────────────────────────────────────────────────

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

  local indices
  indices=$(ui_select_multi "Select CLIs to install:" "${available_clis[@]}")
  [[ -z "$indices" ]] && { ui_warn "Cancelled."; return 1; }

  for idx in $indices; do
    [[ "$idx" =~ ^[0-9]+$ ]] && ((idx < ${#cli_keys[@]})) && _install_cli "${cli_keys[$idx]}"
  done
}

_install_cli() {
  local cli="$1" label="${CLI_LABEL[$cli]}"
  printf "Installing %s... " "$label"
  case "$cli" in
    claude) install_hooks_claude 2>/dev/null ;;
    gemini) install_hooks_gemini 2>/dev/null ;;
    codex)  install_hooks_codex  2>/dev/null ;;
    kimi)   install_hooks_kimi   2>/dev/null ;;
  esac && printf "✓\n" || printf "✗\n"
}
