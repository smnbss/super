#!/usr/bin/env bash
# jungle_up_gcp.sh — create and manage per-session GCP VMs running a WeRoad jungle stack.
#
# ⚠️ This script deliberately does NOT call super-clone-in-gcp/setup_gcp.sh. It
#    reimplements instance creation, public-IP detection, the IP-scoped firewall
#    rule and the SSH wait. Two copies of that logic now exist and will drift.
#    See SKILL.md, "Why this duplicates setup_gcp.sh".
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEFAULT_IMAGE_FAMILY="ubuntu-2404-lts-amd64"
DEFAULT_IMAGE_PROJECT="ubuntu-os-cloud"
DEFAULT_MACHINE_TYPE="e2-standard-8"
DEFAULT_DISK_SIZE_GB="200"
DEFAULT_ZONE="europe-west1-b"
GOLDEN_INSTANCE="jungle-golden"
GOLDEN_IMAGE_PREFIX="jungle-golden-"
FIREWALL_RULE="jungle-session-access"
NETWORK_TAG="jungle-session"

DRY_RUN="${DRY_RUN:-}"
PROJECT_ID="${PROJECT_ID:-}"
ZONE="${ZONE:-$DEFAULT_ZONE}"
MACHINE_TYPE="${MACHINE_TYPE:-$DEFAULT_MACHINE_TYPE}"
DISK_SIZE_GB="${DISK_SIZE_GB:-$DEFAULT_DISK_SIZE_GB}"

log() { printf '  %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$1" >&2; exit "${2:-1}"; }

run() {
  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: %s\n' "$*"
    return 0
  fi
  "$@"
}

slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-\{1,\}//' -e 's/-\{1,\}$//'
}

instance_name() {
  local n
  n="jungle-$(slugify "$1")-$(slugify "$2")"
  n="${n:0:63}"
  n="${n%-}"
  [[ "$n" =~ ^[a-z] ]] || n="j${n}"
  printf '%s' "$n"
}

usage() {
  cat <<'USAGE'
jungle_up_gcp.sh — per-session GCP VMs running a WeRoad jungle stack

  golden build [--refresh]              build or rebuild the golden machine image
  session create <repo> <session>       clone the image, start one service stack
  session list                          show sessions, uptime and disk cost
  session stop <session>                stop the VM, keep the disk
  session rm <session>                  unmount, verify branch pushed, delete
  session mount <session>               (re)mount the VM at ~/vm/<session>
  session unmount <session>             unmount only
  session refresh-ip <session>          re-scope the firewall to your current IP

Options: --dry-run  --project <id>  --zone <zone>  --machine-type <t>  --disk-size-gb <n>
USAGE
}

main() {
  local verb="${1:-}"
  case "$verb" in
    ""|-h|--help|help) usage; exit 0 ;;
    golden|session)    die "verb '$verb' is not implemented yet" 3 ;;
    *)                 printf 'error: unknown verb: %s\n' "$verb" >&2; usage >&2; exit 2 ;;
  esac
}

if [[ -z "${JUNGLE_UP_GCP_LIB:-}" ]]; then
  main "$@"
fi
