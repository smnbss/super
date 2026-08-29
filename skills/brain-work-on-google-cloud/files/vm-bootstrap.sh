#!/usr/bin/env bash
# vm-bootstrap.sh — runs ON the GCP VM. Installs only what jungle/bin/*.sh needs.
#
# Measured 2026-08-27 from github/weroad/jungle/bin/*.sh:
#   git 172 · docker 42 · curl 9 · node 8 · pnpm 5 · gcloud 3
# Plus tmux and claude-code, which the jungle does not need but the detached
# agent does.
# The "op" match in that grep is the word "no-op" in a comment. There is no
# 1Password dependency. Nothing else belongs here.
#
# Claude runs ON this VM under tmux. It does NOT need the super bootstrap or the
# brain repo — a context pack is shipped per session instead.
set -euo pipefail

JUNGLE_DIR="${JUNGLE_DIR:-$HOME/jungle}"

install_base() {
  echo "==> apt base"
  sudo apt-get update -qq
  sudo apt-get install -y -qq ca-certificates curl git gnupg

  echo "==> Docker CE, under systemd"
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  local arch codename
  arch="$(dpkg --print-architecture)"
  codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$arch" "$codename" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"

  echo "==> Node 22 and corepack"
  # ⚠️ Node 20 is too old. Measured 2026-08-27: corepack's default pnpm (11.24.0)
  #    crashes on Node 20 with ERR_UNKNOWN_BUILTIN_MODULE, which reads as a broken
  #    install rather than a version mismatch.
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y -qq nodejs
  sudo corepack enable

  # ⚠️ ASSERT THE MAJOR VERSION. Ubuntu 24.04 ships nodejs 20, so if the nodesource step
  #    above fails the apt install silently succeeds with the WRONG Node, and the build
  #    captures an image nobody questions until pnpm breaks inside it.
  #    jungle-golden-20260827 shipped Node 20 exactly this way. Measured 2026-08-29.
  node_major="$(node -v 2>/dev/null | sed -e 's/^v//' -e 's/\..*//')"
  if [ "${node_major:-0}" -lt 22 ]; then
    echo "FATAL: node is $(node -v 2>/dev/null || echo absent), expected 22 or newer." >&2
    echo "The nodesource repository did not take. Check /etc/apt/sources.list.d/nodesource.sources." >&2
    exit 1
  fi
  echo "    node $(node -v)"

  echo "==> Google Cloud CLI"
  if [ ! -d /opt/google-cloud-sdk ]; then
    curl -fsSL -o /tmp/gcloud.tar.gz \
      https://storage.googleapis.com/cloud-sdk-release/google-cloud-cli-linux-x86_64.tar.gz
    sudo tar -xzf /tmp/gcloud.tar.gz -C /opt
    sudo /opt/google-cloud-sdk/install.sh --quiet --usage-reporting=false \
      --command-completion=false --path-update=false
  fi
  for b in gcloud gsutil bq; do
    [ -x "/opt/google-cloud-sdk/bin/$b" ] && sudo ln -sfn "/opt/google-cloud-sdk/bin/$b" "/usr/local/bin/$b"
  done

  echo "==> tmux and claude-code"
  # ⚠️ Claude runs ON this VM, detached under tmux, so work continues while the
  #    operator's laptop is closed. That requirement is why the agent tooling is
  #    here at all — an earlier revision stripped it out on the assumption that
  #    Claude ran on the laptop.
  sudo apt-get install -y -qq tmux
  sudo npm install -g @anthropic-ai/claude-code

  echo "==> Artifact Registry credential helper"
  sudo install -m 0755 /tmp/docker-credential-gcloudadc /usr/local/bin/docker-credential-gcloudadc
  mkdir -p "$HOME/.docker"
  printf '%s\n' '{ "credHelpers": { "europe-docker.pkg.dev": "gcloudadc", "pkg.dev": "gcloudadc" } }' \
    > "$HOME/.docker/config.json"
}

# ⚠️ MEASURED 2026-08-27, correcting an earlier assumption in this file: the jungle
#    root package.json declares NO `packageManager` and NO `engines`. Its whole
#    dependency set is chalk, handlebars, js-yaml, lodash and nodemon. So the jungle
#    root installs with plain `npm install` and needs no pnpm at all.
#
#    pnpm still matters, but INSIDE the service repos, and those install inside
#    their own containers. The MINIMUM_RELEASE_AGE_VIOLATION trap belongs there,
#    not here.
install_jungle_deps() {
  echo "==> jungle root dependencies (npm, not pnpm)"
  ( cd "$JUNGLE_DIR" && npm install --silent )
}

# Executing runs the install. Sourcing only defines the functions, so `golden
# build` can source this file later just to call pin_pnpm.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  install_base
  echo "vm-bootstrap done"
fi
