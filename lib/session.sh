#!/usr/bin/env bash
# super/lib/session.sh
# Core session management library — sourced by all hook scripts and the launcher
#
# Layout:
#   .super/
#     sessions/
#       2026-04-11_143201_auth-refactor.md
#       2026-04-11_160042_untitled.md
#     active          <- plain text: absolute path to active session file
#     super.log

# ─── Project root discovery ──────────────────────────────────────────────────

_super_find_root() {
  local dir="${SUPER_PROJECT_DIR:-$(pwd)}"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.super" ]]; then
      echo "$dir"; return 0
    fi
    if [[ -d "$dir/.git" || -f "$dir/.git" ]]; then
      echo "$dir"; return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo "$(pwd)"
}

_super_base_dir()     { echo "$(_super_find_root)/.super"; }
_super_sessions_dir() { echo "$(_super_base_dir)/sessions"; }
_super_active_ptr()   { echo "$(_super_base_dir)/active"; }
_super_log_file()     { echo "$(_super_base_dir)/super.log"; }

# ─── Active session path ─────────────────────────────────────────────────────
# All hooks call this to know which file to write to.

_super_session_file() {
  local ptr
  ptr="$(_super_active_ptr)"
  if [[ -f "$ptr" ]]; then
    cat "$ptr"
  else
    # Fallback: newest session, or empty
    ls -t "$(_super_sessions_dir)"/*.md 2>/dev/null | head -1 || echo ""
  fi
}

# ─── Logging ─────────────────────────────────────────────────────────────────

_log() {
  echo "[$(date '+%H:%M:%S')] $*" >> "$(_super_log_file)" 2>/dev/null
}

# ─── Icons ───────────────────────────────────────────────────────────────────

_cli_icon() {
  local name="${1,,}"
  case "$name" in
    claude|claude-code|claude\ code)    echo "🟠" ;;
    gemini|gemini\ cli)                 echo "🔵" ;;
    codex|codex\ cli)                   echo "🟢" ;;
    kimi|kimi\ code|kimi\ code\ cli)    echo "🟡" ;;
    *)                                  echo "⚪" ;;
  esac
}

# ─── Session creation ─────────────────────────────────────────────────────────

session_new() {
  # session_new [title]
  # Creates a new timestamped session file, sets it active, returns its path.
  local title="${1:-untitled}"
  local safe_title
  safe_title="$(echo "$title" | tr '[:upper:]' '[:lower:]' |
    sed 's/[^a-z0-9_-]/-/g; s/--*/-/g; s/^-//; s/-$//' | cut -c1-40)"
  [[ -z "$safe_title" ]] && safe_title="untitled"

  local ts
  ts="$(date '+%Y-%m-%d_%H%M%S')"

  local sessions_dir
  sessions_dir="$(_super_sessions_dir)"
  mkdir -p "$sessions_dir"

  local filepath="$sessions_dir/${ts}_${safe_title}.md"

  cat > "$filepath" << EOF
# SuperCLI Session: $title

**Project:** $(basename "$(_super_find_root)")
**Started:** $(date '+%Y-%m-%d %H:%M:%S')
**Directory:** $(pwd)
**File:** ${ts}_${safe_title}.md

---

EOF

  echo "$filepath" > "$(_super_active_ptr)"
  _log "New session: $filepath"
  echo "$filepath"
}

# ─── Session resume ───────────────────────────────────────────────────────────

session_resume() {
  # session_resume <filepath>
  local filepath="$1"
  [[ -f "$filepath" ]] || { echo "Session not found: $filepath" >&2; return 1; }
  echo "$filepath" > "$(_super_active_ptr)"
  printf '\n---\n\n> ↩️  **Resumed** %s\n\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$filepath"
  _log "Resumed: $filepath"
  echo "$filepath"
}

# ─── Session listing ──────────────────────────────────────────────────────────

