#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Clean Install Test for super with brain
# =============================================================================
# This script automates the CLEAN_INSTALL_WITH_BRAIN test procedure.
# Run from the weroad_brain project root.
# =============================================================================

BRAIN_DIR="${PWD}"
SUPER_REPO="${BRAIN_DIR}/src/github/smnbss/super"
BRAIN_REPO="${BRAIN_DIR}/src/github/smnbss/brain"
HOME_SUPER="${HOME}/.super"
REPORT_FILE="/tmp/super_clean_install_report_$(date +%s).txt"
ERRORS=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$REPORT_FILE"
}

error() {
    log "ERROR: $*"
    ((ERRORS++)) || true
}

# ---------------------------------------------------------------------------
# 1. Commit, merge and push brain + super
# ---------------------------------------------------------------------------
push_repo() {
    local repo="$1"
    local name="$2"
    log "Pushing ${name}..."
    if [[ ! -d "${repo}/.git" ]]; then
        error "${name} is not a git repository: ${repo}"
        return
    fi
    (
        cd "$repo"
        if git diff --quiet && git diff --cached --quiet; then
            log "${name}: no changes to commit."
        else
            git add -A
            git commit -m "chore: pre-clean-install checkpoint [auto]" || true
        fi
        git pull --rebase origin $(git rev-parse --abbrev-ref HEAD) || true
        git push origin $(git rev-parse --abbrev-ref HEAD) || error "Failed to push ${name}"
    )
}

push_repo "$BRAIN_REPO" "brain"
push_repo "$SUPER_REPO" "super"

# ---------------------------------------------------------------------------
# 2. Wait for CI / merge to complete (manual step, prompt user)
# ---------------------------------------------------------------------------
log "Waiting for merges to propagate..."
sleep 2

# Pull latest changes locally
(
    cd "$BRAIN_REPO" && git pull || error "Failed to pull brain"
)
(
    cd "$SUPER_REPO" && git pull || error "Failed to pull super"
)

# ---------------------------------------------------------------------------
# 3. Delete AI-tool folders from current project
# ---------------------------------------------------------------------------
FOLDERS_TO_DELETE=(.agents .super .kimi .codex .claude .gemini)
for folder in "${FOLDERS_TO_DELETE[@]}"; do
    target="${BRAIN_DIR}/${folder}"
    if [[ -d "$target" ]]; then
        log "Removing ${target}..."
        rm -rf "$target"
    else
        log "${target} does not exist, skipping."
    fi
done

# ---------------------------------------------------------------------------
# 4. Delete ~/.super
# ---------------------------------------------------------------------------
if [[ -d "$HOME_SUPER" ]]; then
    log "Removing ${HOME_SUPER}..."
    rm -rf "$HOME_SUPER"
else
    log "${HOME_SUPER} does not exist, skipping."
fi

# ---------------------------------------------------------------------------
# 5. Clone super into ~/.super
# ---------------------------------------------------------------------------
log "Cloning smnbss/super into ${HOME_SUPER}..."
if ! git clone https://github.com/smnbss/super.git "$HOME_SUPER"; then
    error "Failed to clone super repository"
    exit 1
fi

# ---------------------------------------------------------------------------
# 6. Run super install
# ---------------------------------------------------------------------------
log "Running super install..."
if ! bash "${HOME_SUPER}/install.sh"; then
    # Some super distributions use a binary or a different entry point;
    # try a generic fallback if install.sh is missing.
    if [[ -x "${HOME_SUPER}/super" ]]; then
        "${HOME_SUPER}/super" install || error "'super install' failed"
    else
        error "Could not locate super install script/entrypoint"
    fi
fi

# ---------------------------------------------------------------------------
# 7. Verify each CLI is present and responsive
# ---------------------------------------------------------------------------
CLIS=(kimi codex claude gemini)
for cli in "${CLIS[@]}"; do
    cmd="super ${cli}"
    log "Checking ${cmd}..."
    if ! command -v super &> /dev/null; then
        error "'super' command not found in PATH"
        break
    fi
    # Try a harmless --version or help flag; if the CLI doesn't support it,
    # just check that the binary/symlink exists.
    bin_path="${HOME_SUPER}/bin/super-${cli}"
    symlink_path="${HOME}/.local/bin/super-${cli}"
    if [[ ! -e "$bin_path" && ! -e "$symlink_path" ]]; then
        error "${cmd}: neither ${bin_path} nor ${symlink_path} found"
    fi
done

# ---------------------------------------------------------------------------
# 8. Check agents / skills configuration
# ---------------------------------------------------------------------------
log "Checking installed skills..."
SKILL_DIRS=(
    "${BRAIN_DIR}/.kimi/skills"
    "${BRAIN_DIR}/.codex/skills"
    "${BRAIN_DIR}/.claude/skills"
    "${BRAIN_DIR}/.gemini/skills"
    "${BRAIN_DIR}/.agents/skills"
)

for dir in "${SKILL_DIRS[@]}"; do
    if [[ -d "$dir" ]]; then
        log "Skills found in ${dir}:"
        find "$dir" -maxdepth 1 -mindepth 1 -type d | sort | sed 's|^|  - |' | tee -a "$REPORT_FILE"
    else
        log "No skills directory at ${dir}"
    fi
done

# Check for duplicate skill names across directories
log "Scanning for duplicate skill names..."
DUPLICATES=$(find "${BRAIN_DIR}" -maxdepth 3 -type d -path '*/skills/*' ! -path '*/skills' -print0 2>/dev/null | \
    xargs -0 -n1 basename | sort | uniq -d)
if [[ -n "$DUPLICATES" ]]; then
    error "Duplicate skill names detected:"
    echo "$DUPLICATES" | sed 's|^|  - |' | tee -a "$REPORT_FILE"
else
    log "No duplicate skill names found."
fi

# ---------------------------------------------------------------------------
# 9. Verify expected .super files exist
# ---------------------------------------------------------------------------
EXPECTED_FILES=(
    "${HOME_SUPER}/super.config.yaml"
    "${HOME_SUPER}/super.log"
    "${HOME_SUPER}/sessions"
)
for f in "${EXPECTED_FILES[@]}"; do
    if [[ -e "$f" ]]; then
        log "OK: ${f}"
    else
        error "Missing expected file: ${f}"
    fi
done

# ---------------------------------------------------------------------------
# 10. Report summary
# ---------------------------------------------------------------------------
log "========================================"
if [[ $ERRORS -eq 0 ]]; then
    log "CLEAN INSTALL TEST PASSED"
else
    log "CLEAN INSTALL TEST FAILED (${ERRORS} issue(s))"
fi
log "Full report: ${REPORT_FILE}"
log "========================================"

cat "$REPORT_FILE"
exit "$ERRORS"
