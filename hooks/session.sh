#!/usr/bin/env bash
# super/lib/session.sh
# Core session management library — sourced by all hook scripts and the launcher
#
# Layout:
#   .super/
#     sessions/
#       2026-04-11_143201_auth-refactor.md
#       2026-04-11_160042.md
#     super.log

# ─── Debug-only symlinks (must always be ignored) ───────────────────────────
# `super install` creates <project>/.CLI/.CLI → ~/.CLI for each CLI (claude,
# codex, gemini, super) so developers can cd into the global home from inside
# the project. These links are a pure developer convenience — nothing in super
# or its skills should ever read, write, or recurse through them.
_super_is_cli_debug_symlink() {
  # usage: _super_is_cli_debug_symlink <path>
  # returns 0 if path is one of <anywhere>/.{claude,codex,gemini,super}/.{same}
  # AND is a symlink.
  local path="$1"
  local base parent
  base="$(basename "$path")"
  parent="$(basename "$(dirname "$path")")"
  [[ "$base" == "$parent" ]] || return 1
  case "$base" in
    .claude|.codex|.gemini|.super) [[ -L "$path" ]] ;;
    *) return 1 ;;
  esac
}

# ─── Project root discovery ──────────────────────────────────────────────────

_super_find_root() {
  # Prefer `.super` at any depth over `.git`, so nested git repos (e.g. vendored
  # skills with their own .git) don't get mistaken for the project root.
  # The match must be a REAL directory — the `.super/.super` debug symlink that
  # points back to ~/.super must not be treated as a project root marker.
  local start="${SUPER_PROJECT_DIR:-$(pwd)}"
  local dir="$start"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.super" && ! -L "$dir/.super" ]]; then
      echo "$dir"; return 0
    fi
    dir="$(dirname "$dir")"
  done
  dir="$start"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.git" || -f "$dir/.git" ]]; then
      echo "$dir"; return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo "$(pwd)"
}

_super_base_dir()     { echo "$(_super_find_root)/.super"; }
_super_sessions_dir() { echo "$(_super_base_dir)/sessions"; }
_super_log_file()     { echo "$(_super_base_dir)/super.log"; }

# ─── Active session path ─────────────────────────────────────────────────────
# All hooks call this to know which file to write to.

