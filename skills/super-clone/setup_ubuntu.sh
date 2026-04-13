#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$(pwd)}"
ENV_LOCAL="$PROJECT_DIR/.env.local"
SOURCES_MD="$PROJECT_DIR/sources.md"
BASE="super"
BASE_MACHINE="${BASE}-base"

[ -f "$ENV_LOCAL" ] || { echo "Missing $ENV_LOCAL" >&2; exit 1; }
command -v orb &>/dev/null || { echo "Install OrbStack first" >&2; exit 1; }

orb_exists() { orb list 2>/dev/null | awk '{print $1}' | grep -qx "$1"; }

# Ensure base machine exists with pre-installed dependencies
if ! orb_exists "$BASE_MACHINE"; then
  echo "Base machine '$BASE_MACHINE' not found. Creating..."
  orb create ubuntu "$BASE_MACHINE"
  orb -m "$BASE_MACHINE" bash -lc '
    set -euo pipefail
    sudo apt-get update && sudo apt-get install -y git curl
    ARCH=$(uname -m)
    case "$ARCH" in
      x86_64) NODE_ARCH="linux-x64" ;;
      aarch64|arm64) NODE_ARCH="linux-arm64" ;;
      *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
    esac
    NODE_VERSION="20.19.0"
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${NODE_ARCH}.tar.gz" | \
      sudo tar -xz -C /usr/local --strip-components=1
  '
  orb stop "$BASE_MACHINE"
  echo "Base machine '$BASE_MACHINE' created."
fi

# Find a unique machine name
MACHINE="$BASE"
if orb_exists "$MACHINE"; then
  i=2
  while orb_exists "$BASE-$i"; do ((i++)); done
  MACHINE="$BASE-$i"
fi

echo "Cloning '$BASE_MACHINE' to '$MACHINE'..."
orb clone "$BASE_MACHINE" "$MACHINE"
orb start "$MACHINE"

orb -m "$MACHINE" bash -c 'mkdir -p ~/project'
orb push -m "$MACHINE" "$ENV_LOCAL" project/.env.local
if [ -f "$SOURCES_MD" ]; then
  orb push -m "$MACHINE" "$SOURCES_MD" project/sources.md
fi

orb -m "$MACHINE" bash -lc '
  set -euo pipefail
  SUPER_HOME="$HOME/.super"
  rm -rf "$SUPER_HOME"
  git clone https://github.com/smnbss/super "$SUPER_HOME"
  if ! grep -q "$SUPER_HOME" "$HOME/.bashrc" 2>/dev/null; then
    echo "export PATH=\"$SUPER_HOME:\$PATH\"" >> "$HOME/.bashrc"
  fi
  export PATH="$HOME/.local/bin:$SUPER_HOME:$PATH"
  cd "$HOME/project"
  super install --all
'

echo "Done. Machine: $MACHINE"
