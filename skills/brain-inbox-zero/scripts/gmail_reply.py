#!/usr/bin/env python3
"""Build a properly-threaded reply and either save it as a draft or send it.

Replying correctly means base64url-encoding an RFC822 message AND setting the
In-Reply-To / References headers plus the threadId so Gmail nests it in the
existing conversation instead of starting a new one. This script owns that
fiddly bit so the triage loop never hand-rolls MIME.

Default is DRAFT (nothing leaves the outbox). Pass --send only after the
user has explicitly approved the exact text.

Usage:
    gmail_reply.py --thread <id> --to <addr[,addr]> --subject <s>
                   --in-reply-to <message-id> [--references <ids>]
                   [--cc <addr[,addr]>] (--body-file <path> | --body <text>)
                   [--send]

Output: JSON with the created draft/message id and a Gmail deep-link.
"""
import argparse
import base64
import json
import subprocess
import sys
from email.message import EmailMessage


def gws_json(args, body):
    r = subprocess.run(["gws"] + args + ["--json", json.dumps(body)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thread", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--cc", default="")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--in-reply-to", default="")
    ap.add_argument("--references", default="")
    ap.add_argument("--body-file")
    ap.add_argument("--body")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()

    if a.body_file:
        with open(a.body_file, encoding="utf-8") as f:
            body = f.read()
    elif a.body is not None:
        body = a.body
    else:
        sys.stderr.write("provide --body or --body-file\n")
        sys.exit(2)

    msg = EmailMessage()
    msg["To"] = a.to
    if a.cc:
        msg["Cc"] = a.cc
    msg["Subject"] = a.subject
    if a.in_reply_to:
        msg["In-Reply-To"] = a.in_reply_to
    if a.references:
        msg["References"] = a.references
    msg.set_content(body)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")

    if a.send:
        res = gws_json(["gmail", "users", "messages", "send"],
                       {"raw": raw, "threadId": a.thread})
        link = f"https://mail.google.com/mail/u/0/#all/{a.thread}"
        print(json.dumps({"action": "sent", "id": res.get("id"),
                          "threadId": a.thread, "link": link}, indent=2))
    else:
        res = gws_json(["gmail", "users", "drafts", "create"],
                       {"message": {"raw": raw, "threadId": a.thread}})
        did = res.get("id")
        link = "https://mail.google.com/mail/u/0/#drafts"
        print(json.dumps({"action": "draft", "draftId": did,
                          "threadId": a.thread, "link": link}, indent=2))


if __name__ == "__main__":
    main()
