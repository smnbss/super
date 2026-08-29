#!/usr/bin/env bash
# jungle_up_gcp.sh — create and manage per-session GCP VMs running a WeRoad jungle stack.
#
# ⚠️ This script deliberately does NOT call brain-clone-in-gcp/setup_gcp.sh. It
#    reimplements instance creation, public-IP detection, the IP-scoped firewall
#    rule and the SSH wait. Two copies of that logic now exist and will drift.
#    See SKILL.md, "Why this duplicates setup_gcp.sh".
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

DEFAULT_IMAGE_FAMILY="ubuntu-2404-lts-amd64"
DEFAULT_IMAGE_PROJECT="ubuntu-os-cloud"
DEFAULT_MACHINE_TYPE="e2-standard-8"
DEFAULT_DISK_SIZE_GB="200"
DEFAULT_ZONE="europe-west1-b"
GOLDEN_INSTANCE="jungle-golden"
GOLDEN_IMAGE_PREFIX="jungle-golden-"
FIREWALL_RULE="jungle-session-access"
NETWORK_TAG="jungle-session"
AGENT_TOKEN_SECRET="${AGENT_TOKEN_SECRET:-claude-agent-token}"
# ⚠️ A VM AGENT HAS NO MCP SERVERS AT ALL, and this surprises everyone.
#    claude.ai connectors — Linear included — are an ACCOUNT feature delivered by the
#    Claude app. The `claude` CLI reads MCP servers from ~/.claude.json and .mcp.json
#    only, so CLAUDE_CODE_OAUTH_TOKEN buys model access and NOTHING else. `claude mcp
#    list` on a fresh session VM prints "No MCP servers configured". Measured 2026-08-29.
#
#    So a cloud agent cannot read its own Linear issue. The workaround is an API key
#    from Secret Manager, exported as LINEAR_API_KEY, used against the GraphQL API at
#    https://api.linear.app/graphql with the key as a BARE Authorization header.
#
# ⚠️ A LINEAR API KEY ACTS AS THE OPERATOR ACROSS THE WHOLE WORKSPACE, read AND write.
#    It is not scoped to a team or a project. Treat it as the operator's identity.
LINEAR_KEY_SECRET="${LINEAR_KEY_SECRET:-wr-linear-api-key}"
LINEAR_EMAIL_SECRET="${LINEAR_EMAIL_SECRET:-wr-linear-user-email}"
# ⚠️ Scopes are fixed at instance creation. The DEFAULT compute scopes do NOT
#    include Secret Manager, so a VM created without this cannot fetch the agent
#    token however the IAM is set. Changing it later needs the instance STOPPED.
VM_SCOPES="${VM_SCOPES:-https://www.googleapis.com/auth/cloud-platform}"
# ⚠️ THE SERVICE ACCOUNT IS FIXED AT INSTANCE CREATION, exactly like the scopes above.
#    A VM created without this keeps the DEFAULT COMPUTE account, which carries
#    roles/editor on the whole project — a throwaway dev box able to delete other
#    people's instances. Changing it afterwards needs the instance stopped.
#
#    claude-cloud-vm@ already existed for this and nothing used it. It holds
#    secretmanager.secretAccessor and artifactregistry.reader, and NOT roles/editor.
#    Measured 2026-08-29. See SIM-67.
#
#    ⚠️ Its secretAccessor is PROJECT-level, so it can read every secret. That is the
#    starting point, not the end state — SIM-68 moves to one secret per key with
#    per-secret bindings.
VM_SERVICE_ACCOUNT="${VM_SERVICE_ACCOUNT:-claude-cloud-vm@weroad-test-simon.iam.gserviceaccount.com}"

DRY_RUN="${DRY_RUN:-}"
REFRESH="${REFRESH:-}"
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

# Like run(), but for a command whose FAILURE must stop the script. run() always
# returns 0, so `run cmd || die` can never fire and silently reports success.
#
# ⚠️ Not hypothetical: `session create` used `run vm_ssh ... git switch -c`, so a
#    branch that was never created still produced a state file claiming it, and an
#    exit code of 0. See SIM-63.
run_checked() {
  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: %s\n' "$*" >&2
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
  local ip existing
  if ip="$(detect_public_ip)"; then
    printf '%s/32' "$ip"
    return 0
  fi
  # ⚠️ A TRANSIENT NETWORK BLIP IS NOT A REASON TO ABORT A BUILD. On 2026-08-29 a wifi
  #    switch made all three IP services unreachable for a few seconds, and `golden build
  #    --refresh` died — AFTER it had already deleted the golden instance, destroying 36
  #    restored databases for nothing. If the firewall rule already carries a /32, reuse
  #    it: it is the last address that provably worked. Still no open-world fallback.
  existing="$(gcloud --project="$PROJECT_ID" compute firewall-rules describe "$FIREWALL_RULE" \
    --format='value(sourceRanges.list())' 2>/dev/null | tr -d '[:space:]')"
  if [[ "$existing" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]]; then
    log "Cannot detect your public IPv4. Reusing the firewall's current $existing."
    printf '%s' "$existing"
    return 0
  fi
  die "cannot detect your public IPv4. Pass --source-ip <cidr>. Refusing to open the firewall to the world."
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
      --allow=tcp:22,tcp:80,tcp:443 \
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
      --scopes="$VM_SCOPES" \
      --service-account="$VM_SERVICE_ACCOUNT" \
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
      --scopes="$VM_SCOPES" \
      --service-account="$VM_SERVICE_ACCOUNT" \
      --tags="$NETWORK_TAG" \
      || die "failed to create instance '$name'"
  fi
}

vm_ip() {
  gcloud --project="$PROJECT_ID" compute instances describe "$1" --zone="$ZONE" \
    --format='value(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null
}

# ⚠️ A changed public IP breaks SSH and HTTP together, and the only symptom is a
#    timeout. Seen TWICE on 2026-08-27 on a mobile hotspot. Rather than make the
#    operator diagnose it, retry once behind an automatic firewall refresh.
vm_ssh() {
  local name="$1"; shift
  # ⚠️ Capture the status with a bare assignment. `local rc=$?` after an `if`
  #    reads the status of the `if`, and a separate `local rc` line resets $? to
  #    the status of `local` itself. Both make a failed SSH look successful.
  local rc
  gcloud --project="$PROJECT_ID" compute ssh "$name" --zone="$ZONE" --command "$*"
  rc=$?
  [[ $rc -eq 0 ]] && return 0
  [[ -n "${NO_IP_AUTOREFRESH:-}" ]] && return $rc
  [[ -n "${_IP_REFRESHED:-}" ]] && return $rc
  log "SSH failed. Refreshing the firewall to your current IP and retrying once."
  _IP_REFRESHED=1
  # In a subshell: ensure_firewall_rule calls die on failure, which would exit the
  # whole script. A refresh that fails should give up and report the ORIGINAL error.
  ( ensure_firewall_rule "$(resolve_source_cidr)" ) || return $rc
  gcloud --project="$PROJECT_ID" compute ssh "$name" --zone="$ZONE" --command "$*"
}

