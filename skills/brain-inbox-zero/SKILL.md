---
name: brain-inbox-zero
description: >
  Interactively triage the user's unread messages toward inbox zero across BOTH Gmail and Slack:
  fetch unread email threads and recent Slack messages aimed at the user (DMs + @mentions), then
  one at a time give a tight summary and an action menu — reply (drafted in the user's voice),
  mark read, archive, react, schedule a meeting, delegate/forward, open, or skip. Use whenever the
  user says "inbox zero", "process my email", "check my slack", "go through my unread", "triage my
  inbox", "clear my inbox", "catch me up on messages", "help me with my email/slack", or otherwise
  wants to work through their email and/or Slack one message at a time and decide what to do with
  each. Prefer this skill for any "deal with my messages" request, even when the user doesn't say
  the exact words — it beats ad-hoc gws/Slack calls because it summarizes, threads replies
  correctly, and keeps you in control of every send.
---

# Inbox Zero

Work through unread messages — **email and Slack** — **one item at a time**. For each: a tight
summary, then an action menu. You act only on the user's pick. The goal is momentum — clear the
backlog fast without ever sending, reacting, or scheduling anything the user didn't approve.

## Why this shape

Triage stalls when it's a wall of text or when the tool does something irreversible on its own.
So this skill shows exactly one thread at a time, keeps summaries scannable, and treats every
outbound action (send, calendar invite) as a confirm-first step. Drafting a reply is safe and
reversible; sending is not — so replies default to a saved Gmail **draft** the user can send
themselves, and direct sending happens only on an explicit "send it".

## Configuration

```
GMAIL: via the `gws` CLI (never the Gmail MCP) — see brain CLAUDE.md
SLACK:  via the mcp__claude_ai_Slack__* tools (search / read / send / react)
TIMEZONE: Europe/Rome (WeRoad default; override if the user says otherwise)
SCRIPTS: this skill's scripts/ dir — list_unread.py, read_thread.py, gmail_reply.py
VOICE: match the user's writing voice — see memory [[tone-of-voice]]
SLACK_LOOKBACK: 24h (how far back the Slack "needs my attention" search reaches)
```

The three scripts own the fiddly Gmail mechanics (base64url bodies, RFC822 reply MIME, threading
headers) so you don't hand-roll them. Call them with `python3 <skill-dir>/scripts/<name>.py`.
Slack has no scripts — the MCP tools do the work directly.

**Slack has no "unread" or "mark-read" API here.** There's no endpoint to enumerate unread or clear
a badge — the tools are search + read + send + react. So the Slack pass approximates "needs my
attention" as *recent messages directed at you* (DMs + @mentions within SLACK_LOOKBACK), and the
Slack actions are reply / react / open / skip — not mark-read/archive. Be upfront about this if the
user expects a literal unread count.

## Arguments

Read the skill argument for scope overrides. Sensible defaults, all optional:
- default: **both channels** — email first (Part A), then Slack (Part B)
- default email order: **least-important-first** — clear the noise, then focus on what needs you
  (see Step 1). `newest` / `oldest` force plain chronological order instead.
- `email` → email only · `slack` → Slack only
- `human` / `skip newsletters` → drop promotions/updates/social + no-reply (`--skip-bulk`)
- a number (e.g. `10`) → cap the email batch (`--max N`, default 25)
- `7d` / `48h` → widen the Slack lookback window
- a free-text query → pass through to email as `--query "..."` (Gmail search syntax)

Run the two parts back-to-back in one session unless the argument scopes to one. Keep the
one-at-a-time loop across both — don't switch to dumping a Slack list just because it's a new
channel.

## Part A — Email

## Step 1 — Build and prioritize the queue

```bash
python3 <skill-dir>/scripts/list_unread.py [--max N] [--order oldest] [--skip-bulk] [--query "..."]
```

It returns a JSON array of `{threadId, subject, from, date, snippet, messages}`.

**Then sort by importance, ascending — least important first.** The point is to clear the noise fast
so the user's attention is spent only on what's left. Read the `from`/`subject`/`snippet` of each
thread and bucket it (this is judgment, not a rigid rule — a "notification" about a failed
production build can be important; use sense):

- **Noise** — automated/transactional mail with no ask: build/processing notifications, spend and
  usage alerts, verification links, vendor trials and marketing, newsletters, no-reply senders,
  service accounts (e.g. `via Monkeys Leads`). Fast to clear.
- **FYI** — a real human wrote it, but the user is on CC or a distribution list and nothing is asked
  of *them* (broadcasts, "for your awareness" threads). Quick to read/skip/archive.
- **Needs you** — the user is addressed directly, is an active participant, or a decision/reply is
  being waited on. This is where the focus goes — save it for last.

Open with a one-line lay of the land grouped by bucket, so the shape of the work is clear:

> "**14 unread:** 6 look like noise (notifications, a couple of trials), 5 FYI threads you're CC'd
> on, and 3 that actually need you. Let's clear the noise first."

**Offer to batch-clear the Noise bucket in one go** rather than forcing a one-by-one march through
obvious archives:

> "Want me to archive all 6 noise ones in a batch, or go through them one at a time?"

If they say batch, list the 6 subjects, archive them together on confirmation, and report the
count. Then drop into the normal one-at-a-time loop for FYI, and finally Needs-you — newest first
within each bucket. If the user forced `newest`/`oldest`, skip the bucketing and just go
chronologically. Don't dump the full list mid-loop; the point is still one at a time once the noise
is gone.

## Step 2 — The triage loop (repeat per thread)

### 2a. Read the thread

```bash
python3 <skill-dir>/scripts/read_thread.py <threadId>
```

Gives you the decoded chronological transcript plus a `reply_target` (correct To/Cc, subject,
and threading headers) you'll hand to `gmail_reply.py` if the user chooses to reply.

### 2b. Summarize (keep it scannable)

Lead with a progress marker, then a compact block. Adapt length to the thread — a one-line
notification needs one line; a 12-message decision thread needs the gist of where it landed and
what's now being asked of the user.

```
[3/14] · <sender name> · <subject>
<1–3 sentences: what this is and what, if anything, they want from you.>
Asks: <the specific decision/action requested, or "none — FYI">
```

Read what's actually being requested — surface the *ask*, not just the topic. If a thread is a
long back-and-forth, say where it stands and who's waiting on whom. If it's in Italian, summarize
in English but keep the reply in the sender's language.

### 2c. Offer an action menu

Present a short numbered menu, **tailored to the thread**. Don't show "reply" for a no-reply
notification; do show "unsubscribe/archive" for a newsletter. A human email that asks a question
leads with reply. Typical menu:

```
  1. Reply        — I'll draft it in your voice, you review
  2. Archive      — mark read + remove from inbox (inbox-zero)
  3. Mark read    — mark read, keep in inbox
  4. Schedule     — check your calendar, propose times / send an invite
  5. Delegate     — forward to someone with a note
  6. Skip         — leave unread, next thread
  7. Show full    — print the whole thread text
  q. Stop         — end the session with a recap
```

Recommend the obvious move for that thread ("This looks like a quick yes — want me to draft it, or
just archive?"), but let the user drive. Accept natural language, not just numbers ("draft a reply
saying I'm in", "archive this and the next two GitBook ones", "skip"). Batch when they ask to.

## Action playbooks

### Reply — draft in the user's voice
1. If you don't already know the user's voice this session, skim memory [[tone-of-voice]] once for
   register (direct, warm, low-ceremony). Match the sender's language.
2. Draft the reply. Show the **full text** inline and ask: *save as draft, send it, or edit?*
   Never send without an explicit go.
3. Write the body to a temp file (handles newlines/quotes cleanly), then:
   ```bash
   python3 <skill-dir>/scripts/gmail_reply.py --thread <threadId> \
     --to "<reply_target.to>" --cc "<reply_target.cc>" \
     --subject "<reply_target.subject>" \
     --in-reply-to "<reply_target.in_reply_to>" \
     --references "<reply_target.references>" \
     --body-file <tmpfile>          # add --send ONLY after explicit approval
   ```
   Default (no `--send`) saves a Gmail draft nested in the thread and prints a drafts link.
   `--send` sends it. After a send, offer to archive the thread.

### Archive (inbox-zero) / Mark read
Both use `messages.modify` on the thread's messages. Mark-read removes `UNREAD`; archive also
removes `INBOX`. Apply to every message in the thread:
```bash
gws gmail users messages modify --params '{"userId":"me","id":"<messageId>"}' \
  --json '{"removeLabelIds":["UNREAD"]}'               # mark read
gws gmail users messages modify --params '{"userId":"me","id":"<messageId>"}' \
  --json '{"removeLabelIds":["UNREAD","INBOX"]}'        # archive
```
Message ids are in `read_thread.py`'s `messageIds` array — loop over them. These are label
changes and fully reversible, so no confirmation needed — just do it and confirm ("Archived.").

### Schedule a meeting
1. Read free/busy for the next few business days:
   ```bash
   gws calendar freebusy query --json '{"timeMin":"<nowUTC>","timeMax":"<+5dUTC>",
     "items":[{"id":"primary"}]}'
   ```
2. Propose 2–3 concrete slots (working hours, TIMEZONE). Let the user pick — or ask what to send.
3. On a pick, **confirm attendees + time**, then either:
   - create the invite (outward-facing → confirm first):
     ```bash
     gws calendar events insert --params '{"calendarId":"primary","sendUpdates":"all"}' \
       --json '{"summary":"<title>","start":{"dateTime":"...","timeZone":"Europe/Rome"},
       "end":{"dateTime":"...","timeZone":"Europe/Rome"},
       "attendees":[{"email":"<their-address>"}]}'
     ```
   - or draft a reply proposing the times (use the Reply playbook) if they'd rather agree first.

### Delegate / forward
Draft a short forwarding note ("Passing to you — can you take this?") and reply/forward to the
delegate. Use the same draft-first rule.

### Skip / Show full
Skip leaves the thread untouched (still unread) and moves on. Show full prints the transcript from
`read_thread.py` so the user can read the whole exchange before deciding.

---

## Part B — Slack

Same one-at-a-time loop, different medium. Run this after Part A (or on its own if the argument is
`slack`). Because there's no unread feed, you build the queue by searching for what's aimed at the
user, then triage each conversation.

### Step B1 — Get consent, then build the Slack queue

Searching DMs and private channels needs the user's OK. Say once: *"To scan your Slack DMs and
mentions I'll search your private conversations — ok to go ahead?"* Wait for yes before calling
`slack_search_public_and_private` (public-only search doesn't need this, but it misses DMs, which
is where most "needs me" traffic lives).

Search for messages directed at the user, newest first, then window client-side:

```
mcp__claude_ai_Slack__slack_search_public_and_private(
  query="to:me", sort="timestamp", sort_dir="desc", limit=20)
```

⚠️ **Do NOT put `after:<date>` in the query.** In this integration the `after:` modifier combined
with `to:me`/`from:me`/mention filters **silently returns zero results** — the same query without
it works. So sort by `timestamp` desc and drop anything older than SLACK_LOOKBACK yourself using the
`Time:`/`Message_ts` on each result. (Verified 2026-07-03: `to:me after:…` → "No results found";
bare `to:me` → the real DMs.)

`to:me` avoids hardcoding a user id and catches DMs + messages addressed to the user. If it looks
thin, run a second pass for mentions — resolve the user's own id via `slack_read_user_profile` (no
args = current user) and search `query="<@THAT_ID>"` (again, no `after:`). Dedupe results and
**group by conversation** (channel or DM) so a burst of messages in one thread is one queue item,
not ten. Skip the user's own outgoing messages and bot noise.

Open with a one-liner: *"On Slack, you've got 3 conversations from the last 24h that look aimed at
you — a DM from X, a mention in #Y…"* then start the loop.

### Step B2 — The Slack triage loop (repeat per conversation)

Read the surrounding context so the summary is accurate:
- DM → `slack_read_channel(channel_id=<userId or DM id>)`
- Channel mention or thread → `slack_read_thread(channel_id, message_ts)` for the full exchange.

Summarize in the same compact shape, then offer a **Slack-appropriate** menu (no mark-read/archive
— those don't exist here):

```
[S 2/3] · <sender> · #channel or DM
<1–2 sentences: what they're saying and what, if anything, they want from you.>
Asks: <the specific ask, or "none — FYI">

  1. Reply      — I'll draft it in your voice, you review
  2. React      — acknowledge with an emoji (👍 / ✅ / 👀)
  3. Open        — give me the Slack link, I'll handle it there
  4. Skip        — next conversation
  q. Stop        — end with a recap
```

### Slack action playbooks

**Reply** — draft in the user's voice (match register + language). Show the full text inline and
ask *save as draft, send it, or edit?* On approval:
- draft (default, safe): `slack_send_message_draft(channel_id, text, thread_ts=<parent ts if in a thread>)`
- send: `slack_send_message(channel_id, text, thread_ts=<parent ts>)` — reply **in-thread** when the
  source was a thread, so you don't fragment the conversation.
Never send without an explicit go, same as email.

**React** — `slack_add_reaction(channel_id, message_ts, emoji)`. A lightweight ack ("got it") that
clears the item without a full reply. Confirm the emoji if it's anything but an obvious 👍.

**Open** — hand back the Slack deep link (`https://slack.com/app_redirect?channel=<channel_id>`) so
the user can jump in and handle it live. Then move on.

**Skip** — leave it, next conversation.

## Step 3 — Recap

When the user stops (or both queues are empty), give a short tally **across email and Slack**:
threads/conversations processed, drafts saved (with links), messages sent, reactions added, emails
archived, meetings scheduled, and what's left untouched. If drafts were saved (Gmail or Slack),
remind the user they're waiting for review and send.

## Guardrails

- **Every state change is the user's explicit choice — never a side-effect.** Reading, summarizing,
  and searching are non-mutating (verified: `threads.get` does not mark read), so do them freely.
  But **mark-read, archive, RSVP, send, reply, and react happen ONLY when the user picks that exact
  action** (or gives explicit batch consent). Do **not** bundle a label change onto another action:
  accepting an invite does **not** archive the email, sending a reply does **not** archive the
  thread. After an Accept or a Send, *offer* to archive as a separate step and wait — don't infer it.
- **Never send mail, send a Slack message, add a reaction, RSVP, or create/modify a calendar event
  without an explicit, in-context approval** of the exact content. Anything outward-facing
  (including a Slack emoji, which others see) is confirm-first.
- **Get consent before searching private Slack** (DMs / private channels) — ask once at the top of
  Part B.
- **One item at a time**, across both channels. Resist summarizing the whole batch up front — it
  kills the momentum the loop is designed to create.
- **Use `gws` for email** (never the Gmail MCP) and the **Slack MCP tools for Slack** (brain house
  rules).
- Keep summaries tight and skip the preamble — the user is trying to move fast.
