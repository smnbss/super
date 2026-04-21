---
name: super-resume
description: >-
  Read the current super session file and produce a max 1000 character
  description of what the session is about.
---

# /super-resume

Read the current super session file and distill it into a brief description of what the session is about.

## When to use
- When the user says "resume", "what was this about", "summarize the session", or "describe this session"
- At the start of a resumed session to quickly understand the context
- When the user wants a quick overview without reading the full session log

## Steps

1. **Find the active session file**
   - Check the `SUPER_SESSION_FILE` environment variable first (required when multiple CLIs run in parallel)
   - If not set, use the most recently modified `.md` file in `.super/sessions/`

2. **Read the session file**
   - Load the full markdown content of the session file

3. **Distill a concise description**
   - Identify the main topic, goal, or task of the session
   - Mention any key decisions, blockers, or next steps if they clarify the purpose
   - Keep the description under 1000 characters
   - Write it as plain, natural language (not a structured list)

4. **Output the description**
   - Present the description to the user without modifying the session file