vm_scp() {
  local name="$1" src="$2" dst="$3"
  gcloud --project="$PROJECT_ID" compute scp --zone="$ZONE" "$src" "${name}:${dst}"
}

vm_wait_ssh() {
  local name="$1"
  # A probe. Auto-refresh here would turn every poll into a firewall write.
  local NO_IP_AUTOREFRESH=1
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

  # ⚠️ Docker creates a DIRECTORY at a bind-mount source that does not exist. Once
  #    ~/.composer/auth.json is a directory, composer 404s on private packages and
  #    the laravel container dies with an OCI "not a directory" mount error. An scp
  #    into that path lands the file INSIDE the directory and looks like it worked.
  #    Remove the paths first so each is unambiguously a file. Seen live 2026-08-27.
  run vm_ssh "$name" "mkdir -p ~/.config/gcloud ~/.composer ~/.docker && rm -rf ~/.composer/auth.json ~/.npmrc ~/.config/gcloud/application_default_credentials.json"
  run vm_scp "$name" "$CRED_ADC"      "~/.config/gcloud/application_default_credentials.json"
  run vm_scp "$name" "$CRED_NPMRC"    "~/.npmrc"
  run vm_scp "$name" "$CRED_COMPOSER" "~/.composer/auth.json"
  run vm_ssh "$name" "printf '%s\\n' '{ \"credHelpers\": { \"europe-docker.pkg.dev\": \"gcloudadc\", \"pkg.dev\": \"gcloudadc\" } }' > ~/.docker/config.json"
  run vm_ssh "$name" "chmod 600 ~/.config/gcloud/application_default_credentials.json ~/.npmrc ~/.composer/auth.json"
  inject_github_auth "$name"
}

# jungle/bin/repos.sh lists all 72 repos as git@github.com: SSH URLs, and the VM
# has no GitHub SSH key. Rewrite those URLs to token HTTPS instead.
#
# The token is written to a local file and copied. It never appears in a command
# line, so it reaches neither the dry-run transcript nor the remote process list.
github_token() {
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then printf '%s' "$GITHUB_TOKEN"; return 0; fi
  grep -oE '_authToken=.*' "$CRED_NPMRC" 2>/dev/null \
    | head -1 | cut -d= -f2- | tr -d '"'"'"' \r' || return 1
}

inject_github_auth() {
  local name="$1" token tmp
  token="$(github_token)"
  if [[ -z "$token" ]]; then
    log "WARNING: no GitHub token found. repo.init.sh will fail on private repos."
    return 0
  fi
  tmp="$(mktemp)"
  chmod 600 "$tmp"
  printf 'https://x-access-token:%s@github.com\n' "$token" > "$tmp"
  run vm_scp "$name" "$tmp" "~/.git-credentials"
  rm -f "$tmp"
  run vm_ssh "$name" "chmod 600 ~/.git-credentials && git config --global credential.helper store && git config --global url.'https://github.com/'.insteadOf 'git@github.com:'"

  # ⚠️ Without an identity `git commit` fails on the VM, and an agent that hits this
  #    INFERS one from the surrounding history rather than stopping — so commits land
  #    under a guessed name. Seen on the HD-24 session, 2026-08-29.
  local gname gmail
  gname="$(git config --global user.name 2>/dev/null || true)"
  gmail="$(git config --global user.email 2>/dev/null || true)"
  if [[ -n "$gname" && -n "$gmail" ]]; then
    run vm_ssh "$name" "git config --global user.name '$gname' && git config --global user.email '$gmail'"
  else
    log "WARNING: no global git identity on this laptop. Commits on the VM will fail."
  fi
}

# ⚠️ Deletes files only. NEVER call `gcloud auth application-default revoke` here.
#    The VM ADC holds the SAME refresh token as the operator's laptop, so revoking
#    it server-side destroys their local credentials as well. A test in
#    tests/test_jungle_up_gcp.mjs fails the build if that call ever appears.
scrub_credentials() {
  local name="$1"
  # ⚠️ ~/.claude-env WAS MISSING FROM THIS LIST, so jungle-golden-20260827 shipped a
  #    live LiteLLM API token, and so did every VM built from it. A machine image is a
  #    copyable artifact. ANY credential file this script writes must also be listed
  #    here. See SIM-63.
  run vm_ssh "$name" "rm -f ~/.config/gcloud/application_default_credentials.json ~/.npmrc ~/.composer/auth.json ~/.docker/config.json ~/.git-credentials ~/.gitconfig ~/.claude-env"
}

JUNGLE_REMOTE_DIR="${JUNGLE_REMOTE_DIR:-\$HOME/jungle}"
JUNGLE_GIT_URL="${JUNGLE_GIT_URL:-git@github.com:weroad/jungle.git}"

latest_golden_image() {
  gcloud --project="$PROJECT_ID" compute machine-images list \
    --filter="name~^${GOLDEN_IMAGE_PREFIX}" --sort-by=~creationTimestamp \
    --format='value(name)' --limit=1 2>/dev/null | grep . || return 1
}

# ⚠️ wait_for_databases moved INTO files/golden-build-remote.sh, which is where the
#    database restore now happens. Gate on the DATABASE COUNT, never pg_isready:
#    postgres creates ~84 databases on first boot and restarts part-way through, so a
#    passing pg_isready proves nothing and yields "Connection refused" mid-restore.


# ⚠️ The repo count is now reported by files/golden-build-remote.sh, which does the
#    cloning. It is deliberately NOT fatal: compose.yaml is generated up front and
#    parses with most build contexts absent, so a partial clone is a slow first
#    session, never a broken one.


