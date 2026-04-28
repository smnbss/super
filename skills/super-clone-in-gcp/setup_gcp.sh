#!/usr/bin/env bash
set -euo pipefail

DEFAULT_MACHINE_TYPE="e2-standard-4"
DEFAULT_DISK_SIZE_GB="80"
DEFAULT_IMAGE_FAMILY="ubuntu-2604-lts-amd64"
DEFAULT_IMAGE_PROJECT="ubuntu-os-cloud"
DEFAULT_SSH_MODE="oslogin"
DEFAULT_ZONE="europe-west1-b"
NODE_VERSION="20.19.0"
STARTUP_MARKER="/var/lib/super-clone-in-gcp/startup.done"

usage() {
  cat <<'EOF'
Usage: setup_gcp.sh [project-dir] [sources.md] [options]

Options:
  --source <file>         Use <file> instead of sources.md
  --project <id>          Override the GCP project ID
  --zone <zone>           Override the Compute Engine zone
  --machine-type <type>   Machine type (default: e2-standard-4)
  --disk-size-gb <size>   Boot disk size in GB (default: 80)
  --ssh-mode <mode>       SSH mode: oslogin or metadata (default: oslogin)
  --network <network>       VPC network name (default: default)
  --subnet <subnet>         Subnet name
  --source-ip <cidr>      Restrict SSH/XRDP to this IP or CIDR (default: auto-detect
                          your public IPv4 and lock down to /32). Accepts a comma-
                          separated list of IPs/CIDRs.
  --desktop               Install GNOME desktop and XRDP
  --name <instance-name>  Explicit VM name
  --dry-run               Print the resolved configuration and commands only
  --help                  Show this help
EOF
}

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

gcloud_config_value() {
  local key="$1"
  local value
  value="$(gcloud config get-value "$key" 2>/dev/null || true)"
  if [[ -n "$value" && "$value" != "(unset)" ]]; then
    printf '%s' "$value"
  fi
}

dotenv_value() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "$ENV_LOCAL" | tail -n 1 || true)"
  if [[ -n "$line" ]]; then
    printf '%s' "${line#*=}"
  fi
}

detect_public_ip() {
  local ip svc
  for svc in https://api.ipify.org https://ifconfig.me https://icanhazip.com; do
    ip="$(curl -4 -fsSL --max-time 5 "$svc" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      printf '%s' "$ip"
      return 0
    fi
  done
  return 1
}

find_public_key() {
  local candidate
  for candidate in \
    "$HOME/.ssh/google_compute_engine.pub" \
    "$HOME/.ssh/id_ed25519.pub" \
    "$HOME/.ssh/id_rsa.pub"
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

slugify() {
  local raw="$1"
  local slug
  slug="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
  slug="${slug#-}"
  slug="${slug%-}"
  printf '%s' "${slug:-brain}"
}

gcloud_ssh() {
  gcloud --project="$PROJECT_ID" compute ssh "$INSTANCE_NAME" --zone="$ZONE" "$@"
}

gcloud_scp() {
  gcloud --project="$PROJECT_ID" compute scp --zone="$ZONE" "$@"
}

PROJECT_DIR=""
EXPLICIT_SOURCES=""
PROJECT_ID=""
ZONE=""
MACHINE_TYPE="$DEFAULT_MACHINE_TYPE"
DISK_SIZE_GB="$DEFAULT_DISK_SIZE_GB"
SSH_MODE="$DEFAULT_SSH_MODE"
NETWORK=""
SUBNET=""
INSTANCE_NAME=""
DESKTOP=false
DRY_RUN=0
SOURCE_IP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      EXPLICIT_SOURCES="${2:-}"
      shift 2
      ;;
    --project)
      PROJECT_ID="${2:-}"
      shift 2
      ;;
    --zone)
      ZONE="${2:-}"
      shift 2
      ;;
    --machine-type)
      MACHINE_TYPE="${2:-}"
      shift 2
      ;;
    --disk-size-gb)
      DISK_SIZE_GB="${2:-}"
      shift 2
      ;;
    --ssh-mode)
      SSH_MODE="${2:-}"
      shift 2
      ;;
    --network)
      NETWORK="${2:-}"
      shift 2
      ;;
    --subnet)
      SUBNET="${2:-}"
      shift 2
      ;;
    --source-ip)
      SOURCE_IP="${2:-}"
      shift 2
      ;;
    --desktop)
      DESKTOP=true
      shift
      ;;
    --name)
      INSTANCE_NAME="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      if [[ -f "$1" && "$1" == *.md ]]; then
        EXPLICIT_SOURCES="$1"
      elif [[ -d "$1" ]]; then
        PROJECT_DIR="$1"
      elif [[ -f "$(pwd)/$1" && "$1" == *.md ]]; then
        EXPLICIT_SOURCES="$(pwd)/$1"
      else
        die "Unknown argument: $1"
      fi
      shift
      ;;
  esac
