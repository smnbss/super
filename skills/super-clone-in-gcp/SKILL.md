---
name: super-clone-in-gcp
description: >-
  Create a persistent GCP Ubuntu machine pre-configured for the current project,
  copying `.env.local` and `sources.md`. Optional XFCE desktop via XRDP.
---

# /super-clone-in-gcp

Create a persistent Google Compute Engine Ubuntu machine for the current project.

## When to use
- When the user says "super clone in gcp", "remote clone", "setup gcp workstation", or asks to provision a remote Ubuntu environment
- When setting up a long-lived Ubuntu machine with project files copied over
- When a GUI desktop (XFCE) with RDP access is desired on the remote machine

## Steps

1. Locate the `setup_gcp.sh` script in the skill directory:
   - `.agents/skills/super-clone-in-gcp/setup_gcp.sh` (Codex and Gemini)
   - `.claude/skills/super-clone-in-gcp/setup_gcp.sh` (Claude)
2. Run it with the current working directory as the project path:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)"
   ```
   For a machine with XFCE desktop and XRDP:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)" --desktop
   ```
   If your project does not have a `default` VPC network, specify `--network` and `--subnet`:
   ```bash
   <skill-dir>/super-clone-in-gcp/setup_gcp.sh "$(pwd)" --network weroad-vpc-1-development --subnet weroad-eu-subnet-1-development
   ```
3. Report the machine name created or any errors.

The script will:
- Resolve the target project from `BRAIN_CLONE_GCP`, then `gcloud config get-value project`, then `GCP_PROJECT_ID`
- Create a stock Ubuntu Compute Engine VM named `super-<username>-<MMDD-HHMMSS>`
- Run a startup script that installs core dependencies
- With `--desktop`: additionally install XFCE4 and XRDP, create the `allow-xrdp` firewall rule, and print the RDP connection address
- Wait for SSH readiness, copy `.env.local` and optional `sources.md`, then bootstrap `super`
- Print the SSH command plus manual start/stop/delete commands for the workstation

## Environment Variables

Set these in your project's `.env.local`:

- `BRAIN_CLONE_GCP` — GCP project ID for the VM
- `BRAIN_CLONE_USERNAME` — Local username for XRDP login (optional)
- `BRAIN_CLONE_PASSWORD` — Password for the local XRDP user (optional)

If `BRAIN_CLONE_USERNAME` and `BRAIN_CLONE_PASSWORD` are provided, the startup script creates the user with sudo access and configures XRDP automatically.

## RDP Access

After the VM is ready (only when `--desktop` is used):
1. The `allow-xrdp` firewall rule is created automatically in your GCP project (port 3389). The VM is tagged with `xrdp` for this purpose.
2. If you did not set `BRAIN_CLONE_USERNAME`/`BRAIN_CLONE_PASSWORD`, create a local user manually:
   ```bash
   sudo adduser <username>
   ```
3. Connect via RDP to the VM's external IP on port 3389. The XRDP session will launch XFCE automatically.
