---
name: super-persist
description: >-
  Summarize the current conversation and persist the full context as a markdown
  entry in the current super session file.
---

# /super-persist

Summarize the current conversation and save the full context to the current super session file.

## When to use
- When the user says "save this", "persist", "summarize and save", "checkpoint", or "save progress"
- At the end of a long session before switching context
- When the user wants to capture decisions, outcomes, and next steps in the session log

## Steps

1. **Find the active session file**
   - Check the `SUPER_SESSION_FILE` environment variable first (required when multiple CLIs run in parallel)
   - If not set, use the most recently modified `.md` file in `.super/sessions/`

2. **Summarize the conversation**
   - Extract key decisions made
   - List major actions taken (files changed, commands run, APIs called)
   - Note outcomes and current state
   - Identify any blockers or open questions
   - Suggest next steps if relevant

3. **Append the summary to the session file**
   - Append a markdown block in this format:
   ```markdown
   
   ---
   
   ### 📝 Session Summary — `YYYY-MM-DD HH:MM:SS`
   
   **Decisions:**
   - ...
   
   **Actions:**
   - ...
   
   **Outcomes:**
   - ...
   
   **Next Steps:**
   - ...
   
   ```
   - Use the current local date/time for the timestamp

4. **Confirm**
   - Report that the summary has been saved to the session file name.
