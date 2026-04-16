---
name: super-clone
description: Create an OrbStack Ubuntu machine pre-configured for the current project, copying .env.local and sources.md.
---

# /super-clone

Create a cloned OrbStack Ubuntu machine for the current project.

## When to use
- When the user says "super clone", "setup ubuntu", "create ubuntu machine", or asks to provision an OrbStack environment
- When setting up a new Ubuntu machine with project files copied over

## Steps

1. Locate the `setup_ubuntu.sh` script in the skill directory:
   - `.agents/skills/super-clone/setup_ubuntu.sh` (Claude)
   - `.codex/skills/super-clone/setup_ubuntu.sh` (Codex)
   - `.gemini/skills/super-clone/setup_ubuntu.sh` (Gemini)
2. Run it with the current working directory as the project path:
   ```bash
   <skill-dir>/super-clone/setup_ubuntu.sh "$(pwd)"
   ```
3. Report the machine name created or any errors.

The script will:
- Ensure a `super-base` OrbStack machine exists with `git`, `nodejs`, and `npm` pre-installed
- Clone it to a new `super-*` machine
- Copy `.env.local` and `sources.md` from the project into `~/project/` on the new machine
- Install `super` and run `super install --all` inside the machine
