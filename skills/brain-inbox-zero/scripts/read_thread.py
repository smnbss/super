#!/usr/bin/env python3
"""Fetch one Gmail thread and render it as clean JSON for summarizing + replying.

Gmail returns message bodies as base64url-encoded MIME parts buried in a
nested payload tree; the readable text/plain part has to be walked out and
decoded. This script does that once so the triage loop gets a flat, readable
transcript plus a ready-to-use reply_target (addresses + threading headers)
for gmail_reply.py.

Usage:
    read_thread.py <threadId>

Output (JSON on stdout):
    {
      "threadId", "subject", "participants": [...],
      "messages": [{from, to, cc, date, body}, ...],   # chronological
      "reply_target": {                                 # from the LAST message
          "to", "cc", "subject", "in_reply_to", "references", "threadId"
      }
    }
"""
import base64
import json
import re
import subprocess
import sys


def gws(args, params):
    r = subprocess.run(["gws"] + args + ["--params", json.dumps(params)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def decode(data):
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")


def strip_html(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</p>", "\n\n", html)
    text = re.sub(r"(?s)<[^>]+>", "", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def find_body(payload):
    """Walk the MIME tree; prefer text/plain, fall back to stripped text/html."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/plain" and body.get("data"):
        return decode(body["data"])
    if mime == "text/html" and body.get("data"):
        return strip_html(decode(body["data"]))
    plain = html = ""
    for part in payload.get("parts", []) or []:
        got = find_body(part)
        if got and part.get("mimeType") == "text/plain" and not plain:
            plain = got
        elif got and not html:
            html = got
    return plain or html


def trim_quotes(text):
    """Drop the trailing quoted history so the summary sees the new content."""
    lines = text.splitlines()
    out = []
    for ln in lines:
        if re.match(r"^\s*On .*wrote:\s*$", ln) or re.match(r"^\s*-{2,}\s*Original Message", ln, re.I):
            break
        out.append(ln)
    # drop a trailing run of quoted (>) lines
    while out and out[-1].lstrip().startswith(">"):
        out.pop()
    return "\n".join(out).strip() or text.strip()


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: read_thread.py <threadId>\n")
        sys.exit(2)
    tid = sys.argv[1]
    thread = gws(["gmail", "users", "threads", "get"],
                 {"userId": "me", "id": tid, "format": "full"})
    msgs = thread.get("messages", [])

    rendered = []
    participants = set()
    message_ids = []
    last_hdrs = []
    for m in msgs:
        hdrs = m.get("payload", {}).get("headers", [])
        last_hdrs = hdrs
        message_ids.append(m.get("id"))
        frm = header(hdrs, "From")
        participants.add(frm)
        rendered.append({
            "id": m.get("id"),
            "from": frm,
            "to": header(hdrs, "To"),
            "cc": header(hdrs, "Cc"),
            "date": header(hdrs, "Date"),
            "body": trim_quotes(find_body(m.get("payload", {}))),
        })

    subject = header(msgs[0]["payload"]["headers"], "Subject") if msgs else ""
    re_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg_id = header(last_hdrs, "Message-ID")
    prior_refs = header(last_hdrs, "References")
    references = (prior_refs + " " + msg_id).strip() if prior_refs else msg_id
    reply_to = header(last_hdrs, "Reply-To") or header(last_hdrs, "From")

    print(json.dumps({
        "threadId": tid,
        "subject": subject,
        "participants": sorted(participants),
        "messageIds": message_ids,
        "messages": rendered,
        "reply_target": {
            "to": reply_to,
            "cc": header(last_hdrs, "Cc"),
            "subject": re_subject,
            "in_reply_to": msg_id,
            "references": references,
            "threadId": tid,
        },
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
