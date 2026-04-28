---
name: super-clone-in-gcp
description: >-
  Create a persistent GCP Ubuntu machine pre-configured for the current project,
  copying `.env.local` and `sources.md`. Optional GNOME desktop via XRDP.
---

# /super-clone-in-gcp

Create a persistent Google Compute Engine Ubuntu machine for the current project.

## When to use
- When the user says "super clone in gcp", "remote clone", "setup gcp workstation", or asks to provision a remote Ubuntu environment
- When setting up a long-lived Ubuntu machine with project files copied over
- When a GUI desktop (GNOME) with RDP access is desired on the remote machine

## Steps

1. Locate the `setup_gcp.sh` script in the skill directory:
   - `.agents/skills/super-clone-in-gcp/setup_gcp.sh` (Codex and Gemini)
   - `.claude/skills/super-clone-in-gcp/setup_gcp.sh` (Claude)
2. Run it with the current working directory as the project path:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)"
   ```
   For a machine with GNOME desktop and XRDP:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)" --desktop
   ```
   If your project does not have a `default` VPC network, specify `--network` and `--subnet`:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)" --network weroad-vpc-1-development --subnet weroad-eu-subnet-1-development
   ```
   To copy a specific sources file (e.g. `sources.dev.super.md`) instead of the default `sources.md`, pass it positionally or via `--source`:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh sources.dev.super.md
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)" --source sources.dev.super.md
   ```
   Combine both:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)" sources.dev.super.md --desktop
   ```
   To reuse (and upgrade) an existing instance instead of creating a new timestamped one, pass `--name`:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh --name super-dev
   ```
   If the instance exists, it will be started (if TERMINATED) and `super install --all` will run over SSH to refresh tooling. If it doesn't exist, a new instance is created with that name.
   To restrict SSH/XRDP to a specific IP or CIDR (instead of the auto-detected public IP), pass `--source-ip`:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh --name super-dev --source-ip 203.0.113.4/32
   ```
   Multiple IPs/CIDRs can be passed comma-separated (e.g. `--source-ip 1.2.3.4/32,5.6.7.0/24`).
   For the full flag list (`--project`, `--zone`, `--machine-type`, `--disk-size-gb`, `--ssh-mode`, `--network`, `--subnet`, `--source-ip`, `--name`, `--dry-run`), run:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh --help
   ```
3. Report the machine name created or any errors.

The script will:
- Resolve the target project from `BRAIN_CLONE_GCP`, then `gcloud config get-value project`, then `GCP_PROJECT_ID`
- Create a stock Ubuntu 24.04 LTS Compute Engine VM named `super-<username>-<MMDD-HHMMSS>` (default `e2-standard-4`, 80 GB disk, `europe-west1-b`)
- Run a startup script that installs: `git`, `curl`, `zstd`, Node.js 20.19.0, Ollama, Chromium, the Google Cloud CLI, and the `@anthropic-ai/claude-code`, `@openai/codex`, `@google/gemini-cli` npm globals
- With `--desktop`: additionally install GNOME (`ubuntu-desktop-minimal`) and XRDP, force the GNOME-on-Xorg session for xrdp, create the `allow-xrdp` firewall rule, and print the RDP connection address
- Create/update the `allow-ssh` (and, with `--desktop`, `allow-xrdp`) firewall rules so they only permit traffic from the caller's current public IPv4 (auto-detected via `curl -4 https://api.ipify.org` with fallbacks). Override with `--source-ip`. The IP is refreshed on every run — including `--name` reuse — so the lockdown tracks your current IP if it changes. If detection fails and no `--source-ip` is given, the script aborts rather than falling back to `0.0.0.0/0`.
- Wait for SSH readiness, copy `.env.local` and optional `sources.md`, then bootstrap `super` (git clone into `~/.super` + `super install --all`)
- Print the SSH command plus manual start/stop/delete commands for the workstation

## Environment Variables

Set these in your project's `.env.local`:

- `BRAIN_CLONE_GCP` — GCP project ID for the VM
- `BRAIN_CLONE_USERNAME` — Local username for XRDP login (optional)
- `BRAIN_CLONE_PASSWORD` — Password for the local XRDP user (optional)

If `BRAIN_CLONE_USERNAME` is provided, the VM's startup script creates the user with sudo access and configures XRDP automatically. If `BRAIN_CLONE_PASSWORD` is also provided, it is applied over SSH via `chpasswd` after boot — the password is **never** stored as instance metadata, so it isn't readable by anyone with `compute.instances.get`.

## RDP Access

After the VM is ready (only when `--desktop` is used):
1. The `allow-xrdp` firewall rule is created automatically in your GCP project (port 3389), scoped to your detected public IP (or the `--source-ip` override). The VM is tagged with `xrdp` for this purpose.
2. If you did not set `BRAIN_CLONE_USERNAME`/`BRAIN_CLONE_PASSWORD`, create a local user manually:
   ```bash
   sudo adduser <username>
   ```
3. Connect via RDP to the VM's external IP on port 3389. The XRDP session will launch GNOME (Ubuntu, on Xorg) automatically.
