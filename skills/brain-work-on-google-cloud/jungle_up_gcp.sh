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

JUNGLE_REMOTE_DIR="${JUNGLE_REMOTE_DIR:-\$HOME/jungle}"
JUNGLE_GIT_URL="${JUNGLE_GIT_URL:-git@github.com:weroad/jungle.git}"

latest_golden_image() {
  gcloud --project="$PROJECT_ID" compute machine-images list \
    --filter="name~^${GOLDEN_IMAGE_PREFIX}" --sort-by=~creationTimestamp \
    --format='value(name)' --limit=1 2>/dev/null | grep . || return 1
}

# Postgres creates ~84 databases on first boot and restarts part-way through, so a
# passing pg_isready proves nothing. Gate on the database count instead.
wait_for_databases() {
  local name="$1" i count
  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: wait for postgres to report >= 80 databases on %s\n' "$name"
    return 0
  fi
  for (( i = 0; i < 60; i++ )); do
    count="$(vm_ssh "$name" "docker exec jungle-postgresql.weroad.wr-1 psql -U admin -tAc 'select count(*) from pg_database'" 2>/dev/null | tr -d '[:space:]')"
    if [[ "$count" =~ ^[0-9]+$ ]] && (( count >= 80 )); then
      log "Postgres reports $count databases"
      return 0
    fi
    sleep 10
  done
  die "Postgres never reported at least 80 databases"
}

cmd_golden_build() {
  local stamp image
  stamp="$(date +%Y%m%d)"
  image="${GOLDEN_IMAGE_PREFIX}${stamp}"

  log "Creating the golden instance. This takes 1 to 2 hours."
  vm_create "$GOLDEN_INSTANCE"
  run vm_wait_ssh "$GOLDEN_INSTANCE"

  log "Installing the base tooling"
  run vm_scp "$GOLDEN_INSTANCE" "$SKILL_DIR/files/docker-credential-gcloudadc" "/tmp/docker-credential-gcloudadc"
  run vm_scp "$GOLDEN_INSTANCE" "$SKILL_DIR/files/vm-bootstrap.sh" "/tmp/vm-bootstrap.sh"
  run vm_ssh "$GOLDEN_INSTANCE" "bash /tmp/vm-bootstrap.sh"

  log "Injecting credentials for the build only"
  inject_credentials "$GOLDEN_INSTANCE"

  log "Cloning the jungle and all 72 repos"
  run vm_ssh "$GOLDEN_INSTANCE" "git clone $JUNGLE_GIT_URL $JUNGLE_REMOTE_DIR"
  run vm_ssh "$GOLDEN_INSTANCE" "cd $JUNGLE_REMOTE_DIR && ./bin/repo.init.sh"
  run vm_ssh "$GOLDEN_INSTANCE" "source /tmp/vm-bootstrap.sh && pin_pnpm"

  # hosts.init.sh rewrites tracked compose files. That is forbidden on the laptop
  # and correct here, because the VM tree is disposable.
  run vm_ssh "$GOLDEN_INSTANCE" "cd $JUNGLE_REMOTE_DIR && ./bin/hosts.init.sh"

  log "Pulling the staging images. This is the slow step."
  run vm_ssh "$GOLDEN_INSTANCE" "cd $JUNGLE_REMOTE_DIR && ./bin/staging-images.update.sh"

  log "Restoring the databases"
  run vm_ssh "$GOLDEN_INSTANCE" "cd $JUNGLE_REMOTE_DIR && ./bin/jungle.up.sh reverseproxy.wr"
  run vm_ssh "$GOLDEN_INSTANCE" "cd $JUNGLE_REMOTE_DIR && ./bin/database.up.sh"
  wait_for_databases "$GOLDEN_INSTANCE"
  run vm_ssh "$GOLDEN_INSTANCE" "cd $JUNGLE_REMOTE_DIR && ./bin/database.restore.sh"

  log "Scrubbing credentials before the capture"
  scrub_credentials "$GOLDEN_INSTANCE"

  run gcloud --project="$PROJECT_ID" compute instances stop "$GOLDEN_INSTANCE" --zone="$ZONE"
  run gcloud --project="$PROJECT_ID" compute machine-images create "$image" \
    --source-instance="$GOLDEN_INSTANCE" --source-instance-zone="$ZONE"
  log "Golden image ready: $image"
}

WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PWD/outputs/projects-work-on}"

state_path() { printf '%s/%s/.jungle-vm.json' "$WORKSPACE_ROOT" "$1"; }

state_write() {
  local session="$1"; shift
  local f; f="$(state_path "$session")"
  mkdir -p "$(dirname "$f")"
  {
    printf '{\n'
    local first=1 kv
    for kv in "$@"; do
      [[ $first -eq 1 ]] || printf ',\n'
      printf '  "%s": "%s"' "${kv%%=*}" "${kv#*=}"
      first=0
    done
    printf '\n}\n'
  } > "$f"
}

state_read() {
  local f; f="$(state_path "$1")"
  [[ -f "$f" ]] || return 1
  node -e "const s=require('$f');process.stdout.write(String(s['$2']||''))" 2>/dev/null
}

golden_image_age_days() {
  local stamp="${1#"$GOLDEN_IMAGE_PREFIX"}"
  local when now
  when="$(date -j -f %Y%m%d "$stamp" +%s 2>/dev/null)" || return 1
  now="$(date +%s)"
  printf '%s' $(( (now - when) / 86400 ))
}

cmd_session_create() {
  local repo="$1" session="$2"
  local image name ip age
  image="${GOLDEN_IMAGE_OVERRIDE:-$(latest_golden_image || true)}"
  [[ -n "$image" ]] || die "no golden image found. Run: jungle_up_gcp.sh golden build"

  age="$(golden_image_age_days "$image" 2>/dev/null || echo 0)"
  if [[ "$age" =~ ^[0-9]+$ ]] && (( age > 7 )); then
    log "WARNING: golden image '$image' is older than 7 days ($age days)."
    log "Images and database dumps are stale. Repo code is pulled per session."
  fi

  name="$(instance_name "$repo" "$session")"
  log "Creating '$name' from '$image'"
  vm_create "$name" --from-image "$image"
  run vm_wait_ssh "$name"
  inject_credentials "$name"

  log "Preparing the branch"
  run vm_ssh "$name" "cd $JUNGLE_REMOTE_DIR/$repo && git pull --ff-only"
  run vm_ssh "$name" "cd $JUNGLE_REMOTE_DIR/$repo && git switch -c $session"

  ip="$(vm_ip "$name" 2>/dev/null || echo '')"
  state_write "$session" \
    "vm=$name" "zone=$ZONE" "project=$PROJECT_ID" "ip=$ip" \
    "image=$image" "repo=$repo" "session=$session" "branch=$session" \
    "mount=$HOME/vm/$session"
  log "Session state written to $(state_path "$session")"
}

parse_common_flags() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)       DRY_RUN=1; shift ;;
      --project)       PROJECT_ID="${2:-}"; shift 2 ;;
      --zone)          ZONE="${2:-}"; shift 2 ;;
      --machine-type)  MACHINE_TYPE="${2:-}"; shift 2 ;;
      --disk-size-gb)  DISK_SIZE_GB="${2:-}"; shift 2 ;;
      --source-ip)     SOURCE_IP="${2:-}"; shift 2 ;;
      --refresh)       shift ;;
      *)               die "unknown option: $1" 2 ;;
    esac
  done
  [[ -n "$PROJECT_ID" ]] || PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
  [[ -n "$PROJECT_ID" ]] || die "no GCP project. Pass --project <id>." 2
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
    golden)
      shift
      case "${1:-}" in
        build) shift; parse_common_flags "$@"; cmd_golden_build ;;
        *)     die "usage: golden build [--refresh]" 2 ;;
      esac
      ;;
    session)
      shift
      local sub="${1:-}"; shift || true
      case "$sub" in
        create)
          local repo="${1:-}" sess="${2:-}"
          [[ -n "$repo" && -n "$sess" ]] || die "usage: session create <repo> <session>" 2
          shift 2; parse_common_flags "$@"; cmd_session_create "$repo" "$sess" ;;
        *) die "unknown session verb: ${sub:-<none>}" 2 ;;
      esac
      ;;
    *)                 printf 'error: unknown verb: %s\n' "$verb" >&2; usage >&2; exit 2 ;;
  esac
}

if [[ -z "${JUNGLE_UP_GCP_LIB:-}" ]]; then
  main "$@"
fi