session_list() {
  # Prints all sessions, newest first. Used by cmd_sessions and cmd_log.
  local sessions_dir
  sessions_dir="$(_super_sessions_dir)"
  [[ -d "$sessions_dir" ]] || return 0

  local active
  active="$(_super_session_file)"

  local i=1
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    local title started turns marker
    title="$(grep '^# SuperCLI Session:' "$f" | sed 's/# SuperCLI Session: //' | head -1)"
    [[ -z "$title" ]] && title="$(basename "$f" .md)"
    started="$(grep '^\*\*Started:\*\*' "$f" | sed 's/\*\*Started:\*\* //' | head -1)"
    turns="$(grep -c '^## ' "$f" 2>/dev/null || echo 0)"
    marker=""
    [[ "$f" == "$active" ]] && marker=" ◀ active"
    printf '%d\t%s\t%s\t%s turns%s\n' "$i" "$(basename "$f")" "$started" "$turns" "$marker"
    ((i++))
  done < <(ls -t "$sessions_dir"/*.md 2>/dev/null)
}

# ─── Interactive session picker ───────────────────────────────────────────────

session_pick() {
  # Prompts the user to pick a session. Echoes the chosen filepath, or "" for new.
  local sessions_dir
  sessions_dir="$(_super_sessions_dir)"

  local files=()
  while IFS= read -r f; do
    [[ -f "$f" ]] && files+=("$f")
  done < <(ls -t "$sessions_dir"/*.md 2>/dev/null)

  if [[ ${#files[@]} -eq 0 ]]; then
    echo ""; return
  fi

  local active
  active="$(_super_session_file)"

  echo ""
  echo -e "\033[1mSaved sessions  (newest first)\033[0m"
  echo ""

  local i=1
  for f in "${files[@]}"; do
    local title started turns col marker
    title="$(grep '^# SuperCLI Session:' "$f" | sed 's/# SuperCLI Session: //' | head -1)"
    [[ -z "$title" ]] && title="$(basename "$f" .md)"
    started="$(grep '^\*\*Started:\*\*' "$f" | sed 's/\*\*Started:\*\* //' | head -1)"
    turns="$(grep -c '^## ' "$f" 2>/dev/null || echo 0)"
    col="\033[0m"; marker=""
    if [[ "$f" == "$active" ]]; then
      col="\033[1;32m"; marker=" ◀"
    fi
    printf "  \033[1m[%2d]\033[0m  ${col}%-38s\033[0m  %-20s  %s turns%s\n" \
      "$i" "$title" "$started" "$turns" "$marker"
    ((i++))
  done
  echo ""
  printf "  \033[1m[n]\033[0m  Start a \033[1mnew\033[0m session\n"
  echo ""

  read -rp "  Choice: " choice

  case "$choice" in
    n|N|new) echo ""; return ;;
    q|Q)     echo "QUIT"; return ;;
  esac

  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#files[@]} )); then
    echo "${files[$((choice-1))]}"
  else
    echo ""
  fi
}

# ─── Turn appending ───────────────────────────────────────────────────────────

session_append_turn() {
  # session_append_turn <cli_name> <role> <content>
  local cli="$1" role="$2" content="$3"
  local file ts icon

  file="$(_super_session_file)"
  if [[ -z "$file" || ! -f "$file" ]]; then
    file="$(session_new "auto")"
  fi

  ts="$(date '+%H:%M:%S')"
  icon="$(_cli_icon "$cli")"

  case "$role" in
    user)
      printf '\n---\n\n## %s `[%s %s]` 👤 User\n\n%s\n' \
        "$icon" "$cli" "$ts" "$content" >> "$file"
      ;;
    assistant)
      printf '\n### %s `[%s %s]` 🤖 Assistant\n\n%s\n' \
        "$icon" "$cli" "$ts" "$content" >> "$file"
      ;;
    tool)
      printf '\n> **Tool** `%s` `[%s]`\n> \n> ```\n%s\n> ```\n' \
        "$cli" "$ts" "$(echo "$content" | head -20 | sed 's/^/> /')" >> "$file"
      ;;
    session_start)
      printf '\n---\n\n### %s `[%s %s]` 🚀 Started with **%s**\n\n' \
        "$icon" "$cli" "$ts" "$cli" >> "$file"
      ;;
    session_end)
      printf '\n### %s `[%s %s]` 🏁 Session ended (**%s**)\n\n' \
        "$icon" "$cli" "$ts" "$cli" >> "$file"
      ;;
  esac
  _log "Appended $role from $cli → $(basename "$file")"
}

# ─── Context injection ────────────────────────────────────────────────────────

session_get_summary() {
  local n="${1:-50}"
  local file
  file="$(_super_session_file)"
  [[ -f "$file" ]] || { echo "No active session."; return; }
  grep -v '^---$' "$file" | tail -n "$n"
}

session_inject_context() {
  local cli="$1"
  local root
  root="$(_super_find_root)"
  local summary
  summary="$(session_get_summary 80)"
  local header="<!-- super:session-context -->"
  local footer="<!-- /super:session-context -->"
  local session_file active_name
  session_file="$(_super_session_file)"
  active_name="$(basename "${session_file:-unknown}")"

  _inject_to_file() {
    local target="$1"
    if [[ -f "$target" ]]; then
      python3 -c "
import sys
path,hdr,ftr = sys.argv[1],'<!-- super:session-context -->','<!-- /super:session-context -->'
with open(path) as fh: lines = fh.readlines()
out,skip = [],False
for line in lines:
    if hdr in line: skip=True
    if not skip: out.append(line)
    if ftr in line: skip=False
with open(path,'w') as fh: fh.writelines(out)
" "$target"
    else
      touch "$target"
    fi
    cat >> "$target" << EOF

$header
## 📋 SuperCLI Cross-Session Context

Session: \`$active_name\`

You are continuing a conversation that may have started in a different AI coding
assistant. The history below is the shared session log. Pick up where things
left off.

$summary
$footer
EOF
    _log "Injected context → $target"
  }

  case "${cli,,}" in
    claude|claude-code) _inject_to_file "$root/CLAUDE.md"  ;;
    gemini)             _inject_to_file "$root/GEMINI.md"  ;;
    codex|kimi)         _inject_to_file "$root/AGENTS.md"  ;;
  esac
}

session_clear_injections() {
  local root
  root="$(_super_find_root)"
  for f in CLAUDE.md GEMINI.md AGENTS.md; do
    local target="$root/$f"
    [[ -f "$target" ]] || continue
    python3 -c "
import sys
path,hdr,ftr = sys.argv[1],'<!-- super:session-context -->','<!-- /super:session-context -->'
with open(path) as fh: lines = fh.readlines()
out,skip = [],False
for line in lines:
    if hdr in line: skip=True
    if not skip: out.append(line)
    if ftr in line: skip=False
with open(path,'w') as fh: fh.writelines(out)
" "$target"
  done
  _log "Cleared injections"
}
