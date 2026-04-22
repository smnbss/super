#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=""
EXPLICIT_SOURCES=""
EXPLICIT_NAME=""
DESKTOP=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --desktop)
      DESKTOP=true
      shift
      ;;
    --source)
      EXPLICIT_SOURCES="${2:-}"
      shift 2
      ;;
    --name)
      EXPLICIT_NAME="${2:-}"
      shift 2
      ;;
    *)
      if [ -f "$1" ] && [[ "$1" == *.md ]]; then
        EXPLICIT_SOURCES="$1"
      elif [ -d "$1" ]; then
        PROJECT_DIR="$1"
      elif [ -f "$(pwd)/$1" ] && [[ "$1" == *.md ]]; then
        EXPLICIT_SOURCES="$(pwd)/$1"
      fi
      shift
      ;;
  esac
done

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
ENV_LOCAL="$PROJECT_DIR/.env.local"
SOURCES_MD="${EXPLICIT_SOURCES:-$PROJECT_DIR/sources.md}"
BASE="super"
BASE_MACHINE="${BASE}-base"

[ -f "$ENV_LOCAL" ] || { echo "Missing $ENV_LOCAL" >&2; exit 1; }
command -v orb &>/dev/null || { echo "Install OrbStack first" >&2; exit 1; }

# Read optional clone credentials from .env.local
BRAIN_CLONE_USERNAME=""
BRAIN_CLONE_PASSWORD=""
if [ -f "$ENV_LOCAL" ]; then
  BRAIN_CLONE_USERNAME="$(grep -E '^BRAIN_CLONE_USERNAME=' "$ENV_LOCAL" | tail -n 1 | cut -d= -f2- | tr -d '"' || true)"
  BRAIN_CLONE_PASSWORD="$(grep -E '^BRAIN_CLONE_PASSWORD=' "$ENV_LOCAL" | tail -n 1 | cut -d= -f2- | tr -d '"' || true)"
fi

orb_exists() { orb list 2>/dev/null | awk '{print $1}' | grep -qx "$1"; }
orb_running() { orb list 2>/dev/null | awk -v m="$1" '$1==m && $2=="running"{f=1} END{exit !f}'; }

# Ensure base machine exists with pre-installed dependencies.
#
# We only bake in the stuff that was proven stable in v5.9.3 — the heavy
# downloads (ollama, gcloud, node, three AI CLIs). Everything else (uv,
# markitdown, gws, gh) is installed per-clone by `super install`. That's
# ~5 min extra per clone but keeps the BASE_MACHINE bootstrap simple and
# reliable; a previous attempt to pre-bake those extras ran into
# unresolvable /usr/local ownership churn on Ubuntu 25.10 questing.
if ! orb_exists "$BASE_MACHINE"; then
  echo "Base machine '$BASE_MACHINE' not found. Creating..."
  orb create ubuntu "$BASE_MACHINE"
  orb -m "$BASE_MACHINE" bash -lc '
    set -euo pipefail
    sudo apt-get update && sudo apt-get install -y git curl zstd ca-certificates
    ARCH=$(uname -m)
    case "$ARCH" in
      x86_64) NODE_ARCH="linux-x64" ;;
      aarch64|arm64) NODE_ARCH="linux-arm64" ;;
      *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
    esac
    NODE_VERSION="20.19.0"
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${NODE_ARCH}.tar.gz" | \
      sudo tar -xz -C /usr/local --strip-components=1
    curl -fsSL https://ollama.com/install.sh | sh
    # Install Chromium via snap. On Ubuntu 25.10 questing the
    # `chromium-browser` apt package is a transitional stub that
    # Pre-Depends on snapd and just redirects to the chromium snap —
    # installing it without snapd produces a 50KB empty shell with no
    # browser binary. Bootstrap snapd first, wait for seed, then install
    # the real chromium snap. Covers both GUI (XRDP desktop entry) and
    # headless (--remote-debugging-port) use cases on ARM64 and x86_64.
    sudo apt-get install -y snapd
    sudo systemctl enable --now snapd.socket snapd.service
    sudo snap wait system seed.loaded
    sudo snap install chromium
    # Ubuntu 25.10 questing images do not ship /usr/bin/gpg, and sudo-rs
    # drops it into PATH in ways that are painful to work around. Use
    # [trusted=yes] on the apt source to skip signature verification
    # entirely — acceptable for a single-user dev VM sealing a local image.
    echo "deb [trusted=yes] https://packages.cloud.google.com/apt cloud-sdk main" | \
      sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
    sudo apt-get update && sudo apt-get install -y google-cloud-cli
    # Make /usr/local user-writable LAST. ollama runs `install -o0 -g0
    # -m755 -d /usr/local/bin` which re-chowns the directory to root.
    # We only need user ownership for the following npm -g step, so
    # doing the chown after ollama (and before npm) is both sufficient
    # and avoids any of the apt or curl installers re-flipping it back.
    sudo chown -R "$(id -u):$(id -g)" /usr/local/lib/node_modules /usr/local/bin /usr/local/include /usr/local/share
    npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli
  '
  orb stop "$BASE_MACHINE"
  echo "Base machine '$BASE_MACHINE' created."