done

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
[[ -d "$PROJECT_DIR" ]] || die "Project directory not found: $PROJECT_DIR"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
ENV_LOCAL="$PROJECT_DIR/.env.local"
SOURCES_MD="${EXPLICIT_SOURCES:-$PROJECT_DIR/sources.md}"

[[ -f "$ENV_LOCAL" ]] || die "Missing $ENV_LOCAL"
require_cmd gcloud
require_cmd git
require_cmd mktemp

CURRENT_GCLOUD_PROJECT="$(gcloud_config_value project || true)"
CURRENT_GCLOUD_ZONE="$(gcloud_config_value compute/zone || true)"
BRAIN_CLONE_GCP_VALUE="$(dotenv_value BRAIN_CLONE_GCP)"
GCP_PROJECT_ID_VALUE="$(dotenv_value GCP_PROJECT_ID)"
BRAIN_CLONE_USERNAME="$(dotenv_value BRAIN_CLONE_USERNAME)"
BRAIN_CLONE_PASSWORD="$(dotenv_value BRAIN_CLONE_PASSWORD)"

PROJECT_ID="${PROJECT_ID:-${BRAIN_CLONE_GCP:-${BRAIN_CLONE_GCP_VALUE:-${CURRENT_GCLOUD_PROJECT:-${GCP_PROJECT_ID:-${GCP_PROJECT_ID_VALUE:-}}}}}}"
ZONE="${ZONE:-${CURRENT_GCLOUD_ZONE:-$DEFAULT_ZONE}}"

[[ -n "$PROJECT_ID" ]] || die "Set BRAIN_CLONE_GCP, GCP_PROJECT_ID, or pass --project"
[[ "$SSH_MODE" == "oslogin" || "$SSH_MODE" == "metadata" ]] || die "--ssh-mode must be oslogin or metadata"
[[ "$DISK_SIZE_GB" =~ ^[0-9]+$ ]] || die "--disk-size-gb must be numeric"

if [[ -z "$SOURCE_IP" ]]; then
  DETECTED_IP="$(detect_public_ip || true)"
  [[ -n "$DETECTED_IP" ]] || die "Could not auto-detect public IP. Pass --source-ip <ip-or-cidr> explicitly."
  SOURCE_IP="${DETECTED_IP}/32"
  log "Locking down SSH/XRDP to detected public IP: $SOURCE_IP"
