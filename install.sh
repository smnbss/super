#!/bin/bash
# SuperCLI Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/smnbss/super/main/install.sh | bash

set -e

REPO="smnbss/super"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.super}"
VERSION="${1:-latest}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
  echo -e "${GREEN}[super]${NC} $1"
}

warn() {
  echo -e "${YELLOW}[super]${NC} $1"
}

error() {
  echo -e "${RED}[super]${NC} $1" >&2
  exit 1
}

# Check dependencies
command -v curl >/dev/null 2>&1 || error "curl is required but not installed"
command -v tar >/dev/null 2>&1 || error "tar is required but not installed"

# Check bash version (need 4+ for associative arrays)
BASH_MAJOR=${BASH_VERSION%%.*}
if [ "$BASH_MAJOR" -lt 4 ]; then
  warn "macOS ships with bash 3.x. You need bash 4+ for super."
  warn "Install with: brew install bash"
  exit 1
fi

# Determine download URL
if [ "$VERSION" = "latest" ]; then
  # Get actual latest version from GitHub API
  log "Fetching latest version..."
  VERSION=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null | \
    grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/') || true
  VERSION=${VERSION#v}
  log "Latest version: $VERSION"
else
  VERSION="${VERSION#v}"
fi

URL="https://github.com/$REPO/releases/download/v${VERSION}/super-${VERSION}.tar.gz"

# Download and extract
log "Installing super v$VERSION to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

if [ -n "$VERSION" ] && curl -fsSL "$URL" 2>/dev/null | tar -xz -C "$INSTALL_DIR" --strip-components=0; then
  log "Installed from release tarball."
else
  warn "Release tarball not found or download failed."
  # Fallback: install from local clone if available
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [ -f "$SCRIPT_DIR/super" ] && [ -f "$SCRIPT_DIR/super.mjs" ]; then
    log "Installing from local source ($SCRIPT_DIR)..."
    cp -r "$SCRIPT_DIR"/super "$SCRIPT_DIR"/super.mjs "$SCRIPT_DIR"/lib "$SCRIPT_DIR"/hooks "$SCRIPT_DIR"/skills "$SCRIPT_DIR"/tests "$SCRIPT_DIR"/README.md "$SCRIPT_DIR"/VERSION "$SCRIPT_DIR"/super.config.yaml "$SCRIPT_DIR"/package.json "$SCRIPT_DIR"/package-lock.json "$INSTALL_DIR"/ 2>/dev/null || true
  else
    # Final fallback: clone repo and copy files
    log "Cloning $REPO and installing from source..."
    TMP_DIR=$(mktemp -d)
    git clone --depth 1 "https://github.com/$REPO.git" "$TMP_DIR"
    cp -r "$TMP_DIR"/super "$TMP_DIR"/super.mjs "$TMP_DIR"/lib "$TMP_DIR"/hooks "$TMP_DIR"/skills "$TMP_DIR"/tests "$TMP_DIR"/README.md "$TMP_DIR"/VERSION "$TMP_DIR"/super.config.yaml "$TMP_DIR"/package.json "$TMP_DIR"/package-lock.json "$INSTALL_DIR"/ 2>/dev/null || true
    rm -rf "$TMP_DIR"
  fi
fi

# Make executable
chmod +x "$INSTALL_DIR/super"
chmod +x "$INSTALL_DIR/hooks"/*/*.sh 2>/dev/null || true
chmod +x "$INSTALL_DIR/skills"/*/*.sh 2>/dev/null || true

# Check if in PATH
if ! echo "$PATH" | grep -q "$INSTALL_DIR"; then
  SHELL_NAME=$(basename "$SHELL")
  case "$SHELL_NAME" in
    zsh) RC_FILE="$HOME/.zshrc" ;;
    bash) RC_FILE="$HOME/.bashrc" ;;
    *) RC_FILE="$HOME/.profile" ;;
  esac
  
  warn "Add super to your PATH by running:"
  echo ""
  echo "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> $RC_FILE"
  echo "  source $RC_FILE"
  echo ""
fi

log "SuperCLI installed successfully!"
log "Run 'super --help' to get started"

# Check for CLIs
log "Detected CLIs:"
for cli in claude gemini codex; do
  if command -v "$cli" >/dev/null 2>&1; then
    echo "  ✓ $cli"
  else
    echo "  ✗ $cli (not found)"
  fi
done
