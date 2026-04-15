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
FOLDERS_TO_DELETE=(.agents .super .kimi .codex .claude .gemini .venv)
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
# 6. Run super install (from clone source, fallback for missing releases)
# ---------------------------------------------------------------------------
log "Running super install script..."
if ! bash "${HOME_SUPER}/install.sh"; then
    error "super install script failed"
    exit 1
fi

# Ensure ~/.super is on PATH for the rest of this script
export PATH="${HOME_SUPER}:${PATH}"

# ---------------------------------------------------------------------------
# 7. Run super install inside the brain project
# ---------------------------------------------------------------------------
log "Running 'super install --all' in brain project (non-interactive)..."
cd "$BRAIN_DIR"
if ! super install --all; then
    error "'super install --all' failed in brain project"
fi

# ---------------------------------------------------------------------------
# 8. Verify super is present and responsive
# ---------------------------------------------------------------------------
log "Checking super binary..."
if ! command -v super &> /dev/null; then
    error "'super' command not found in PATH"
else
    log "OK: super is in PATH at $(command -v super)"
fi

if [[ ! -x "${HOME_SUPER}/super" ]]; then
    error "${HOME_SUPER}/super is not executable"
else
    log "OK: ${HOME_SUPER}/super is executable"
fi

# Verify that known CLIs are detected by super
log "Checking detected CLIs..."
for cli in kimi codex claude gemini; do
    if command -v "$cli" &> /dev/null; then
        log "  ✓ $cli installed"
    else
        log "  ✗ $cli (not found)"
    fi
done

# ---------------------------------------------------------------------------
# 9. Check agents / skills configuration
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
# 10. Verify expected .super files exist in the brain project
# ---------------------------------------------------------------------------
EXPECTED_FILES=(
    "${BRAIN_DIR}/.super/super.config.yaml"
)
EXPECTED_DIRS=(
    "${BRAIN_DIR}/.super/sessions"
)

for f in "${EXPECTED_FILES[@]}"; do
    if [[ -e "$f" ]]; then
        log "OK: ${f}"
    else
        error "Missing expected file: ${f}"
    fi
done

for d in "${EXPECTED_DIRS[@]}"; do
    if [[ -d "$d" ]]; then
        log "OK: ${d}"
    else
        error "Missing expected directory: ${d}"
    fi
done

# ---------------------------------------------------------------------------
# 11. Report summary
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
