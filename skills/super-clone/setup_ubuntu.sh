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
#
# Everything that lives in $SUPER_HOME/super.config.yaml's `system:` + `clis:`
# sections (uv, markitdown, ollama, gws, gcloud, gh, claude, codex, gemini)
# gets baked in here. `super install` on each clone then short-circuits every
# `check:` and only runs the per-project work (hooks, skills, MCPs, context
# files) — cutting per-clone time from ~5 min to under a minute.
#
# When you add a new static dep to super.config.yaml, add the same install
# snippet here too and nuke ~/.orbstack/machines/super-base to rebuild.
if ! orb_exists "$BASE_MACHINE"; then
  echo "Base machine '$BASE_MACHINE' not found. Creating..."
  orb create ubuntu "$BASE_MACHINE"
  orb -m "$BASE_MACHINE" bash -lc '
    set -euo pipefail

    # --- Bootstrap apt + node --------------------------------------------
    sudo apt-get update
    # Split into two calls: apt-transport-https is a transitional package
    # that has been removed in Ubuntu 25.10 questing. When passed in the
    # same apt-get install invocation alongside other packages, apt
    # silently drops the whole group. Splitting avoids that footgun.
    sudo apt-get install -y git curl wget zstd ca-certificates
    # gnupg pulls in /usr/bin/gpg as a dependency; install separately so
    # a failure surfaces clearly instead of being hidden.
    sudo apt-get install -y gnupg

    ARCH=$(uname -m)
    case "$ARCH" in
      x86_64)        NODE_ARCH="linux-x64";        GWS_TARGET="x86_64-unknown-linux-gnu" ;;
      aarch64|arm64) NODE_ARCH="linux-arm64";      GWS_TARGET="aarch64-unknown-linux-gnu" ;;
      *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
    esac

    NODE_VERSION="20.19.0"
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${NODE_ARCH}.tar.gz" | \
      sudo tar -xz -C /usr/local --strip-components=1
    # Make the Node global prefix user-writable so `npm install -g` works
    # without sudo for gemini/codex and any future global installs.
    sudo chown -R "$(id -u):$(id -g)" /usr/local/lib/node_modules /usr/local/bin /usr/local/include /usr/local/share

    mkdir -p "$HOME/.local/bin"

    # --- System prereqs baked in ------------------------------------------

    # uv (Astral)
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

    # markitdown[all] — docx/pdf/xlsx/pptx support via extras
    uv tool install --force "markitdown[all]"

    # ollama
    curl -fsSL https://ollama.com/install.sh | sh

    # gws (Google Workspace CLI) — prebuilt Linux tarball
    tmpgws=$(mktemp -d)
    curl -fsSL "https://github.com/googleworkspace/cli/releases/latest/download/google-workspace-cli-${GWS_TARGET}.tar.gz" | tar -xz -C "$tmpgws"
    install -m 0755 "$tmpgws/gws" "$HOME/.local/bin/gws"
    rm -rf "$tmpgws"

    # gcloud + bq (google-cloud-cli)
    # Drop the ASCII-armored key straight into /etc/apt/trusted.gpg.d/
    # with a .asc extension. apt has parsed ASCII-armored keys from that
    # directory natively since 20.04 so we never invoke gpg ourselves.
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
      sudo tee /etc/apt/trusted.gpg.d/cloud.google.asc >/dev/null
    echo "deb https://packages.cloud.google.com/apt cloud-sdk main" | \
      sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y google-cloud-cli

    # gh (GitHub CLI)
    sudo mkdir -p -m 755 /etc/apt/keyrings
    wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
      sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
    sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
      sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y gh

    # --- CLIs baked in ----------------------------------------------------

    # Claude Code (official installer → ~/.local/bin/claude)
    curl -fsSL https://claude.ai/install.sh | bash

    # Gemini + Codex via npm (global prefix is now user-writable)
    npm install -g @google/gemini-cli @openai/codex
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

orb -m "$MACHINE" bash -c 'mkdir -p ~/brain'
orb push -m "$MACHINE" "$ENV_LOCAL" brain/.env.local
if [ -f "$SOURCES_MD" ]; then
  orb push -m "$MACHINE" "$SOURCES_MD" brain/sources.md
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
  cd "$HOME/brain"
  super install --all
'

echo "Done. Machine: $MACHINE"
