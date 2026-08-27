#!/usr/bin/env bash
# wr-cloud jungle health check — idempotent, safe to re-run.
#
# dockerd is NOT supervised here, and /etc/hosts gets wiped. Both faults give the
# identical symptom: every endpoint returns 000. This script repairs both.
#
# Run from the jungle root (/home/user/jungle).
#
# Uses 0.0.0.0, matching bin/hosts.init.sh:25. Seeding 127.0.0.1 instead makes a
# later run of that script append a duplicate entry for all 86 domains.
# Uses bin/hosts.sh, NOT bin/hosts.init.sh — that one rewrites tracked compose files.

set -uo pipefail

if ! docker info >/dev/null 2>&1; then
  echo "dockerd is down — restarting"
  dockerd >/tmp/dockerd.log 2>&1 &
  for _ in $(seq 1 30); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
fi
docker info >/dev/null 2>&1 && echo "dockerd: up" || { echo "dockerd: FAILED, see /tmp/dockerd.log"; exit 1; }

if [ ! -f bin/hosts.sh ]; then
  echo "bin/hosts.sh not found — run this from the jungle root"
  exit 1
fi

# shellcheck disable=SC1091
source bin/hosts.sh

added=0
for d in "${DOMAINS[@]}"; do
  if ! grep -qE "^0\.0\.0\.0[[:space:]]+$d\$" /etc/hosts; then
    echo "0.0.0.0 $d" >> /etc/hosts
    added=$((added + 1))
  fi
done
echo "/etc/hosts: ${#DOMAINS[@]} domains expected, $added added"
