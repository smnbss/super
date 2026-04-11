#!/bin/bash
# SuperCLI Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/simonebasso/supercli/main/install.sh | bash

set -e

REPO="simonebasso/supercli"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.supercli}"
VERSION="${1:-latest}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
  echo -e "${GREEN}[supercli]${NC} $1"
}

warn() {
  echo -e "${YELLOW}[supercli]${NC} $1"
}

error() {
  echo -e "${RED}[supercli]${NC} $1" >&2
  exit 1
}

# Check dependencies
command -v curl >/dev/null 2>&1 || error "curl is required but not installed"
command -v tar >/dev/null 2>&1 || error "tar is required but not installed"

# Check bash version (need 4+ for associative arrays)
BASH_MAJOR=${BASH_VERSION%%.*}
if [ "$BASH_MAJOR" -lt 4 ]; then
  warn "macOS ships with bash 3.x. You need bash 4+ for supercli."
  warn "Install with: brew install bash"
  exit 1
fi

# Determine download URL
if [ "$VERSION" = "latest" ]; then
  # Get actual latest version from GitHub API
  log "Fetching latest version..."
  VERSION=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | \
    grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
  VERSION=${VERSION#v}
  log "Latest version: $VERSION"
else
  VERSION="${VERSION#v}"
fi

URL="https://github.com/$REPO/releases/download/v${VERSION}/supercli-${VERSION}.tar.gz"

# Download and extract
log "Installing supercli v$VERSION to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

curl -fsSL "$URL" | tar -xz -C "$INSTALL_DIR" --strip-components=0

# Make executable
chmod +x "$INSTALL_DIR/supercli"
chmod +x "$INSTALL_DIR/hooks"/*/*.sh 2>/dev/null || true

# Check if in PATH
if ! echo "$PATH" | grep -q "$INSTALL_DIR"; then
  SHELL_NAME=$(basename "$SHELL")
  case "$SHELL_NAME" in
    zsh) RC_FILE="$HOME/.zshrc" ;;
    bash) RC_FILE="$HOME/.bashrc" ;;
    *) RC_FILE="$HOME/.profile" ;;
  esac
  
  warn "Add supercli to your PATH by running:"
  echo ""
  echo "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> $RC_FILE"
  echo "  source $RC_FILE"
  echo ""
fi

log "SuperCLI v$VERSION installed successfully!"
log "Run 'supercli --help' to get started"

# Check for CLIs
log "Detected CLIs:"
for cli in claude gemini codex kimi; do
  if command -v "$cli" >/dev/null 2>&1; then
    echo "  ✓ $cli"
  else
    echo "  ✗ $cli (not found)"
  fi
done
