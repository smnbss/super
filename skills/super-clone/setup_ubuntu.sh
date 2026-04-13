#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$(pwd)}"
ENV_LOCAL="$PROJECT_DIR/.env.local"
SOURCES_MD="$PROJECT_DIR/sources.md"
BASE="super"
BASE_IMAGE="${BASE}-base"

[ -f "$ENV_LOCAL" ] || { echo "Missing $ENV_LOCAL" >&2; exit 1; }
command -v orb &>/dev/null || { echo "Install OrbStack first" >&2; exit 1; }

orb_exists() { orb list 2>/dev/null | awk '{print $1}' | grep -qx "$1"; }

# Ensure base image exists with pre-installed dependencies
if ! orb_exists "$BASE_IMAGE"; then
  echo "Base image '$BASE_IMAGE' not found. Creating..."
  orb create ubuntu "$BASE_IMAGE"
  orb -m "$BASE_IMAGE" bash -lc '
    set -euo pipefail
    sudo apt-get update && sudo apt-get install -y git nodejs npm
  '
  orb stop "$BASE_IMAGE"
  echo "Base image '$BASE_IMAGE' created."
fi

# Find a unique machine name
MACHINE="$BASE"
if orb_exists "$MACHINE"; then
  i=2
  while orb_exists "$BASE-$i"; do ((i++)); done
  MACHINE="$BASE-$i"
fi

echo "Cloning '$BASE_IMAGE' to '$MACHINE'..."
orb clone "$BASE_IMAGE" "$MACHINE"
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
  export PATH="$HOME/.local/bin:$SUPER_HOME:$PATH"
  cd "$HOME/project"
  super install --all
'

echo "Done. Machine: $MACHINE"