# Polls the detached remote build. Survives a dropped laptop: every probe is a fresh SSH,
# and a failed probe is retried rather than treated as a failed build.
# Polls the detached remote build.
#
# ⚠️ THREE STATES, AND THE FIRST VERSION COLLAPSED THEM INTO ONE. It treated an empty
#    reply as "no answer from the VM" whether SSH had failed or the log was simply quiet,
#    and it had no way to notice the remote script had DIED. On 2026-08-29 it spun for 85
#    minutes reporting "no answer" while SSH worked perfectly and the build was long dead.
#
#      unreachable  — SSH itself failed. The LAPTOP lost the VM; the build does not care.
#                     Keep polling.
#      running      — pid file names a live process. Report progress.
#      finished     — the DONE marker exists. Success or failure; read the log to see.
#
#    A pid file that names no live process, with no DONE marker, means the script was
#    killed. Say so and stop, rather than waiting for a marker that will never arrive.
golden_wait_remote() {
  local i probe rc unreachable=0 last_size="" stalled=0
  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: wait for the remote golden build to finish\n'
    return 0
  fi
  for (( i = 0; i < 960; i++ )); do
    probe="$(vm_ssh "$GOLDEN_INSTANCE" "
      test -f ~/golden-build.done && echo MARKER=done
      if [ -f ~/golden-build.pid ] && kill -0 \"\$(cat ~/golden-build.pid)\" 2>/dev/null; then
        echo PROC=alive
      else
        echo PROC=gone
      fi
      echo SIZE=\$(stat -c %s ~/golden-build.log 2>/dev/null || echo 0)
      echo LAST=\$(tail -1 ~/golden-build.log 2>/dev/null | tr -d '\r' | cut -c1-70)
    " 2>/dev/null)"
    rc=$?

    if (( rc != 0 )) || [[ -z "$probe" ]]; then
      unreachable=$(( unreachable + 1 ))
      (( unreachable % 10 == 0 )) \
        && log "  (cannot reach the VM — $unreachable probes. The build is detached and continues.)"
      sleep 30
      continue
    fi
    unreachable=0

    if [[ "$probe" == *MARKER=done* ]]; then
      log "Remote build phase finished"
      vm_ssh "$GOLDEN_INSTANCE" "tail -5 ~/golden-build.log" 2>/dev/null | sed 's/^/    /' >&2
      return 0
    fi

    local size; size="$(printf '%s' "$probe" | sed -n 's/^SIZE=//p')"
    if [[ "$probe" == *PROC=gone* ]]; then
      log "ERROR: the remote build process is gone and wrote no completion marker."
      log "It was killed rather than finishing. Read ~/golden-build.log on '$GOLDEN_INSTANCE':"
      vm_ssh "$GOLDEN_INSTANCE" "tail -8 ~/golden-build.log" 2>/dev/null | sed 's/^/    /' >&2
      return 1
    fi

    # A live process whose log has not grown for 40 minutes is stuck, not working.
    if [[ "$size" == "$last_size" ]]; then
      stalled=$(( stalled + 1 ))
      if (( stalled == 80 )); then
        log "WARNING: the log has not grown in ~40 minutes. The build may be stuck."
        log "Still polling, but check ~/golden-build.log on '$GOLDEN_INSTANCE'."
      fi
    else
      stalled=0
      last_size="$size"
      (( i % 5 == 0 )) && log "  … $(printf '%s' "$probe" | sed -n 's/^LAST=//p')"
    fi
    sleep 30
  done
  log "ERROR: the remote build did not finish within 8 hours."
  return 1
}

cmd_golden_build() {
  local stamp image
  stamp="$(date +%Y%m%d)"
  image="${GOLDEN_IMAGE_PREFIX}${stamp}"

  # ⚠️ RESOLVE THE FIREWALL CIDR BEFORE DESTROYING ANYTHING. On 2026-08-29 --refresh
  #    deleted the golden instance and THEN failed on an undetectable public IP during a
  #    wifi switch, throwing away 36 restored databases for a transient blip. Anything
  #    that can fail must fail before the delete.
  local _cidr; _cidr="$(resolve_source_cidr)" || exit 1
  ensure_firewall_rule "$_cidr"

  # ⚠️ --refresh was PARSED AND DISCARDED, so a rebuild collided with the jungle-golden
  #    instance left by the previous build and failed at the first step. See SIM-63.
  if gcloud --project="$PROJECT_ID" compute instances describe "$GOLDEN_INSTANCE" \
       --zone="$ZONE" >/dev/null 2>&1; then
    [[ -n "$REFRESH" ]] \
      || die "instance '$GOLDEN_INSTANCE' already exists. Re-run with --refresh to replace it."
    log "Deleting the previous golden instance"
    run gcloud --project="$PROJECT_ID" compute instances delete "$GOLDEN_INSTANCE" \
      --zone="$ZONE" --quiet
  fi

  log "Creating the golden instance. This takes 1 to 2 hours."
  vm_create "$GOLDEN_INSTANCE"
  run vm_wait_ssh "$GOLDEN_INSTANCE"

  log "Installing the base tooling"
  run vm_scp "$GOLDEN_INSTANCE" "$SKILL_DIR/files/docker-credential-gcloudadc" "/tmp/docker-credential-gcloudadc"
  run vm_scp "$GOLDEN_INSTANCE" "$SKILL_DIR/files/vm-bootstrap.sh" "/tmp/vm-bootstrap.sh"
  run vm_ssh "$GOLDEN_INSTANCE" "bash /tmp/vm-bootstrap.sh"

  log "Injecting credentials for the build only"
  inject_credentials "$GOLDEN_INSTANCE"

  # ⚠️ THE LONG HALF RUNS ON THE VM, DETACHED. It used to be a sequence of live
  #    `gcloud compute ssh` calls from the laptop, so a 1-2 hour build depended on the
  #    laptop staying awake, online and on the SAME IP throughout. It died three times on
  #    2026-08-29 — terminal exited, instance stopped, and a wifi change that broke every
  #    SSH pipe and left the laptop hung for 1h42m on a dead connection. See SIM-63.
  #
  #    Now the laptop only polls. A dropped laptop no longer kills the build: reconnect,
  #    run `golden build --refresh` again and it picks up, or just watch the log.
  log "Starting the long build phase ON the VM, detached. The laptop only polls."
  run vm_scp "$GOLDEN_INSTANCE" "$SKILL_DIR/files/golden-build-remote.sh" "/tmp/golden-build-remote.sh"
  run vm_ssh "$GOLDEN_INSTANCE" "chmod +x /tmp/golden-build-remote.sh && rm -f ~/golden-build.done && setsid nohup /tmp/golden-build-remote.sh '$JUNGLE_GIT_URL' >/dev/null 2>&1 < /dev/null & sleep 3; echo launched"

  golden_wait_remote || die "the remote build phase did not finish. Read ~/golden-build.log on '$GOLDEN_INSTANCE'."

  log "Scrubbing credentials before the capture"
  scrub_credentials "$GOLDEN_INSTANCE"

  run gcloud --project="$PROJECT_ID" compute instances stop "$GOLDEN_INSTANCE" --zone="$ZONE"
  run gcloud --project="$PROJECT_ID" compute machine-images create "$image" \
    --source-instance="$GOLDEN_INSTANCE" --source-instance-zone="$ZONE"
  log "Golden image ready: $image"
}

WORKSPACE_ROOT="${WORKSPACE_ROOT:-$PWD/outputs/projects-work-on}"

# The workspace is <repo|preset>/<session>/, the same shape brain-work-on uses, so
# one session's notes, plan, .linear.json and .jungle-vm.json sit together and a repo
# with several sessions groups them. `create` knows the scope; every other verb takes
# only <session>, so resolve the directory by searching for it.
#
# Depth 3 is the current layout. Depth 2 is the pre-2026-08-29 flat one, still
# resolved so an existing session keeps working after the change.
state_path() {          # <session> [<repo|preset>]
  local session="$1" scope="${2:-}"
  if [[ -n "$scope" ]]; then
    printf '%s/%s/%s/.jungle-vm.json' "$WORKSPACE_ROOT" "$scope" "$session"; return 0
  fi
  local hits n
  hits="$(find "$WORKSPACE_ROOT" -mindepth 2 -maxdepth 3 -type f -name .jungle-vm.json \
            -path "*/$session/.jungle-vm.json" 2>/dev/null)"
  n="$(printf '%s' "$hits" | grep -c . || true)"
  # Two scopes can carry the same session name. Guessing which one would point a
  # destructive verb at the wrong VM, so refuse instead.
  if (( n > 1 )); then
    printf 'session %s exists under several scopes:\n%s\n' "$session" "$hits" >&2
    printf 'Remove the duplicate, or address it by path.\n' >&2
    return 1
  fi
  printf '%s' "$hits"
}