_super_session_file() {
  if [[ -n "${SUPER_SESSION_FILE:-}" && -f "$SUPER_SESSION_FILE" ]]; then
    echo "$SUPER_SESSION_FILE"
    return
  fi
  # Fallback: most recently modified session, or empty
  ls -t "$(_super_sessions_dir)"/*.md 2>/dev/null | head -1 || true
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

  local filepath="$sessions_dir/${ts}.md"
  local filename="${ts}.md"

  cat > "$filepath" << EOF
# Super Session: $title

**Project:** $(basename "$(_super_find_root)")
**Started:** $(date '+%Y-%m-%d %H:%M:%S')
**Directory:** $(pwd)
**File:** ${filename}

---

EOF

  export SUPER_SESSION_FILE="$filepath"
  _log "New session: $filepath"
  echo "$filepath"
}

# ─── Session resume ───────────────────────────────────────────────────────────

session_resume() {
  # session_resume <filepath>
  local filepath="$1"
  [[ -f "$filepath" ]] || { echo "Session not found: $filepath" >&2; return 1; }
  export SUPER_SESSION_FILE="$filepath"
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
    title="$(grep '^# Super Session:' "$f" 2>/dev/null | sed 's/# Super Session: //' | head -1 || true)"
    [[ -z "$title" ]] && title="$(basename "$f" .md)"
    started="$(grep '^\*\*Started:\*\*' "$f" 2>/dev/null | sed 's/\*\*Started:\*\* //' | head -1 || true)"
    turns="$(grep -c '^## ' "$f" 2>/dev/null || echo 0)"
    marker=""
    [[ "$f" == "$active" ]] && marker=" ◀ active"
    printf '%d\t%s\t%s\t%s turns%s\n' "$i" "$(basename "$f")" "$started" "$turns" "$marker"
    i=$((i + 1))
  done < <(ls -t "$sessions_dir"/*.md 2>/dev/null || true)
}

# ─── Interactive session picker ───────────────────────────────────────────────

session_pick() {
  # Prompts the user to pick a session. Echoes the chosen filepath, or "" for new.
  local sessions_dir
  sessions_dir="$(_super_sessions_dir)"

  local files=()
  while IFS= read -r f; do
    [[ -f "$f" ]] && files+=("$f")
  done < <(ls -t "$sessions_dir"/*.md 2>/dev/null || true)

  if [[ ${#files[@]} -eq 0 ]]; then
    echo ""; return
  fi

  local active
  active="$(_super_session_file)"

  # Build options for ui_select_single
  local options=()
  for f in "${files[@]}"; do
    local title started turns marker
    title="$(grep '^# Super Session:' "$f" 2>/dev/null | sed 's/# Super Session: //' | head -1 || true)"
    [[ -z "$title" ]] && title="$(basename "$f" .md)"
    started="$(grep '^\*\*Started:\*\*' "$f" 2>/dev/null | sed 's/\*\*Started:\*\* //' | head -1 || true)"
    turns="$(grep -c '^## ' "$f" 2>/dev/null || echo 0)"
    marker=""
    [[ "$f" == "$active" ]] && marker=" ◀"
    options+=("$(printf '%-38s  %-20s  %s turns%s' "$title" "$started" "$turns" "$marker")")
  done
  options+=("🆕 Start a new session")

  local choice
  choice=$(ui_select_single "Saved sessions (newest first)" 0 "${options[@]}")

  [[ -z "$choice" ]] && { echo "QUIT"; return; }

  # Last option = new session
  if [[ "$choice" -eq ${#files[@]} ]]; then
    echo ""; return
  fi

  echo "${files[$choice]}"
}

# ─── Header helpers ───────────────────────────────────────────────────────────

_session_generate_title() {
  local content="$1"
  echo "$content" | python3 -c "
import sys, re
text = sys.stdin.read()
text = re.sub(r'\`\`\`[\s\S]*?\`\`\`', '', text)
text = re.sub(r'\`[^\`]+\`', '', text)
text = text.replace('\n', ' ').strip()
if not text:
    print('code snippet')
else:
    words = re.findall(r'[\w\-]+', text)
    title = ' '.join(words[:6])[:50]
    print(title or 'code snippet')
"
}

_session_generate_description() {
  local content="$1"
  echo "$content" | python3 -c "
import sys, re
text = sys.stdin.read()
text = re.sub(r'\`\`\`[\s\S]*?\`\`\`', '', text)
text = re.sub(r'\`[^\`]+\`', '', text)
text = text.replace('\n', ' ').strip()
print(text[:140] if text else 'Shared a code snippet')
"
}

_session_update_header() {
  local file="$1" content="$2"
  [[ -f "$file" ]] || return

  # Only update title/description on first user turn (title still "untitled" or "auto")
  local current_title
  current_title="$(grep '^# Super Session:' "$file" 2>/dev/null | sed 's/# Super Session: //' | head -1 || true)"
  current_title="${current_title// /}"
  if [[ "$current_title" != "untitled" && "$current_title" != "auto" ]]; then
    return
  fi

  python3 -c "
import sys, re
file_path = sys.argv[1]
fallback = sys.argv[2]

with open(file_path) as f:
    text = f.read()

# Extract all user turns from the entire conversation
user_contents = []
for match in re.finditer(r'\n## [^\n]*👤 User\n\n(.*?)(?=\n> \*\*Tool\*\*|\n### |\n---\n\n|\n## |$)', text, re.DOTALL):
    user_contents.append(match.group(1).strip())

combined = ' '.join(user_contents) if user_contents else fallback
combined = re.sub(r'\`\`\`[\s\S]*?\`\`\`', '', combined)
combined = re.sub(r'\`[^\`]+\`', '', combined)
combined = combined.replace('\n', ' ').strip()

if not combined:
    title = 'code snippet'
    description = 'Shared a code snippet'
else:
    words = re.findall(r'[\w\-]+', combined)
    title = ' '.join(words[:6])[:50] or 'code snippet'
    description = combined[:140]

text = re.sub(r'^# Super Session: .+$', f'# Super Session: {title}', text, flags=re.M)

if re.search(r'^\*\*Description:\*\* ', text, flags=re.M):
    text = re.sub(r'^\*\*Description:\*\* .+$', f'**Description:** {description}', text, flags=re.M)
else:
    text = re.sub(r'^(\*\*File:\*\* .+)$', r'\1\n**Description:** ' + description, text, flags=re.M)

with open(file_path, 'w') as f:
    f.write(text)
" "$file" "$content"
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
      _session_update_header "$file" "$content"
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
  grep -v '^---$' "$file" 2>/dev/null | tail -n "$n" || true
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
    codex)              _inject_to_file "$root/AGENTS.md"  ;;
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


# ─── Transcript saving ────────────────────────────────────────────────────────

_transcript_dir() {
  echo "$(_super_base_dir)/transcripts"
}

session_save_transcript() {
  # Save rolling transcript as JSONL
  local session_file="$(_super_session_file)"
  [[ -f "$session_file" ]] || return
  
  local transcript_dir="$(_transcript_dir)"
  mkdir -p "$transcript_dir"
  
  local transcript_file="$transcript_dir/$(basename "$session_file" .md).jsonl"
  
  # Convert markdown session to JSONL format
  python3 - "$session_file" "$transcript_file" << 'PYEOF'
import sys, json, re
from datetime import datetime

session_file = sys.argv[1]
transcript_file = sys.argv[2]

entries = []
with open(session_file) as f:
    content = f.read()

# Parse turns (simplified)
for match in re.finditer(r'## \[(.*?)\].*?User\n\n(.*?)(?=\n---|\Z)', content, re.DOTALL):
    cli_ts = match.group(1)
    user_content = match.group(2).strip()
    entries.append({
        "role": "user",
        "content": user_content,
        "cli": cli_ts.split()[0] if ' ' in cli_ts else cli_ts,
        "timestamp": datetime.now().isoformat()
    })

# Write JSONL
with open(transcript_file, 'w') as f:
    for entry in entries:
        f.write(json.dumps(entry) + '\n')
PYEOF
  _log "Saved transcript → $transcript_file"
}

session_save_final_transcript() {
  # Save complete transcript on session end
  local session_file="$(_super_session_file)"
  [[ -f "$session_file" ]] || return
  
  local transcript_dir="$(_transcript_dir)"
  mkdir -p "$transcript_dir"
  
  local final_file="$transcript_dir/$(basename "$session_file" .md)-final.md"
  cp "$session_file" "$final_file"
  _log "Saved final transcript → $final_file"
}

# ─── Session cleanup ──────────────────────────────────────────────────────────

session_cleanup_old() {
  local max_age="${1:-7}"
  local sessions_dir="$(_super_sessions_dir)"
  [[ -d "$sessions_dir" ]] || return
  
  local count=0
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    local mtime; mtime="$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)"
    local age=$(( ($(date +%s) - mtime) / 86400 ))
    if [[ $age -gt $max_age ]]; then
      rm "$f"
      count=$((count + 1))
    fi
  done < <(find "$sessions_dir" -name "*.md" -type f 2>/dev/null)
  
  [[ $count -gt 0 ]] && _log "Cleaned up $count old session(s)"
}