fi

USER_NAME="$(whoami)"
USER_SLUG="$(printf '%s' "$USER_NAME" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"

# --name <instance-name>: if the machine exists, reuse it — start it if
# stopped, then re-run `super install --all` to pull the latest tooling.
# This gives you a fast "upgrade my existing clone" path without throwing
# away your work. If --name is given but no such machine exists, we fall
# through and create a new one with that name.
# Ensure Chromium is installed via snap on a machine. Idempotent: no-op if
# snap list already shows chromium. Installed here (not only on base image
# creation) so old super-base images that predate the snap fix self-heal
# on every clone/reuse instead of requiring a base rebuild.
ensure_chromium() {
  local machine="$1"
  orb -m "$machine" bash -lc '
    set -euo pipefail
    if snap list chromium &>/dev/null; then
      exit 0
    fi
    echo "Installing Chromium via snap..."
    sudo apt-get update
    sudo apt-get install -y snapd
    sudo systemctl enable --now snapd.socket snapd.service
    sudo snap wait system seed.loaded
    sudo snap install chromium
  '
}

if [ -n "$EXPLICIT_NAME" ] && orb_exists "$EXPLICIT_NAME"; then
  MACHINE="$EXPLICIT_NAME"
  if ! orb_running "$MACHINE"; then
    echo "Machine '$MACHINE' is stopped. Starting..."
    orb start "$MACHINE"
  fi
  echo "Machine '$MACHINE' already exists. Upgrading super + tools..."
  ensure_chromium "$MACHINE"
  orb -m "$MACHINE" bash -lc '
    set -euo pipefail
    export PATH="$HOME/.local/bin:$HOME/.super:$PATH"
    cd "$HOME/brain" 2>/dev/null || cd "$HOME"
    super install --all
  '
  echo "Done. Machine: $MACHINE (upgraded)"
  exit 0
fi

if [ -n "$EXPLICIT_NAME" ]; then
  MACHINE="$EXPLICIT_NAME"
else
  MACHINE="${BASE}-${USER_SLUG}-$(date +%m%d-%H%M%S)"
  if orb_exists "$MACHINE"; then
    i=2
    while orb_exists "$MACHINE-$i"; do ((i++)); done
    MACHINE="$MACHINE-$i"
  fi
fi

echo "Cloning '$BASE_MACHINE' to '$MACHINE'..."
orb clone "$BASE_MACHINE" "$MACHINE"
orb start "$MACHINE"

# Set up custom user credentials if provided
if [ -n "$BRAIN_CLONE_USERNAME" ] && [ -n "$BRAIN_CLONE_PASSWORD" ]; then
  echo "Configuring user '$BRAIN_CLONE_USERNAME'..."
  orb -m "$MACHINE" bash -lc "
    set -euo pipefail
    if ! id '$BRAIN_CLONE_USERNAME' &>/dev/null; then
      sudo useradd -m -s /bin/bash -G sudo '$BRAIN_CLONE_USERNAME'
    fi
    echo '$BRAIN_CLONE_USERNAME:$BRAIN_CLONE_PASSWORD' | sudo chpasswd
  "
fi

orb -m "$MACHINE" bash -c 'mkdir -p ~/brain'
orb push -m "$MACHINE" "$ENV_LOCAL" brain/.env.local
if [ -f "$SOURCES_MD" ]; then
  orb push -m "$MACHINE" "$SOURCES_MD" brain/sources.md
fi

