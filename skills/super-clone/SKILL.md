---
name: super-clone
description: >-
  Create an OrbStack Ubuntu machine pre-configured for the current project,
  copying `.env.local`, `sources.md`, and `sources.github.md`. Optional GNOME desktop via XRDP.
---

# /super-clone

Create a cloned OrbStack Ubuntu machine for the current project.

## When to use
- When the user says "super clone", "setup ubuntu", "create ubuntu machine", or asks to provision an OrbStack environment
- When setting up a new Ubuntu machine with project files copied over
- When the user asks for an Ubuntu desktop / RDP access to the machine

## Steps

1. Locate the `setup_ubuntu.sh` script in the skill directory:
   - `.agents/skills/super-clone/setup_ubuntu.sh` (Codex and Gemini)
   - `.claude/skills/super-clone/setup_ubuntu.sh` (Claude)
2. Run it with the current working directory as the project path:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh "$(pwd)"
   ```
   For a machine with GNOME desktop and XRDP:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh "$(pwd)" --desktop
   ```
   By default it copies both `sources.md` (non-GitHub → `src/`) and `sources.github.md` (repos → `github/`).
   To copy a single specific sources file (e.g. `sources.dev.super.md`) as `sources.md` instead, pass it positionally or via `--source` (this skips the `sources.github.md` companion):
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh sources.dev.super.md
   <skill-dir>/super-clone/setup_ubuntu.sh --source sources.dev.super.md
   ```
   Combine both:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh sources.dev.super.md --desktop
   ```
   To reuse (and upgrade) an existing machine instead of creating a new timestamped one, pass `--name`:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh --name super-dev
   ```
   If `super-dev` exists, it will be started (if stopped) and `super install --all` will run inside it to refresh tooling. If it doesn't exist, a new machine is created with that name.
3. Report the machine name created or any errors.

The script will:
- Ensure a `super-base` OrbStack machine exists, pre-baked with: `git`, `curl`, `zstd`, Node.js 20.19.0, Ollama, Chromium, the Google Cloud CLI, and the `@anthropic-ai/claude-code`, `@openai/codex`, `@google/gemini-cli` npm globals
- Clone it to a new machine named `super-<username>-<MMDD-HHMMSS>`
- Copy `.env.local` from the project into `~/brain/` on the new machine
- Copy `sources.md` and `sources.github.md` into `~/brain/` on the new machine (or, with `--source`, just the explicit `.md` file you pass, landing as `~/brain/sources.md`)
- Install `super` (git clone into `~/.super`) and run `super install --all` inside the machine
- With `--desktop`: additionally install GNOME (`ubuntu-desktop-minimal`) and XRDP, force the GNOME-on-Xorg session for xrdp, and print the RDP connection address. The base `super-base` machine is built once on Ubuntu 24.04 LTS — to rebuild it on a newer Ubuntu, `orb delete super-base` and rerun.

## Environment Variables

Set these in your project's `.env.local`:

- `BRAIN_CLONE_USERNAME` — Local username for XRDP login (optional)
- `BRAIN_CLONE_PASSWORD` — Password for the local XRDP user (optional)

If provided, the script creates the user with sudo access and configures XRDP credentials automatically.
