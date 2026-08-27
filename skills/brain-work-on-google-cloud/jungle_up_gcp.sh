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

detect_public_ip() {
  local ip svc
  for svc in https://api.ipify.org https://ifconfig.me https://icanhazip.com; do
    ip="$(curl -4 -fsSL --max-time 5 "$svc" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
      printf '%s' "$ip"
      return 0
    fi
  done
  return 1
}

# Resolve the caller's IP into a /32, or abort. There is no open-world fallback.
resolve_source_cidr() {
  if [[ -n "${SOURCE_IP:-}" ]]; then
    printf '%s' "$SOURCE_IP"
    return 0
  fi
  local ip
  ip="$(detect_public_ip)" \
    || die "cannot detect your public IPv4. Pass --source-ip <cidr>. Refusing to open the firewall to the world."
  printf '%s/32' "$ip"
}

ensure_firewall_rule() {
  local cidr="$1"
  if gcloud --project="$PROJECT_ID" compute firewall-rules describe "$FIREWALL_RULE" \
       --format="value(name)" >/dev/null 2>&1; then
    log "Updating firewall rule '$FIREWALL_RULE' → $cidr"
    run gcloud --project="$PROJECT_ID" compute firewall-rules update "$FIREWALL_RULE" \
      --source-ranges="$cidr" >/dev/null \
      || die "failed to update firewall rule '$FIREWALL_RULE'"
  else
    log "Creating firewall rule '$FIREWALL_RULE' (tcp:22,80,443 from $cidr)"
    run gcloud --project="$PROJECT_ID" compute firewall-rules create "$FIREWALL_RULE" \
      --allow=tcp:22,80,443 \
      --source-ranges="$cidr" \
      --target-tags="$NETWORK_TAG" \
      --description="jungle session VMs: SSH and HTTP from one operator IP" >/dev/null \
      || die "failed to create firewall rule '$FIREWALL_RULE'"
  fi
}

vm_create() {
  local name="$1"; shift
  local from_image=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --from-image) from_image="${2:-}"; shift 2 ;;
      *) die "vm_create: unknown option $1" ;;
    esac
  done

  ensure_firewall_rule "$(resolve_source_cidr)"

  if [[ -n "$from_image" ]]; then
    run gcloud --project="$PROJECT_ID" compute instances create "$name" \
      --zone="$ZONE" \
      --source-machine-image="$from_image" \
      --tags="$NETWORK_TAG" \
      || die "failed to create '$name' from image '$from_image'"
  else
    run gcloud --project="$PROJECT_ID" compute instances create "$name" \
      --zone="$ZONE" \
      --machine-type="$MACHINE_TYPE" \
      --boot-disk-size="${DISK_SIZE_GB}GB" \
      --boot-disk-type=pd-balanced \
      --image-family="$DEFAULT_IMAGE_FAMILY" \
      --image-project="$DEFAULT_IMAGE_PROJECT" \
      --tags="$NETWORK_TAG" \
      || die "failed to create instance '$name'"
  fi
}

vm_ip() {
  gcloud --project="$PROJECT_ID" compute instances describe "$1" --zone="$ZONE" \
    --format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null
}

vm_ssh() {
  local name="$1"; shift
  gcloud --project="$PROJECT_ID" compute ssh "$name" --zone="$ZONE" --command "$*"
}

vm_scp() {
  local name="$1" src="$2" dst="$3"
  gcloud --project="$PROJECT_ID" compute scp --zone="$ZONE" "$src" "${name}:${dst}"
}

vm_wait_ssh() {
  local name="$1"
  local tries="${SSH_WAIT_TRIES:-40}"
  local nap="${SSH_WAIT_SLEEP:-5}"
  local i
  for (( i = 0; i < tries; i++ )); do
    if vm_ssh "$name" true >/dev/null 2>&1; then
      log "SSH is ready on '$name'"
      return 0
    fi
    [[ "$nap" == "0" ]] || sleep "$nap"
  done
  die "'$name' did not become reachable over SSH after $tries attempts"
}

# The three credentials the jungle needs on the VM. Injected per session VM, never
# baked into the golden image: a machine image is a copyable artifact, and a refresh
# token inside one cannot be rotated by deleting a box.
CRED_ADC="${CRED_ADC:-$HOME/.config/gcloud/application_default_credentials.json}"
CRED_NPMRC="${CRED_NPMRC:-$HOME/.npmrc}"
CRED_COMPOSER="${CRED_COMPOSER:-$HOME/.composer/auth.json}"

inject_credentials() {
  local name="$1"
  if [[ -z "${SKIP_CRED_CHECK:-}" ]]; then
    [[ -f "$CRED_ADC" ]] \
      || die "missing $CRED_ADC — run: gcloud auth application-default login"
    [[ -f "$CRED_NPMRC" ]] \
      || die "missing $CRED_NPMRC — needed for @weroad/* npm packages"
    [[ -f "$CRED_COMPOSER" ]] \
      || die "missing $CRED_COMPOSER — needed for private weroad/* composer packages"
  fi

  run vm_ssh "$name" "mkdir -p ~/.config/gcloud ~/.composer ~/.docker"
  run vm_scp "$name" "$CRED_ADC"      "~/.config/gcloud/application_default_credentials.json"
  run vm_scp "$name" "$CRED_NPMRC"    "~/.npmrc"
  run vm_scp "$name" "$CRED_COMPOSER" "~/.composer/auth.json"
  run vm_ssh "$name" "printf '%s\\n' '{ \"credHelpers\": { \"europe-docker.pkg.dev\": \"gcloudadc\", \"pkg.dev\": \"gcloudadc\" } }' > ~/.docker/config.json"
  run vm_ssh "$name" "chmod 600 ~/.config/gcloud/application_default_credentials.json ~/.npmrc ~/.composer/auth.json"
}

# ⚠️ Deletes files only. NEVER call `gcloud auth application-default revoke` here.
#    The VM ADC holds the SAME refresh token as the operator's laptop, so revoking
#    it server-side destroys their local credentials as well. A test in
#    tests/test_jungle_up_gcp.mjs fails the build if that call ever appears.
scrub_credentials() {
  local name="$1"
  run vm_ssh "$name" "rm -f ~/.config/gcloud/application_default_credentials.json ~/.npmrc ~/.composer/auth.json ~/.docker/config.json"
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