# OrbStack symlinks /etc/resolv.conf -> /opt/orbstack-guest/etc/resolv.conf
# on a read-only overlay, with a reserved 0.x.x.x nameserver that
# OrbStack proxies at the VM networking layer. This breaks two things:
#   1. Snap confinement (chromium, etc.) cannot bind-mount resolv.conf
#      into its mount namespace, so confined apps see no DNS config.
#   2. Chromium's built-in async resolver rejects 0.x.x.x as
#      non-routable before sending a packet, producing
#      DNS_PROBE_FINISHED_BAD_CONFIG in the browser even though curl
#      from the same shell resolves fine via glibc+kernel routing.
# Replace the symlink with a real file using public resolvers. The
# trade-off is losing in-VM resolution of *.orb.local — acceptable
# since the user is already inside the VM.
orb -m "$MACHINE" bash -lc '
  if [ -L /etc/resolv.conf ]; then
    sudo rm -f /etc/resolv.conf
    printf "nameserver 1.1.1.1\nnameserver 8.8.8.8\noptions edns0\n" | \
      sudo tee /etc/resolv.conf >/dev/null
  fi
'

ensure_chromium "$MACHINE"

if [ "$DESKTOP" = true ]; then
  echo "Installing XFCE desktop and XRDP..."
  orb -m "$MACHINE" bash -lc '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    sudo apt-get update
    sudo apt-get install -y xfce4 xfce4-goodies xrdp
    # Configure XRDP to use XFCE
    echo "xfce4-session" | sudo tee /etc/skel/.xsession
    echo "xfce4-session" > ~/.xsession
    # Ensure xrdp uses the local session manager
    sudo sed -i "s/^test -x \/etc\/X11\/Xsession/# test -x \/etc\/X11\/Xsession/" /etc/xrdp/startwm.sh || true
    sudo sed -i "s/^exec \/bin\/sh \/etc\/X11\/Xsession/# exec \/bin\/sh \/etc\/X11\/Xsession/" /etc/xrdp/startwm.sh || true
    # XRDP does not export XAUTHORITY into the user session by default;
    # children of xfce4-session (notably terminals that then launch
    # confined snap apps like chromium) can see DISPLAY but fail with
    # "Authorization required, but no authorization protocol specified"
    # because they cannot find the X cookie. Export it before startxfce4
    # so every process in the desktop session inherits it.
    if ! grep -q "XAUTHORITY=" /etc/xrdp/startwm.sh; then
      echo "export XAUTHORITY=\"\$HOME/.Xauthority\"" | sudo tee -a /etc/xrdp/startwm.sh
    fi
    # Append XFCE start command if not present
    if ! grep -q "xfce4-session" /etc/xrdp/startwm.sh; then
      echo "startxfce4" | sudo tee -a /etc/xrdp/startwm.sh
    fi
    # Allow anyone to start X server (needed for XRDP)
    sudo sed -i "s/allowed_users=console/allowed_users=anybody/" /etc/X11/Xwrapper.config 2>/dev/null || true
    # Start and enable XRDP
    sudo systemctl enable xrdp
    sudo systemctl restart xrdp
  '
  RDP_IP="$(orbctl info "$MACHINE" | grep 'IPv4:' | awk '{print $2}')"
  echo "Desktop installed. Connect via RDP to $RDP_IP:3389"
  if [ -n "$BRAIN_CLONE_USERNAME" ]; then
    echo "  Username: $BRAIN_CLONE_USERNAME"
    echo "  Password: (from BRAIN_CLONE_PASSWORD in .env.local)"
    echo "  RDP URI: rdp://full%20address=s:$RDP_IP:3389\&username=s:$BRAIN_CLONE_USERNAME"
  else
    echo "  RDP URI: rdp://full%20address=s:$RDP_IP:3389"
  fi
fi

orb -m "$MACHINE" bash -lc '
  set -euo pipefail
  SUPER_HOME="$HOME/.super"
  rm -rf "$SUPER_HOME"
  git clone https://github.com/smnbss/super "$SUPER_HOME"
  # Interactive shells land here every time the user does `orb -m super`.
  # Default shell cwd is $HOME, but super refuses to install into $HOME
  # (and every brain skill expects to run from inside the brain dir).
  # Auto-cd to ~/brain and put super on PATH.
  if ! grep -q "$SUPER_HOME" "$HOME/.bashrc" 2>/dev/null; then
    {
      echo ""
      echo "# super"
      echo "export PATH=\"$SUPER_HOME:\$PATH\""
      echo "# Land interactive shells in the brain project, not \$HOME"
      echo "case \$- in *i*) [ -d \"\$HOME/brain\" ] && cd \"\$HOME/brain\" ;; esac"
    } >> "$HOME/.bashrc"
  fi
  export PATH="$HOME/.local/bin:$SUPER_HOME:$PATH"
  cd "$HOME/brain"
  super install --all
'

echo "Done. Machine: $MACHINE"