state_write() {
  local scope="$1" session="$2"; shift 2
  local f; f="$(state_path "$session" "$scope")"
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
  # require() resolves a bare relative path as a MODULE, not a file, and throws a
  # stack trace instead of returning empty. WORKSPACE_ROOT defaults to an absolute
  # path, but an operator can export a relative one.
  [[ "$f" == /* ]] || f="$PWD/$f"
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

  inject_agent_auth "$name" \
    || die "no usable agent credential on '$name'. Fix the secret, then: session rm $session"
  # Order matters: inject_agent_auth rewrites ~/.claude-env, this one appends to it.
  inject_linear_auth "$name"

  local services
  services="$(ensure_session_repos "$name" "$repo")" \
    || die "no compose service matches '$repo'. Check it against: docker compose -f compose.yaml config --services"

  log "Preparing the branch"
  run_checked vm_ssh "$name" "cd $JUNGLE_REMOTE_DIR/$repo && git switch -c $session" \
    || die "cannot create branch '$session' in $JUNGLE_REMOTE_DIR/$repo on '$name'"

  ship_context_pack "$name" "$repo"
  stack_up "$name" "$repo" "$services"

  ip="$(vm_ip "$name" 2>/dev/null || echo '')"
  state_write "$repo" "$session" \
    "vm=$name" "zone=$ZONE" "project=$PROJECT_ID" "ip=$ip" \
    "image=$image" "repo=$repo" "session=$session" "branch=$session" \
    "mount=$HOME/vm/$session"
  log "Session state written to $(state_path "$session" "$repo")"

  # ⚠️ The state file must be written BEFORE this point: chrome_command reads the IP
  #    back out of it.
  local host; host="$(primary_host "$services")"
  if [[ -z "$DRY_RUN" ]]; then
    verify_render "$name" "$host"
  fi
  log "Open the stack with:"
  chrome_command "$session" "$host"
}

# Fuse-T licence position, recorded because the two sources disagree:
#   fuse-t.org  — "Free for personal use. Commercial license available for
#                  embedding and shipping Fuse-T in a product."
#   License.txt — "For commercial use or/and bundling with commercial software,
#                  the software vendor has to obtain a commercial license."
# Simone chose the website reading on 2026-08-27. This skill never installs
# Fuse-T silently, and always names mutagen (MIT) as the alternative.
mount_preflight() {
  command -v sshfs >/dev/null 2>&1 && return 0
  cat >&2 <<'PREFLIGHT'
error: sshfs is not installed. This skill mounts each session VM with Fuse-T.

  brew install macos-fuse-t/homebrew-cask/fuse-t
  brew install macos-fuse-t/homebrew-cask/fuse-t-sshfs

Licence, before you install:
  fuse-t.org says  "Free for personal use. Commercial license available for
                    embedding and shipping Fuse-T in a product."
  License.txt says "For commercial use or/and bundling with commercial software,
                    the software vendor has to obtain a commercial license."
  The two readings differ on whether work use needs a licence. Decide before you
  install. mutagen (MIT, no such question) is the alternative — see SKILL.md,
  "Swapping the mount for a sync".
PREFLIGHT
  return 1
}

# ⚠️ stack_up and derive_services were defined and called by NOTHING, so `session create`
#    finished with a VM that served nothing, while SKILL.md documented nine measured
#    behaviours of a function no verb ran. See SIM-63.
#
#    `session create` now calls stack_up itself. This verb re-runs it — what you want
#    after `session stop`, after a compose change, or when a container died.
cmd_session_up() {
  local session="$1" vm repo services ip
  vm="$(state_read "$session" vm)" || die "no session '$session'. Run: session create"
  repo="$(state_read "$session" repo)"

  # ⚠️ A STOPPED VM COMES BACK ON A DIFFERENT EXTERNAL IP. Nothing refreshed it, so the
  #    state file kept the old address and `chrome_command` handed out a dead one —
  #    which looks exactly like the stack being broken. Seen live 2026-08-29 after a
  #    stop/start: 207.175.117.220 became 34.14.73.195. Re-read it every time.
  ip="$(vm_ip "$vm" 2>/dev/null || echo '')"
  if [[ -n "$ip" && "$ip" != "$(state_read "$session" ip)" ]]; then
    log "External IP changed to $ip — updating the session state"
    state_write "$repo" "$session" \
      "vm=$vm" "zone=$ZONE" "project=$PROJECT_ID" "ip=$ip" \
      "image=$(state_read "$session" image)" "repo=$repo" "session=$session" \
      "branch=$(state_read "$session" branch)" "mount=$(state_read "$session" mount)"
    ensure_firewall_rule "$(resolve_source_cidr)"
  fi
  services="$(ensure_session_repos "$vm" "$repo")" || die "no compose service matches '$repo'"
  stack_up "$vm" "$repo" "$services"
  log "Stack up on '$vm':"
  printf '%s\n' "$services" | sed 's/^/    /' >&2
}

# ⚠️ Databases were the one thing NOTHING refreshed. `golden build` restored them once, at
#    image-build time, and `session create` never touched them — so a session VM served
#    data frozen on the day the image was built, and the only cure was a 1-2 hour rebuild.
#    The >7-day warning in cmd_session_create says exactly this. See SIM-63.
#
#    This restores ONLY the databases the session's own services use. A beye session needs
#    api_beye: one database, not 84.
#
# ⚠️⚠️ A RESTORE REPLACES THE DATABASE. Everything created on the VM since the image was
#      built is DESTROYED — uploaded dashboards, seeded fixtures, an agent's test data.
#      There is no merge and no prompt. Run `REFRESH_DB_LIST=1 session refresh-db <s>`
#      first to see which databases would be replaced.
cmd_session_refresh_db() {
  local session="$1"; shift
  local vm repo dbs
  vm="$(state_read "$session" vm)" || die "no session '$session'. Run: session create"
  repo="$(state_read "$session" repo)"

  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: refresh databases for %s on %s\n' "$repo" "$vm"
    return 0
  fi

  run vm_scp "$vm" "$SKILL_DIR/files/refresh-db.sh" "/tmp/refresh-db.sh" \
    || die "cannot copy refresh-db.sh to '$vm'"
  # Explicit database names, when given, skip derivation entirely.
  dbs="$(vm_ssh "$vm" "REFRESH_DB_LIST='${REFRESH_DB_LIST:-}' bash /tmp/refresh-db.sh '$repo' $*")" \
    || die "database refresh failed on '$vm'"
  if [[ "${REFRESH_DB_LIST:-}" == "1" ]]; then
    log "Would refresh on '$vm' (nothing changed):"
  else
    log "Refreshed on '$vm':"
  fi
  printf '%s\n' "$dbs" | sed 's/^/    /' >&2
}

cmd_session_mount() {
  local session="$1" vm ip mp
  mount_preflight || return 1
  vm="$(state_read "$session" vm)" || die "no session '$session'. Run: session create"
  ip="$(state_read "$session" ip)"
  mp="$(state_read "$session" mount)"
  mkdir -p "$mp"
  run sshfs "${USER}@${ip}:jungle" "$mp" \
    -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3 \
    -o "volname=${session}" \
    -o "IdentityFile=${HOME}/.ssh/google_compute_engine" \
    || die "mount failed for '$session'"
  log "Mounted '$vm' at $mp"
}

cmd_session_unmount() {
  local session="$1" mp
  mp="$(state_read "$session" mount)" || die "no session '$session'"
  run umount "$mp" 2>/dev/null || run diskutil unmount force "$mp" 2>/dev/null || true
  log "Unmounted $mp"
}

# One Chrome instance per session. --user-data-dir is mandatory: without it, `open`
# hands the URL to the running Chrome and you reach the wrong stack.
#
# ⚠️ AND THE PROFILE MUST BE CLOSED FIRST. --host-resolver-rules is read once, at
#    process start. A Chrome already running on this profile keeps its OLD mapping,
#    so `open -na` silently sends you to the previous session's VM and everything
#    looks fine. Seen live 2026-08-27: a request meant for a session VM landed on
#    the golden VM, and only the nginx access log revealed it.
# The service a person opens: neither an API, nor an MCP, nor a php-fpm pool. For beye
# that is beye.weroad.wr, for partner it is partner.weroad.wr.
#
# ⚠️ Falls back to the FIRST service rather than guessing a name. A wrong host here
#    sends the operator to a stack that is not theirs.
primary_host() {
  local services="$1" svc
  for svc in $services; do
    case "$svc" in
      laravel.*|api-*|nest-*|mcp-*) continue ;;
      *) printf '%s' "$svc"; return 0 ;;
    esac
  done
  printf '%s' "$(printf '%s\n' $services | head -1)"
}

# ⚠️ This hardcoded api-partner.weroad.wr, so every session opened the partner URL
#    whatever repo it was for. See SIM-63.
chrome_command() {
  local session="$1" host="$2" ip
  ip="$(state_read "$session" ip)" || die "no session '$session'"
  printf 'pkill -f "user-data-dir=/tmp/chrome-%s" 2>/dev/null; sleep 1; open -na "Google Chrome" --args --user-data-dir=/tmp/chrome-%s --no-first-run --no-default-browser-check --host-resolver-rules="MAP *.weroad.wr %s" "http://%s/"\n' \
    "$session" "$session" "$ip" "$host"
}

# One logical service is often several compose entries. A Laravel API is BOTH
# api-x.weroad.wr (nginx) and its php-fpm sibling. nginx alone returns 502.
# Derive the set from compose. Never guess it.
# ⚠️ derive_services lived here and was called by NOTHING. Its grep is now the first
#    step of files/ensure-repos.sh, which runs ON the VM so that deriving the services
#    and cloning what they build from cannot drift apart. See SIM-63.
#
# Clone or refresh every repo the matching services build from, then print the service
# names on STDOUT. Progress goes to stderr on both sides.
ensure_session_repos() {
  local vm="$1" repo="$2"
  # ⚠️ Nothing may reach STDOUT here except the service names — the caller captures
  #    this with $(...). run() prints its DRY-RUN transcript on stdout, so the dry-run
  #    branch comes FIRST and the scp never runs under it.
  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: ensure repos and derive services for %s\n' "$repo" >&2
    return 0
  fi
  vm_scp "$vm" "$SKILL_DIR/files/ensure-repos.sh" "/tmp/ensure-repos.sh" >&2 \
    || die "cannot copy ensure-repos.sh to '$vm'"
  vm_ssh "$vm" "bash /tmp/ensure-repos.sh '$repo'"
}

# GCE is expected to carry IPv6, so DVO-419 probably does not apply here. Probe.
needs_ipv4_fpm() {
  local vm="$1"
  vm_ssh "$vm" "test -e /proc/net/if_inet6" >/dev/null 2>&1 && return 1
  return 0
}

stack_up() {
  local vm="$1" repo="$2" services="$3"
  local override=""

  if [[ -z "$DRY_RUN" ]] && needs_ipv4_fpm "$vm"; then
    log "No IPv6 on this VM. Mounting the IPv4 php-fpm pool (DVO-419)."
    run vm_scp "$vm" "$SKILL_DIR/files/zz-apko.conf" "/tmp/zz-apko.conf"
    override="-f /tmp/override.yaml"
    run vm_ssh "$vm" "cd $JUNGLE_REMOTE_DIR && printf 'services:\\n' > /tmp/override.yaml && for s in \$(docker compose -f compose.yaml config --services | grep '^laravel\\.'); do printf '  \"%s\":\\n    volumes:\\n      - \"/tmp/zz-apko.conf:/etc/php/php-fpm.d/zz-apko.conf:ro\"\\n' \"\$s\" >> /tmp/override.yaml; done"
  fi

  # ⚠️ jungle binds the reverse proxy to 127.0.0.1:80 (compose.jungle.yaml). On a
  #    remote VM that makes the stack unreachable whatever the firewall says.
  #    Re-publish it on all interfaces. The firewall still limits it to one IP.
  run vm_scp "$vm" "$SKILL_DIR/files/reverseproxy-expose.yaml" "/tmp/reverseproxy-expose.yaml"
  run vm_ssh "$vm" "cd $JUNGLE_REMOTE_DIR && docker compose -f compose.jungle.yaml -f /tmp/reverseproxy-expose.yaml up -d --force-recreate reverseproxy.wr"
  run vm_ssh "$vm" "cd $JUNGLE_REMOTE_DIR && docker compose -f compose.yaml $override up -d --no-deps postgresql.weroad.wr redis.weroad.wr rabbitmq.weroad.wr"
  # ⚠️ ORDER MATTERS. nginx resolves its php-fpm upstream when it PARSES its
  #    config, not on first request. Starting an api-* nginx before its laravel.*
  #    sibling exists gives "host not found in upstream" and a crash loop that no
  #    restart clears. Start every laravel.* first. Seen live 2026-08-27.
  local fpm="" rest=""
  for svc in $services; do
    case "$svc" in
      laravel.*) fpm="$fpm $svc" ;;
      *)         rest="$rest $svc" ;;
    esac
  done
  if [[ -n "$fpm" ]]; then
    run vm_ssh "$vm" "cd $JUNGLE_REMOTE_DIR && docker compose -f compose.yaml $override up -d --build --no-deps $fpm"
  fi
  if [[ -n "$rest" ]]; then
    run vm_ssh "$vm" "cd $JUNGLE_REMOTE_DIR && docker compose -f compose.yaml $override up -d --build --no-deps $rest"
  fi

  # ⚠️ nginx resolves its php-fpm upstream ONCE, at startup. When an api-* nginx
  #    starts before its laravel.* sibling is ready, it caches a dead address and
  #    returns 502 forever, with healthy containers on both sides. Restarting the
  #    nginx is the fix, and it must be automatic — this trap cost two debug
  #    cycles on 2026-08-27.
  restart_nginx_siblings "$vm" "$services"
}

# ⚠️ A laravel.* container reports "Up" long before php-fpm accepts connections —
#    it runs composer install and migrations first, which takes minutes. Restarting
#    the nginx before that finishes just rebuilds the same 502. Wait for the pool.
wait_for_fpm() {
  local vm="$1" svc="$2" i
  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: wait for php-fpm on %s\n' "$svc"
    return 0
  fi
  for (( i = 0; i < 60; i++ )); do
    if vm_ssh "$vm" "docker logs --tail 40 jungle-${svc}-1 2>&1 | grep -q 'ready to handle connections'" >/dev/null 2>&1; then
      log "php-fpm is ready on $svc"
      return 0
    fi
    sleep 10
  done
  log "WARNING: $svc never reported 'ready to handle connections'"
  return 1
}

# Restart every api-* nginx whose laravel.* sibling is in this service set.
restart_nginx_siblings() {
  local vm="$1" services="$2" svc base
  for svc in $services; do
    case "$svc" in
      laravel.*)
        base="${svc#laravel.}"
        wait_for_fpm "$vm" "$svc" || true
        log "Restarting nginx for $base (it resolves the php-fpm upstream at startup)"
        run vm_ssh "$vm" "cd $JUNGLE_REMOTE_DIR && docker compose -f compose.yaml restart $base >/dev/null 2>&1 || true"
        ;;
    esac
  done
}

# A 200 can be an empty shell. Require a body of real size.
verify_render() {
  local vm="$1" host="$2" out code bytes
  out="$(vm_ssh "$vm" "curl -s -o /tmp/render.html -w '%{http_code} %{size_download}' -H 'Host: $host' http://127.0.0.1/")"
  code="${out%% *}"; bytes="${out##* }"
  # ⚠️ A 3xx IS A HEALTHY ANSWER, and treating it as failure rejects every authenticated
  #    stack. beye redirects to /auth/login and on to staging-auth.weroad.io; partner
  #    behaves the same. Measured 2026-08-29.
  case "$code" in
    3??)
      log "$host answered HTTP $code — a redirect, normally the login hand-off. Reachable."
      return 0 ;;
    200)
      if [[ "$bytes" =~ ^[0-9]+$ ]] && (( bytes > 2000 )); then
        log "$host rendered ($bytes bytes)"
        return 0
      fi
      die "$host returned 200 with an empty shell ($bytes bytes). The page did not render." ;;
    *)
      die "$host returned HTTP ${code:-no response}" ;;
  esac
}

# ── The detached agent ──────────────────────────────────────────────────────
# ⚠️ Claude runs ON the VM, inside tmux. That is the whole reason this design
#    exists: the operator closes the laptop and the work continues. A laptop-side
#    agent editing through a mount cannot meet that requirement, because closing
#    the lid suspends the process and drops the mount.
AGENT_TMUX_SESSION="claude"

# Claude on the VM talks to Anthropic DIRECTLY. It does NOT go through WeRoad's
# LiteLLM proxy — that route was removed 2026-08-27 (Cloudflare Access blocks the
# VM, and an Anthropic-compatible endpoint was never verified). Do not reintroduce
# it without testing both.
#
# THE TOKEN NEVER PASSES THROUGH THE OPERATOR'S SHELL HISTORY OR AN AGENT CONTEXT.
# It is created once, straight into Secret Manager, and each VM fetches it itself:
#
#   claude setup-token                      # interactive; prints the token
#   read -rs TOK && printf '%s' "$TOK" | \
#     gcloud secrets create claude-agent-token --data-file=- --project <project>
#
# ⚠️ Do NOT pipe `claude setup-token` straight into the secret. It is interactive,
#    so the pipe captures its banner, URL and ANSI codes instead of the token.
#
# Resolution order:
#   1. CLAUDE_CODE_OAUTH_TOKEN in the environment — for a one-off run.
#   2. ANTHROPIC_API_KEY in the environment — for API-key users.
#   3. Secret Manager, fetched ON the VM by its own service account. Preferred:
#      the token never touches the laptop, and rotation is one command that every
#      future VM picks up with no code change.
inject_agent_auth() {
  local name="$1" tmp
  local oauth="${CLAUDE_CODE_OAUTH_TOKEN:-}"
  local apikey="${ANTHROPIC_API_KEY:-}"

  # ⚠️ PURGE FIRST. Absent, this broke a live run on 2026-08-29: the golden image
  #    bakes a ~/.claude-env pointing at the REMOVED LiteLLM proxy route. Every write
  #    below uses `>`, but a failed fetch writes nothing, so the stale file survived
  #    and the agent used it, failing with "API returned an empty or malformed
  #    response (HTTP 200)". Deleting first means a failure yields NO credential
  #    rather than a wrong one.
  run vm_ssh "$name" "rm -f ~/.claude-env"

  if [[ -n "$oauth" || -n "$apikey" ]]; then
    tmp="$(mktemp)"; chmod 600 "$tmp"
    if [[ -n "$oauth" ]]; then
      printf 'export CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$oauth" > "$tmp"
    else
      printf 'export ANTHROPIC_API_KEY=%s\n' "$apikey" > "$tmp"
    fi
    run vm_scp "$name" "$tmp" "~/.claude-env"
    rm -f "$tmp"
    run vm_ssh "$name" "chmod 600 ~/.claude-env && grep -q claude-env ~/.bashrc || echo '[ -f ~/.claude-env ] && . ~/.claude-env' >> ~/.bashrc"
    return 0
  fi

  fetch_agent_token_from_secret_manager "$name"
}

# The VM reads the secret itself. The value never reaches the laptop.
fetch_agent_token_from_secret_manager() {
  local name="$1"
  run vm_ssh "$name" "set -e
    tok=\$(gcloud secrets versions access latest --secret='$AGENT_TOKEN_SECRET' --project='$PROJECT_ID' 2>/dev/null || true)
    if [ -z \"\$(printf '%s' \"\$tok\" | tr -d '[:space:]')\" ]; then echo 'AGENT_TOKEN_MISSING'; exit 0; fi
    # 'claude setup-token' is INTERACTIVE, so everyone pipes it and the secret ends
    # up holding its banner, URL and ANSI codes instead of the token. Recover the
    # token from inside the blob rather than failing.
    # ⚠️ Strip ANSI but KEEP the line structure, then grep. Collapsing newlines
    #    FIRST welds the next word onto the token — a banner reading
    #    \"<esc>sk-ant-TOKEN<esc>\\nDone.\" yielded \"sk-ant-TOKENDone\", which passes
    #    every check here and then fails at runtime as a bare \"Not logged in\".
    tok=\$(printf '%s' \"\$tok\" | sed -e 's/\\x1b\\[[0-9;?]*[a-zA-Z]//g' \\
          | grep -oE 'sk-ant-[A-Za-z0-9_-]+' | head -1)
    if [ -z \"\$tok\" ]; then echo 'AGENT_TOKEN_MALFORMED'; exit 0; fi
    umask 077
    printf 'export CLAUDE_CODE_OAUTH_TOKEN=%s\\n' \"\$tok\" > ~/.claude-env
    grep -q claude-env ~/.bashrc || echo '[ -f ~/.claude-env ] && . ~/.claude-env' >> ~/.bashrc
    echo AGENT_TOKEN_OK" > /tmp/.agent-token-probe 2>&1
  if grep -q AGENT_TOKEN_OK /tmp/.agent-token-probe 2>/dev/null; then
    rm -f /tmp/.agent-token-probe
    log "Agent token fetched from Secret Manager on the VM"
    return 0
  fi
  if grep -q AGENT_TOKEN_MALFORMED /tmp/.agent-token-probe 2>/dev/null; then
    rm -f /tmp/.agent-token-probe
    log "ERROR: the secret '$AGENT_TOKEN_SECRET' does not hold a token."
    log "It must start with sk-ant- and contain no spaces or escape codes."
    log "\`claude setup-token\` is INTERACTIVE — piping it captures its banner, not"
    log "the token. Run it, read the token it prints, then:"
    log "  read -rs TOK && printf '%s' \"\$TOK\" | \\"
    log "    gcloud secrets versions add $AGENT_TOKEN_SECRET --data-file=- --project $PROJECT_ID"
    return 1
  fi
  rm -f /tmp/.agent-token-probe
  agent_token_help
  return 1
}

# Gives the VM agent Linear access, since it has no MCP servers. See LINEAR_KEY_SECRET.
#
# ⚠️ MUST RUN AFTER inject_agent_auth. That function DELETES ~/.claude-env and rewrites
#    it with `>`. This one appends, so the order is load-bearing.
#
# Non-fatal by design: plenty of sessions never touch Linear.
inject_linear_auth() {
  local name="$1"
  if [[ -n "$DRY_RUN" ]]; then
    printf 'DRY-RUN: fetch %s into ~/.claude-env on %s\n' "$LINEAR_KEY_SECRET" "$name" >&2
    return 0
  fi
  vm_ssh "$name" "set -e
    key=\$(gcloud secrets versions access latest --secret='$LINEAR_KEY_SECRET' --project='$PROJECT_ID' 2>/dev/null | tr -d '\\r\\n')
    mail=\$(gcloud secrets versions access latest --secret='$LINEAR_EMAIL_SECRET' --project='$PROJECT_ID' 2>/dev/null | tr -d '\\r\\n')
    if [ -z \"\$key\" ]; then echo LINEAR_KEY_MISSING; exit 0; fi
    umask 077
    printf 'export LINEAR_API_KEY=%s\\n' \"\$key\" >> ~/.claude-env
    [ -n \"\$mail\" ] && printf 'export LINEAR_USER_EMAIL=%s\\n' \"\$mail\" >> ~/.claude-env
    echo LINEAR_KEY_OK" > /tmp/.linear-probe 2>&1
  if grep -q LINEAR_KEY_OK /tmp/.linear-probe 2>/dev/null; then
    rm -f /tmp/.linear-probe
    log "Linear API key fetched from Secret Manager on the VM"
    return 0
  fi
  rm -f /tmp/.linear-probe
  log "NOTE: no Linear key on '$name'. A cloud agent cannot read its own issue."
  log "Grant the VM service account secretAccessor on '$LINEAR_KEY_SECRET', or pass the"
  log "issue text to the agent as a file instead."
  return 0
}

agent_token_help() {
  cat >&2 <<HELP
  No agent credential available on the VM.

  Create it ONCE, without the token passing through your shell history:

    claude setup-token                      # interactive; prints the token
    read -rs TOK && printf '%s' "\$TOK" | \
      gcloud secrets create $AGENT_TOKEN_SECRET --data-file=- --project $PROJECT_ID && unset TOK

  Do NOT pipe setup-token directly: it is interactive, so the pipe stores its
  banner and colour codes rather than the token.

  Then let the VM service account read it:

    gcloud secrets add-iam-policy-binding $AGENT_TOKEN_SECRET --project $PROJECT_ID \
      --member "serviceAccount:\$(gcloud compute instances describe <vm> --zone $ZONE \
        --project $PROJECT_ID --format='value(serviceAccounts[0].email)')" \
      --role roles/secretmanager.secretAccessor

  To rotate later, add a new version — every future VM picks it up:

    claude setup-token
    read -rs TOK && printf '%s' "\$TOK" | \
      gcloud secrets versions add $AGENT_TOKEN_SECRET --data-file=- --project $PROJECT_ID && unset TOK
HELP
}

# Ship the brain context the VM cannot reach. Claude runs there, and there is no
# gbrain, no service docs and no DEVELOPER.md on that machine.
ship_context_pack() {
  local name="$1" repo="$2" brain_root="${BRAIN_ROOT:-$PWD}"
  local pack; pack="$(mktemp -d)"
  mkdir -p "$pack/services"

  [[ -f "$brain_root/DEVELOPER.md" ]] && cp "$brain_root/DEVELOPER.md" "$pack/"
  local doc
  for doc in "$brain_root"/outputs/services/**/*"$repo"*.agent.md \
             "$brain_root"/outputs/services/*"$repo"*.agent.md; do
    [[ -f "$doc" ]] && cp "$doc" "$pack/services/"
  done

  run vm_ssh "$name" "mkdir -p ~/session-context"
  run vm_scp "$name" "$pack" "~/session-context"
  rm -rf "$pack"
  log "Context pack shipped to ~/session-context"
}

# Start the agent detached. It survives the SSH connection closing, so the work
# continues after the operator closes the laptop.
# ⚠️ Claude Code refuses to honour a workspace's settings until the directory is
#    trusted, and in headless mode it simply reports "Not logged in" and exits.
#    Pre-accept the trust dialog for the working directory.
trust_agent_workspace() {
  local vm="$1" wd="$2"
  run vm_ssh "$vm" "node -e \"
    const fs=require('fs'),p=process.env.HOME+'/.claude.json';
    let j={}; try{ j=JSON.parse(fs.readFileSync(p,'utf8')); }catch(e){}
    j.projects=j.projects||{};
    j.projects['$wd']=Object.assign({},j.projects['$wd'],{hasTrustDialogAccepted:true});
    fs.writeFileSync(p,JSON.stringify(j,null,2));
  \""
}

# Start the agent detached. It survives the SSH connection closing, so the work
# continues after the operator closes the laptop.
#
# ⚠️ Source ~/.claude-env EXPLICITLY. `bash -lc` is a non-interactive login shell,
#    and Ubuntu's ~/.bashrc returns early for non-interactive shells, so the token
#    written there is never loaded. The failure surfaces as "Not logged in" inside
#    tmux while a hand-run `source ~/.claude-env; claude` works perfectly.
cmd_agent_start() {
  local session="$1" prompt="$2" vm repo
  vm="$(state_read "$session" vm)"   || die "no session '$session'"
  repo="$(state_read "$session" repo)"
  local wd="\$HOME/jungle/$repo"
  local wd_literal
  wd_literal="$(vm_ssh "$vm" "echo \$HOME/jungle/$repo" 2>/dev/null | tr -d '\r\n')"

  [[ -n "$wd_literal" ]] && trust_agent_workspace "$vm" "$wd_literal"

  run vm_ssh "$vm" "tmux has-session -t $AGENT_TMUX_SESSION 2>/dev/null && tmux kill-session -t $AGENT_TMUX_SESSION; true"
  run vm_ssh "$vm" "cd $wd && tmux new-session -d -s $AGENT_TMUX_SESSION \"bash -c '. ~/.claude-env; claude --dangerously-skip-permissions -p \\\"$prompt\\\" 2>&1 | tee -a ~/agent.log'\""
  log "Agent started detached on '$vm'. Close the laptop freely."
  log "Read progress with:  session agent log $session"
}

cmd_agent_log() {
  local session="$1" vm
  vm="$(state_read "$session" vm)" || die "no session '$session'"
  vm_ssh "$vm" "tail -n ${AGENT_LOG_LINES:-80} ~/agent.log 2>/dev/null || echo '(no agent log yet)'"
}

cmd_agent_attach() {
  local session="$1" vm zone
  vm="$(state_read "$session" vm)" || die "no session '$session'"
  zone="$(state_read "$session" zone)"
  printf 'gcloud compute ssh %s --zone=%s --project=%s -- -t "tmux attach -t %s"\n' \
    "$vm" "$zone" "$(state_read "$session" project)" "$AGENT_TMUX_SESSION"
}

# The firewall is scoped to ONE address. A laptop that changes network — hotspot,
# office, cafe — loses SSH and HTTP at once, and every command times out with no
# hint that the cause is the firewall. Observed live on 2026-08-27.
cmd_session_refresh_ip() {
  local cidr
  cidr="$(resolve_source_cidr)"
  ensure_firewall_rule "$cidr"
  log "Firewall now allows $cidr"
}

branch_is_pushed() {
  [[ -n "${BRANCH_PUSHED:-}" ]] && return 0
  local vm="$1" repo="$2" branch="$3"
  # A probe guarding a destructive delete. Failure must mean "not pushed",
  # never "retry until it looks pushed".
  local NO_IP_AUTOREFRESH=1
  vm_ssh "$vm" "cd $JUNGLE_REMOTE_DIR/$repo && git rev-parse --verify --quiet origin/$branch" >/dev/null 2>&1
}

cmd_session_list() {
  printf '%-40s %-10s %-26s %s\n' SESSION STATUS CREATED COST
  gcloud --project="$PROJECT_ID" compute instances list \
    --filter="name~^jungle- AND -name:$GOLDEN_INSTANCE" \
    --format='value(name,status,creationTimestamp)' 2>/dev/null \
  | while read -r name status created; do
      printf '%-40s %-10s %-26s %s\n' "$name" "$status" "$created" \
        "~EUR 0.25/h running, ~EUR 18/mo disk"
    done
  printf '\nDelete a finished session with: session rm <session>\n'
}

cmd_session_stop() {
  local session="$1" vm
  vm="$(state_read "$session" vm)" || die "no session '$session'"
  cmd_session_unmount "$session" 2>/dev/null || true
  run gcloud --project="$PROJECT_ID" compute instances stop "$vm" --zone="$ZONE"
  log "Stopped '$vm'. The disk still costs about EUR 18 each month."
}

# ⚠️ Code exists ONLY on the VM. This gate is the only thing between an unpushed
#    branch and permanent loss.
cmd_session_rm() {
  local session="$1" vm repo branch
  vm="$(state_read "$session" vm)" || die "no session '$session'"
  repo="$(state_read "$session" repo)"
  branch="$(state_read "$session" branch)"

  if ! branch_is_pushed "$vm" "$repo" "$branch"; then
    die "branch '$branch' is not pushed to origin. Refusing to delete '$vm'. Push it first:
  gcloud compute ssh $vm --zone=$ZONE --command 'cd ~/jungle/$repo && git push -u origin $branch'"
  fi

  cmd_session_unmount "$session" 2>/dev/null || true
  scrub_credentials "$vm"
  run gcloud --project="$PROJECT_ID" compute instances delete "$vm" --zone="$ZONE" --quiet
  log "Deleted '$vm'. Notes, plans and specs remain in the laptop workspace."
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
      --refresh)       REFRESH=1; shift ;;
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
  session create <repo|preset> <session>  clone the image, start one service stack
  session up <session>                  (re)start that session's stack
  session refresh-db <session> [db...]  re-download and restore only this session's dbs
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
          [[ -n "$repo" && -n "$sess" ]] || die "usage: session create <repo|preset> <session>" 2
          shift 2; parse_common_flags "$@"; cmd_session_create "$repo" "$sess" ;;
        mount)
          local m="${1:-}"; [[ -n "$m" ]] || die "usage: session mount <session>" 2
          shift; parse_common_flags "$@"; cmd_session_mount "$m" ;;
        unmount)
          local u="${1:-}"; [[ -n "$u" ]] || die "usage: session unmount <session>" 2
          shift; parse_common_flags "$@"; cmd_session_unmount "$u" ;;
        up)
          local upn="${1:-}"; [[ -n "$upn" ]] || die "usage: session up <session>" 2
          shift; parse_common_flags "$@"; cmd_session_up "$upn" ;;
        refresh-db)
          local rdn="${1:-}"; [[ -n "$rdn" ]] || die "usage: session refresh-db <session> [db...]" 2
          shift
          # Positional database names come before any flag; split on the first dash.
          local rddbs=()
          while [[ $# -gt 0 && "$1" != --* ]]; do rddbs+=("$1"); shift; done
          parse_common_flags "$@"; cmd_session_refresh_db "$rdn" "${rddbs[@]}" ;;
        list)    parse_common_flags "$@"; cmd_session_list ;;
        stop)
          local st="${1:-}"; [[ -n "$st" ]] || die "usage: session stop <session>" 2
          shift; parse_common_flags "$@"; cmd_session_stop "$st" ;;
        rm)
          local rmn="${1:-}"; [[ -n "$rmn" ]] || die "usage: session rm <session>" 2
          shift; parse_common_flags "$@"; cmd_session_rm "$rmn" ;;
        agent)
          local av="${1:-}"; shift 2>/dev/null || true
          case "$av" in
            start)  local as="${1:-}" ap="${2:-}"; shift 2 2>/dev/null || true
                    parse_common_flags "$@"; cmd_agent_start "$as" "$ap" ;;
            log)    local al="${1:-}"; shift; parse_common_flags "$@"; cmd_agent_log "$al" ;;
            attach) local aa="${1:-}"; shift; parse_common_flags "$@"; cmd_agent_attach "$aa" ;;
            *) die "usage: session agent start|log|attach <session>" 2 ;;
          esac ;;
        refresh-ip)
          # ⚠️ SKILL.md documents `session refresh-ip <session>`, but the session name was
          #    never consumed, so the documented form died with "unknown option". The
          #    firewall rule is global, so the name is accepted and ignored. See SIM-63.
          [[ $# -gt 0 && "$1" != --* ]] && shift
          parse_common_flags "$@"; cmd_session_refresh_ip ;;
        *) die "unknown session verb: ${sub:-<none>}" 2 ;;
      esac
      ;;
    *)                 printf 'error: unknown verb: %s\n' "$verb" >&2; usage >&2; exit 2 ;;
  esac
}

if [[ -z "${JUNGLE_UP_GCP_LIB:-}" ]]; then
  main "$@"
fi
