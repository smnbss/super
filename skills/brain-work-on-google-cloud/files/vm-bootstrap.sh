#!/usr/bin/env bash
# vm-bootstrap.sh — runs ON the GCP VM. Installs only what jungle/bin/*.sh needs.
#
# Measured 2026-08-27 from github/weroad/jungle/bin/*.sh:
#   git 172 · docker 42 · curl 9 · node 8 · pnpm 5 · gcloud 3
# The "op" match in that grep is the word "no-op" in a comment. There is no
# 1Password dependency. Nothing else belongs here.
#
# Claude runs on the operator's laptop, so this VM needs no agent tooling, no
# super bootstrap and no brain files.
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

  echo "==> Node and corepack"
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y -qq nodejs
  sudo corepack enable

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

  echo "==> Artifact Registry credential helper"
  sudo install -m 0755 /tmp/docker-credential-gcloudadc /usr/local/bin/docker-credential-gcloudadc
  mkdir -p "$HOME/.docker"
  printf '%s\n' '{ "credHelpers": { "europe-docker.pkg.dev": "gcloudadc", "pkg.dev": "gcloudadc" } }' \
    > "$HOME/.docker/config.json"
}

# pnpm is pinned to the jungle lockfile's packageManager field. A corepack-pulled
# newer pnpm fails the Docker build with MINIMUM_RELEASE_AGE_VIOLATION.
#
# Called by golden build AFTER the jungle clone exists. Calling it earlier would
# read a package.json that is not there yet.
pin_pnpm() {
  local pm
  pm="$(node -p "require('$JUNGLE_DIR/package.json').packageManager || ''" 2>/dev/null || echo '')"
  if [ -n "$pm" ]; then
    echo "==> pinning $pm"
    sudo corepack prepare "$pm" --activate
  else
    echo "==> no packageManager field found. Leaving the corepack default." >&2
  fi
}

# Executing runs the install. Sourcing only defines the functions, so `golden
# build` can source this file later just to call pin_pnpm.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  install_base
  echo "vm-bootstrap done"
fi