elif [[ "$SOURCE_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SOURCE_IP="${SOURCE_IP}/32"
fi

ensure_firewall_rule() {
  local name="$1"
  local port="$2"
  local desc="$3"
  if gcloud --project="$PROJECT_ID" compute firewall-rules describe "$name" --format="value(name)" >/dev/null 2>&1; then
    log "Updating firewall rule '$name' → source-ranges=$SOURCE_IP"
    gcloud --project="$PROJECT_ID" compute firewall-rules update "$name" \
      --source-ranges="$SOURCE_IP" >/dev/null || log "Firewall rule update failed for '$name'."
  else
    log "Creating firewall rule '$name' (tcp:$port, source=$SOURCE_IP)..."
    gcloud --project="$PROJECT_ID" compute firewall-rules create "$name" \
      --allow="tcp:$port" \
      --source-ranges="$SOURCE_IP" \
      --target-tags="xrdp" \
      --description="$desc" || log "Firewall rule creation failed for '$name'."
  fi
}

apply_clone_password() {
  if [[ -z "$BRAIN_CLONE_USERNAME" || -z "$BRAIN_CLONE_PASSWORD" ]]; then
    return 0
  fi
  log "Setting password for '$BRAIN_CLONE_USERNAME' via SSH..."
  printf '%s:%s\n' "$BRAIN_CLONE_USERNAME" "$BRAIN_CLONE_PASSWORD" | \
    gcloud_ssh --command "sudo chpasswd" >/dev/null || log "chpasswd failed for '$BRAIN_CLONE_USERNAME'."
}

repair_xrdp_ssl_cert() {
  # On existing VMs (or VMs provisioned before this fix shipped) the xrdp
  # user may not be in ssl-cert, which breaks TLS handshake. Idempotent;
  # no-op if xrdp isn't installed.
  gcloud_ssh --command 'if id xrdp >/dev/null 2>&1; then sudo usermod -aG ssl-cert xrdp && sudo systemctl restart xrdp; fi' >/dev/null 2>&1 \
    || log "xrdp ssl-cert repair skipped or failed."
}

repair_xrdp_session() {
  # On existing VMs provisioned before the dbus-run-session fix shipped the
  # desktop session exits ~1s after login (xrdp logs "Window manager exited
  # quickly") because gnome-session/xfce4-session has no per-session bus.
  # Symptom client-side: connect succeeds, password accepted, then immediate
  # disconnect that looks like a TLS abort. Fix: install dbus-x11 and
  # rewrite the exec line in /etc/xrdp/startwm.sh to wrap the WM in
  # dbus-run-session. Idempotent; no-op if xrdp isn't installed.
  gcloud_ssh --command '
if id xrdp >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y dbus-x11 >/dev/null 2>&1 || true
  if [ -f /etc/xrdp/startwm.sh ] && ! grep -q "dbus-run-session" /etc/xrdp/startwm.sh; then
    sudo sed -i "s|^exec gnome-session\$|exec dbus-run-session -- gnome-session|" /etc/xrdp/startwm.sh
    sudo sed -i "s|^exec startxfce4\$|exec dbus-run-session -- xfce4-session|" /etc/xrdp/startwm.sh
  fi
fi' >/dev/null 2>&1 \
    || log "xrdp session repair skipped or failed."
}

USER_NAME="$(whoami)"
USER_SLUG="$(slugify "$USER_NAME")"
if [[ -z "$INSTANCE_NAME" ]]; then
  INSTANCE_NAME="super-${USER_SLUG}-$(date +%m%d-%H%M%S)"
fi
INSTANCE_NAME="$(slugify "$INSTANCE_NAME")"
INSTANCE_NAME="${INSTANCE_NAME:0:63}"
[[ "$INSTANCE_NAME" =~ ^[a-z] ]] || INSTANCE_NAME="s${INSTANCE_NAME}"

TMP_DIR="$(mktemp -d)"
STARTUP_SCRIPT="$TMP_DIR/startup.sh"
REMOTE_BOOTSTRAP="$TMP_DIR/bootstrap.sh"
SSH_KEYS_FILE=""
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# Header: injects values that must be resolved locally (paths, versions).
# Everything after runs on the VM, so use a quoted heredoc below to avoid
# local expansion of remote-side variables.
cat >"$STARTUP_SCRIPT" <<HEAD
#!/usr/bin/env bash
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
exec > >(tee -a /var/log/super-clone-in-gcp.log) 2>&1
STARTUP_MARKER="$STARTUP_MARKER"
NODE_VERSION="$NODE_VERSION"
HEAD
cat >>"$STARTUP_SCRIPT" <<'EOF'
mkdir -p "$(dirname "$STARTUP_MARKER")"

# Ubuntu cloud images run unattended-upgrades on first boot and hold the dpkg
# lock for several minutes. Stop the daily timers and wait for any in-flight
# upgrade to release the lock before we start installing.
systemctl stop apt-daily.timer apt-daily-upgrade.timer unattended-upgrades 2>/dev/null || true
for _ in $(seq 1 120); do
  fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock >/dev/null 2>&1 || break
  sleep 5
done

# Belt-and-suspenders: every apt-get also waits up to 10 min for the lock.
APT="apt-get -o DPkg::Lock::Timeout=600"
$APT update
$APT install -y git curl zstd ca-certificates
curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.gz" | \
  tar -xz -C /usr/local --strip-components=1
curl -fsSL https://ollama.com/install.sh | sh
# On Ubuntu 24.04 LTS `chromium-browser` is a transitional package
# that Pre-Depends on snapd and redirects to the chromium snap —
# installing it without snapd produces a 50KB empty stub with no
# browser binary. Bootstrap snapd, wait for the seed, install the
# real chromium snap. Covers both GUI (XRDP desktop entry) and
# headless (--remote-debugging-port) use cases.
$APT install -y snapd
systemctl enable --now snapd.socket snapd.service
snap wait system seed.loaded
snap install chromium
# Set chromium as the default browser system-wide. The snap postinst does
# not register update-alternatives, so anything calling xdg-open, BROWSER,
# or x-www-browser falls back to whatever is first in PATH. Register it
# and seed the XDG mimeapps defaults so GNOME and headless tooling both
# route to chromium_chromium.desktop.
update-alternatives --install /usr/bin/x-www-browser x-www-browser /snap/bin/chromium 200
update-alternatives --set x-www-browser /snap/bin/chromium
update-alternatives --install /usr/bin/gnome-www-browser gnome-www-browser /snap/bin/chromium 200
update-alternatives --set gnome-www-browser /snap/bin/chromium
mkdir -p /etc/xdg
cat >/etc/xdg/mimeapps.list <<'MIME'
[Default Applications]
text/html=chromium_chromium.desktop
x-scheme-handler/http=chromium_chromium.desktop
x-scheme-handler/https=chromium_chromium.desktop
x-scheme-handler/about=chromium_chromium.desktop
x-scheme-handler/unknown=chromium_chromium.desktop
MIME
echo 'export BROWSER=/snap/bin/chromium' >/etc/profile.d/chromium-default.sh
chmod +x /etc/profile.d/chromium-default.sh
echo "deb [trusted=yes] https://packages.cloud.google.com/apt cloud-sdk main" \
  >/etc/apt/sources.list.d/google-cloud-sdk.list
$APT update
$APT install -y google-cloud-cli
npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli

DESKTOP_ENABLED="$(curl -fsSL "http://metadata.google.internal/computeMetadata/v1/instance/attributes/enable-desktop" -H "Metadata-Flavor: Google" 2>/dev/null || true)"
if [[ "$DESKTOP_ENABLED" == "true" ]]; then
  # dbus-x11 provides dbus-launch / dbus-run-session — without it the
  # desktop session exits immediately with "dbus-launch not found, the
  # desktop will not work properly!" and xrdp tears the connection down
  # one second after login. ubuntu-desktop-minimal does not always pull
  # it in, so install explicitly.
  $APT install -y ubuntu-desktop-minimal xrdp dbus-x11
  # Ubuntu's xrdp ships /etc/xrdp/{cert,key}.pem as symlinks to
  # /etc/ssl/private/ssl-cert-snakeoil.key (root:ssl-cert, mode 0640), but
  # the package postinst does not add the xrdp service user to ssl-cert.
  # Without this, TLS handshake fails with "Cannot read private key file:
  # Permission denied" and the client never sees a login prompt.
  usermod -aG ssl-cert xrdp
  systemctl enable xrdp
  # Use restart (not start) so the running daemon picks up the new group.
  systemctl restart xrdp

  sed -i 's/^test -x \/etc\/X11\/Xsession/#&/' /etc/xrdp/startwm.sh
  sed -i 's/^exec \/bin\/sh \/etc\/X11\/Xsession/#&/' /etc/xrdp/startwm.sh
  # XRDP does not export XAUTHORITY into the user session by default;
  # children of gnome-session (notably terminals that then launch
  # confined snap apps like chromium) can see DISPLAY but fail with
  # "Authorization required, but no authorization protocol specified"
  # because they can't find the X cookie. Export it before gnome-session
  # so every process in the desktop session inherits it.
  if ! grep -q 'XAUTHORITY=' /etc/xrdp/startwm.sh; then
    echo 'export XAUTHORITY="$HOME/.Xauthority"' >> /etc/xrdp/startwm.sh
  fi
  # GNOME 4x defaults to Wayland, but xrdp speaks X11. Drop a system-wide
  # .xsessionrc so every xrdp login inherits the Ubuntu GNOME-on-Xorg env
  # (XDG_CURRENT_DESKTOP, session mode, data/config dirs).
  cat >/etc/skel/.xsessionrc <<'XSR'
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_DATA_DIRS=/usr/share/ubuntu:/usr/local/share:/usr/share:/var/lib/snapd/desktop
export XDG_CONFIG_DIRS=/etc/xdg/xdg-ubuntu:/etc/xdg
XSR
  # Wrap gnome-session in dbus-run-session so the WM always gets a fresh
  # per-session message bus — without it, gnome-session exits ~1s after
  # login with "Cannot open display" / "dbus-launch not found", and the
  # RDP client sees the same symptom as a TLS-handshake abort (xrdp logs
  # "Window manager exited quickly").
  echo '. /etc/skel/.xsessionrc' >> /etc/xrdp/startwm.sh
  echo 'exec dbus-run-session -- gnome-session' >> /etc/xrdp/startwm.sh

  sed -i 's/TerminalServerUsers=tsusers/TerminalServerUsers=sudo/' /etc/xrdp/sesman.ini || true
  sed -i 's/TerminalServerAdmins=tsadmins/TerminalServerAdmins=sudo/' /etc/xrdp/sesman.ini || true

  echo 'gnome-session' > /etc/skel/.xsession

  # gdm3 is unused — xrdp launches its own X server on :10+. Drop to
  # multi-user.target so we don't waste RAM on a console login screen
  # nobody will see.
  systemctl set-default multi-user.target
  systemctl disable gdm3 2>/dev/null || true
fi

CLONE_USER="$(curl -fsSL "http://metadata.google.internal/computeMetadata/v1/instance/attributes/brain-clone-username" -H "Metadata-Flavor: Google" 2>/dev/null || true)"
if [[ -n "$CLONE_USER" ]]; then
  if ! id "$CLONE_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$CLONE_USER"
  fi
  usermod -aG sudo "$CLONE_USER"
  mkdir -p "/home/$CLONE_USER/brain"
  if [[ "$DESKTOP_ENABLED" == "true" ]]; then
    echo "gnome-session" > "/home/$CLONE_USER/.xsession"
    cp /etc/skel/.xsessionrc "/home/$CLONE_USER/.xsessionrc" 2>/dev/null || true
    chown "$CLONE_USER:$CLONE_USER" "/home/$CLONE_USER/.xsession" "/home/$CLONE_USER/.xsessionrc" 2>/dev/null || true
  fi
fi

touch "$STARTUP_MARKER"
EOF
chmod +x "$STARTUP_SCRIPT"

cat >"$REMOTE_BOOTSTRAP" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HOME/brain"
SUPER_HOME="$HOME/.super"
rm -rf "$SUPER_HOME"
git clone https://github.com/smnbss/super "$SUPER_HOME"
if ! grep -qF "$SUPER_HOME:" "$HOME/.bashrc" 2>/dev/null; then
  {
    echo ""
    echo "# super"
    echo "export PATH=\"$SUPER_HOME:\$PATH\""
    echo "# Land interactive shells in the brain project, not \$HOME"
    echo "case \$- in *i*) [ -d \"\$HOME/brain\" ] && cd \"\$HOME/brain\" ;; esac"
  } >>"$HOME/.bashrc"
fi
export PATH="$HOME/.local/bin:$SUPER_HOME:$PATH"
cd "$HOME/brain"
super install --all

# Configure XRDP session for this user
if [ -f /etc/xrdp/startwm.sh ]; then
  echo "gnome-session" > "$HOME/.xsession"
  cp /etc/skel/.xsessionrc "$HOME/.xsessionrc" 2>/dev/null || true
fi

# Also bootstrap super + XRDP session for the local clone user (XRDP login target)
CLONE_USER="$(curl -fsSL "http://metadata.google.internal/computeMetadata/v1/instance/attributes/brain-clone-username" -H "Metadata-Flavor: Google" 2>/dev/null || true)"
if [[ -n "$CLONE_USER" && -d "/home/$CLONE_USER" ]]; then
  # Seed the clone user's ~/brain with the same .env.local and sources.md
  sudo mkdir -p "/home/$CLONE_USER/brain"
  for f in .env.local sources.md; do
    if [[ -f "$HOME/brain/$f" ]]; then
      sudo cp "$HOME/brain/$f" "/home/$CLONE_USER/brain/$f"
    fi
  done
  sudo chown -R "$CLONE_USER:$CLONE_USER" "/home/$CLONE_USER/brain"

  # Run the super bootstrap as the clone user so `super` is on their PATH in RDP terminals
  sudo -u "$CLONE_USER" -H bash -s <<'CLONE_EOF'
set -euo pipefail
SUPER_HOME="$HOME/.super"
rm -rf "$SUPER_HOME"
git clone https://github.com/smnbss/super "$SUPER_HOME"
if ! grep -qF "$SUPER_HOME:" "$HOME/.bashrc" 2>/dev/null; then
  {
    echo ""
    echo "# super"
    echo "export PATH=\"\$HOME/.local/bin:$SUPER_HOME:\$PATH\""
    echo "case \$- in *i*) [ -d \"\$HOME/brain\" ] && cd \"\$HOME/brain\" ;; esac"
  } >>"$HOME/.bashrc"
fi
export PATH="$HOME/.local/bin:$SUPER_HOME:$PATH"
mkdir -p "$HOME/brain"
cd "$HOME/brain"
super install --all
echo "gnome-session" > "$HOME/.xsession"
cp /etc/skel/.xsessionrc "$HOME/.xsessionrc" 2>/dev/null || true
CLONE_EOF
fi

rm -f "$HOME/.super-bootstrap.sh"
EOF
chmod +x "$REMOTE_BOOTSTRAP"

METADATA_ITEMS=()

if [[ -n "$BRAIN_CLONE_USERNAME" ]]; then
  METADATA_ITEMS+=("brain-clone-username=$BRAIN_CLONE_USERNAME")
fi

if [[ "$DESKTOP" == true ]]; then
  METADATA_ITEMS+=("enable-desktop=true")
fi

if [[ "$SSH_MODE" == "oslogin" ]]; then
  METADATA_ITEMS+=("enable-oslogin=TRUE")
else
  METADATA_ITEMS+=("enable-oslogin=FALSE")
fi

CREATE_ARGS=(
  gcloud --project="$PROJECT_ID" compute instances create "$INSTANCE_NAME"
  --zone="$ZONE"
  --machine-type="$MACHINE_TYPE"
  --boot-disk-size="${DISK_SIZE_GB}GB"
  --image-family="$DEFAULT_IMAGE_FAMILY"
  --image-project="$DEFAULT_IMAGE_PROJECT"
  --metadata-from-file="startup-script=$STARTUP_SCRIPT"
  --tags="xrdp"
)

if [[ ${#METADATA_ITEMS[@]} -gt 0 ]]; then
  METADATA_STRING=$(IFS=,; echo "${METADATA_ITEMS[*]}")
  CREATE_ARGS+=(--metadata="$METADATA_STRING")
fi

# BRAIN_CLONE_PASSWORD is deliberately NOT stored as instance metadata — it
# would be readable by anyone with compute.instances.get on the project.
# It's applied post-boot via SSH + chpasswd below.

if [[ -n "$NETWORK" ]]; then
  CREATE_ARGS+=(--network="$NETWORK")
fi

if [[ -n "$SUBNET" ]]; then
  CREATE_ARGS+=(--subnet="$SUBNET")
fi

if [[ "$SSH_MODE" == "metadata" ]]; then
  PUBKEY_PATH="$(find_public_key || true)"
  [[ -n "$PUBKEY_PATH" ]] || die "No SSH public key found for metadata mode"
  SSH_KEYS_FILE="$TMP_DIR/ssh-keys"
  printf '%s:%s\n' "${USER:-$(id -un)}" "$(cat "$PUBKEY_PATH")" >"$SSH_KEYS_FILE"
  CREATE_ARGS+=(--metadata-from-file="ssh-keys=$SSH_KEYS_FILE")
fi

SSH_COMMAND="gcloud --project=$PROJECT_ID compute ssh $INSTANCE_NAME --zone=$ZONE"
STOP_COMMAND="gcloud --project=$PROJECT_ID compute instances stop $INSTANCE_NAME --zone=$ZONE"
START_COMMAND="gcloud --project=$PROJECT_ID compute instances start $INSTANCE_NAME --zone=$ZONE"
DELETE_COMMAND="gcloud --project=$PROJECT_ID compute instances delete $INSTANCE_NAME --zone=$ZONE"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "Dry run"
  log "  Project:      $PROJECT_ID"
  log "  Zone:         $ZONE"
  log "  Machine type: $MACHINE_TYPE"
  log "  Disk size:    ${DISK_SIZE_GB}GB"
  log "  SSH mode:     $SSH_MODE"
  log "  Instance:     $INSTANCE_NAME"
  log "  Project dir:  $PROJECT_DIR"
  log "  Source IP:    $SOURCE_IP"
  log ""
  log "Create command:"
  printf '  '
  for arg in "${CREATE_ARGS[@]}"; do
    printf '%q ' "$arg"
  done
  printf '\n'
  log "SSH command:"
  log "  $SSH_COMMAND"
  log "Stop command:"
  log "  $STOP_COMMAND"
  log "Start command:"
  log "  $START_COMMAND"
  log "Delete command:"
  log "  $DELETE_COMMAND"
  exit 0
fi

# --name <instance-name>: if the instance already exists, reuse it —
# start it if TERMINATED, then re-run `super install --all` to pull the
# latest tooling. Fast "upgrade my existing clone" path without throwing
# away disk state. If the name doesn't exist, fall through and create.
EXISTING_STATUS="$(gcloud --project="$PROJECT_ID" compute instances describe "$INSTANCE_NAME" --zone="$ZONE" --format="value(status)" 2>/dev/null || true)"
if [[ -n "$EXISTING_STATUS" ]]; then
  log "Instance '$INSTANCE_NAME' already exists (status: $EXISTING_STATUS). Upgrading super + tools..."
  if [[ "$EXISTING_STATUS" != "RUNNING" ]]; then
    log "Starting instance..."
    gcloud --project="$PROJECT_ID" compute instances start "$INSTANCE_NAME" --zone="$ZONE"
    # Wait for SSH to come up after start.
    for _ in $(seq 1 30); do
      if gcloud_ssh --command "true" >/dev/null 2>&1; then
        break
      fi
      sleep 5
    done
  fi
  gcloud_ssh --command 'set -euo pipefail; export PATH="$HOME/.local/bin:$HOME/.super:$PATH"; cd "$HOME/brain" 2>/dev/null || cd "$HOME"; super install --all'
  # Refresh firewall rules so the IP lockdown tracks the caller's current IP.
  ensure_firewall_rule "allow-ssh" "22" "Allow SSH connections"
  if gcloud --project="$PROJECT_ID" compute firewall-rules describe "allow-xrdp" --format="value(name)" >/dev/null 2>&1; then
    ensure_firewall_rule "allow-xrdp" "3389" "Allow XRDP connections"
  fi
  # Repair ssl-cert group on VMs provisioned before that fix shipped, and
  # (re)apply the clone user's password. Both are idempotent — running
  # --name <existing> effectively doubles as a repair tool.
  repair_xrdp_ssl_cert
  repair_xrdp_session
  apply_clone_password
  EXTERNAL_IP="$(gcloud --project="$PROJECT_ID" compute instances list --filter="name=$INSTANCE_NAME" --format="value(EXTERNAL_IP)" --zone="$ZONE" 2>/dev/null || true)"
  log ""
  log "Done. Machine: $INSTANCE_NAME (upgraded)"
  log "SSH:"
  log "  $SSH_COMMAND"
  if [[ -n "$EXTERNAL_IP" ]]; then
    log "External IP: $EXTERNAL_IP"
  fi
  log "Stop:"
  log "  $STOP_COMMAND"
  log "Delete:"
  log "  $DELETE_COMMAND"
  exit 0
fi

log "Creating '$INSTANCE_NAME' in project '$PROJECT_ID' ($ZONE)..."
"${CREATE_ARGS[@]}"

# Ensure firewall rules exist and are scoped to $SOURCE_IP.
ensure_firewall_rule "allow-ssh" "22" "Allow SSH connections"
if [[ "$DESKTOP" == true ]]; then
  ensure_firewall_rule "allow-xrdp" "3389" "Allow XRDP connections"
fi

log "Waiting for startup to finish..."
READY=0
for _ in $(seq 1 60); do
  if gcloud_ssh --command "test -f $STARTUP_MARKER" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 10
done
[[ "$READY" -eq 1 ]] || die "VM did not become ready in time. Check serial console or /var/log/super-clone-in-gcp.log."

log "Copying project files..."
gcloud_ssh --command "mkdir -p ~/brain"
gcloud_scp "$ENV_LOCAL" "$INSTANCE_NAME:~/brain/.env.local"
if [[ -f "$SOURCES_MD" ]]; then
  gcloud_scp "$SOURCES_MD" "$INSTANCE_NAME:~/brain/sources.md"
fi
gcloud_scp "$REMOTE_BOOTSTRAP" "$INSTANCE_NAME:~/.super-bootstrap.sh"

log "Bootstrapping super on the VM..."
gcloud_ssh --command "chmod +x ~/.super-bootstrap.sh && ~/.super-bootstrap.sh"

apply_clone_password

RDP_COMMAND="gcloud --project=$PROJECT_ID compute instances list --filter=name=$INSTANCE_NAME --format='value(EXTERNAL_IP)'"
EXTERNAL_IP="$(gcloud --project="$PROJECT_ID" compute instances list --filter="name=$INSTANCE_NAME" --format="value(EXTERNAL_IP)" --zone="$ZONE" 2>/dev/null || true)"

log ""
log "Done. Machine: $INSTANCE_NAME"
log "SSH:"
log "  $SSH_COMMAND"
if [[ "$DESKTOP" == true && -n "$EXTERNAL_IP" ]]; then
  log "RDP:"
  if [[ -n "$BRAIN_CLONE_USERNAME" && -n "$BRAIN_CLONE_PASSWORD" ]]; then
    log "  $EXTERNAL_IP:3389 (user: $BRAIN_CLONE_USERNAME / password: $BRAIN_CLONE_PASSWORD)"
  else
    log "  $EXTERNAL_IP:3389 (user: $(whoami) — set a password with: sudo passwd \$(whoami))"
  fi
fi
log "Stop:"
log "  $STOP_COMMAND"
log "Start:"
log "  $START_COMMAND"
log "Delete:"
log "  $DELETE_COMMAND"
