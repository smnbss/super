#!/usr/bin/env python3
"""List unread inbox threads as compact JSON for the inbox-zero triage queue.

Two-tier fetch keeps it fast: threads.list gets the ids + snippets, then a
metadata-only threads.get per thread grabs just the Subject/From/Date headers
(no bodies). Bodies are fetched later, one thread at a time, by read_thread.py.

Usage:
    list_unread.py [--max N] [--order newest|oldest] [--skip-bulk] [--query "..."]

Output: a JSON array on stdout, one object per thread:
    {threadId, subject, from, date, snippet, messages}
Newest-first is the Gmail default; --order oldest reverses it.
"""
import argparse
import json
import subprocess
import sys


def gws(args, params=None):
    cmd = ["gws"] + args
    if params is not None:
        cmd += ["--params", json.dumps(params)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("--order", choices=["newest", "oldest"], default="newest")
    ap.add_argument("--skip-bulk", action="store_true",
                    help="drop promotions/updates/social and no-reply senders")
    ap.add_argument("--query", default=None,
                    help="override the Gmail search query entirely")
    a = ap.parse_args()

    q = a.query or "is:unread in:inbox"
    if a.skip_bulk and not a.query:
        q += " -category:promotions -category:updates -category:social -from:noreply"

    listing = gws(["gmail", "users", "threads", "list"],
                  {"userId": "me", "q": q, "maxResults": a.max})
    threads = listing.get("threads", [])

    out = []
    for t in threads:
        detail = gws(["gmail", "users", "threads", "get"],
                     {"userId": "me", "id": t["id"], "format": "metadata",
                      "metadataHeaders": ["Subject", "From", "Date"]})
        msgs = detail.get("messages", [])
        last = msgs[-1] if msgs else {}
        hdrs = last.get("payload", {}).get("headers", [])
        out.append({
            "threadId": t["id"],
            "subject": header(hdrs, "Subject") or "(no subject)",
            "from": header(hdrs, "From"),
            "date": header(hdrs, "Date"),
            "snippet": t.get("snippet", "").strip(),
            "messages": len(msgs),
        })

    if a.order == "oldest":
        out.reverse()
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
