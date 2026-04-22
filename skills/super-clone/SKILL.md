---
name: super-clone
description: >-
  Create an OrbStack Ubuntu machine pre-configured for the current project,
  copying `.env.local` and `sources.md`. Optional XFCE desktop via XRDP.
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
   For a machine with XFCE desktop and XRDP:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh --desktop "$(pwd)"
   ```
   To copy a specific sources file (e.g. `sources.dev.super.md`) instead of the default `sources.md`:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh sources.dev.super.md
   ```
   Combine both:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh sources.dev.super.md --desktop
   ```
3. Report the machine name created or any errors.

The script will:
- Ensure a `super-base` OrbStack machine exists with `git`, `nodejs`, and `npm` pre-installed
- Clone it to a new machine named `super-<username>-<MMDD-HHMMSS>`
- Copy `.env.local` from the project into `~/brain/` on the new machine
- Copy `sources.md` (or an explicit `.md` file you pass) into `~/brain/sources.md` on the new machine
- Install `super` and run `super install --all` inside the machine
- With `--desktop`: additionally install XFCE4 and XRDP, then print the RDP connection address

## Environment Variables

Set these in your project's `.env.local`:

- `BRAIN_CLONE_USERNAME` — Local username for XRDP login (optional)
- `BRAIN_CLONE_PASSWORD` — Password for the local XRDP user (optional)

If provided, the script creates the user with sudo access and configures XRDP credentials automatically.
