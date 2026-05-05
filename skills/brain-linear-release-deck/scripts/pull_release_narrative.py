#!/usr/bin/env python3
"""Pull release issues + comments from Linear and build an extended narrative.

This is the deck skill's own data layer — it does *not* depend on
brain-linear-release-summary. The summary skill optimises for a tight
markdown report; the deck needs richer per-issue context (full description,
all comments, every image reference, heuristic bet assignment) so the
synthesis step has enough material to write punchy slides without losing
fidelity.

The output file lives at
`outputs/releases-decks/<slug>/<slug>-narrative.json` (each window gets
its own subfolder under `outputs/releases-decks/`) and contains:
  - releases: per-issue records (id, ship date, title, platform,
    description, all comments, inline images, bet assignment, impact
    flag + extracted KPIs when present)
  - aggregates: counts per bet, per platform; top measured-impact ones

The deck-synthesis step reads this file (instead of an impact-summary
markdown) and writes the deck spec.

Usage:
    set -a; source .env.local; set +a    # gives us LINEAR_TOKEN
    python pull_release_narrative.py --window "2026-01..2026-04" \
        --output outputs/releases-decks/2026-01-2026-04/2026-01-2026-04-narrative.json

The window grammar matches brain-linear-release-summary so the same slug
convention applies.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.linear.app/graphql"
PROJECT_ID = "98945ef1-bb21-4155-8de6-b9a15302bb8d"  # MOL release-notes
PROJECT_URL = "https://linear.app/weroad/project/release-notes-1bc4d3fcb947/issues"

# Title-date sanity: titles must start `YYYY-MM-DD - …` to count as releases
TITLE_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\b")
JUNK_RE = re.compile(
    r"(test|asdf|aaaa|ddd|RELEASE_EMAIL_TO|safsa|sdfas|\[TEST\]|Test Release Note)",
    re.IGNORECASE,
)
IMG_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>https://uploads\.linear\.app/[^)\s]+)\)"
)
# Empirical impact-comment shapes. Mautino opens with `## 📊 Output misurati`
# (sometimes followed by bold KPI tables); Parenti opens with `## Impact
# update — N days post-release` (older variant uses `**…**` bold instead of
# H2). The "Output misurati" Italian phrase is unambiguous; the "Impact
# update" English phrase is matched at the start of a heading or bold run
# so it won't false-positive on offhand mentions in chitchat.
IMPACT_PATTERNS = (
    re.compile(r"##\s*📊\s*Output\s+misurati", re.IGNORECASE),
    re.compile(
        r"(?:^|\n)\s*(?:#{1,6}\s*|\*\*)\s*Impact\s+update\s*[—–-]\s*\d+\s*days?\s*post-release",
        re.IGNORECASE,
    ),
)


# ---------- Window parsing ----------

def parse_window(spec: str, today: dt.date) -> tuple[dt.date, dt.date, str, str]:
    """Return (start_inclusive, end_inclusive, machine_slug, human_label).

    Mirrors the grammar used by brain-linear-release-summary so slugs match.
    """
    s = spec.strip()
    s_low = s.lower()

    # last N days (rolling window ending today)
    m = re.fullmatch(r"last\s+(\d+)\s+days?", s_low)
    if m:
        n = int(m.group(1))
        end = today
        start = end - dt.timedelta(days=n - 1)
        slug = f"{today.isoformat()}-last-{n}-days"
        return start, end, slug, f"last {n} days (ending {end.isoformat()})"

    # last N months (rolling)
    m = re.fullmatch(r"last\s+(\d+)\s+months?", s_low)
    if m:
        n = int(m.group(1))
        end = today
        start_year = end.year
        start_month = end.month - n + 1
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start = dt.date(start_year, start_month, 1)
        slug = f"{today.isoformat()}-last-{n}-months"
        return start, end, slug, f"last {n} months (ending {end.isoformat()})"

    # full year
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        y = int(m.group(1))
        return (dt.date(y, 1, 1), dt.date(y, 12, 31), str(y),
                f"calendar year {y}")

    # quarter — accept "Q1 2026", "2026-Q1", "q1 2026"
    m = re.fullmatch(r"(?:Q([1-4])\s*(\d{4})|(\d{4})[-\s]Q([1-4]))",
                     s, re.IGNORECASE)
    if m:
        q = int(m.group(1) or m.group(4))
        y = int(m.group(2) or m.group(3))
        first_month = (q - 1) * 3 + 1
        last_month = first_month + 2
        next_month_first = (
            dt.date(y, last_month + 1, 1) if last_month < 12
            else dt.date(y + 1, 1, 1)
        )
        end = next_month_first - dt.timedelta(days=1)
        return (dt.date(y, first_month, 1), end, f"{y}-q{q}",
                f"Q{q} {y}")

    # year-month range "YYYY-MM..YYYY-MM"
    m = re.fullmatch(r"(\d{4})-(\d{2})\.\.(\d{4})-(\d{2})", s)
    if m:
        y1, m1, y2, m2 = map(int, m.groups())
        start = dt.date(y1, m1, 1)
        # last day of (y2, m2)
        next_first = (dt.date(y2, m2 + 1, 1) if m2 < 12
                      else dt.date(y2 + 1, 1, 1))
        end = next_first - dt.timedelta(days=1)
        slug = f"{y1:04d}-{m1:02d}-{y2:04d}-{m2:02d}"
        return start, end, slug, f"{y1}-{m1:02d} → {y2}-{m2:02d}"

    # single month "YYYY-MM" or "May 2026"
    m = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        next_first = (dt.date(y, mo + 1, 1) if mo < 12
                      else dt.date(y + 1, 1, 1))
        end = next_first - dt.timedelta(days=1)
        return (dt.date(y, mo, 1), end, f"{y}-{mo:02d}",
                end.strftime("%B %Y"))

    raise SystemExit(f"unrecognized window: {spec!r}")


# ---------- Linear API ----------

def graphql(query: str, variables: dict | None = None,
            *, retries: int = 3) -> dict:
    body = json.dumps({"query": query,
                       "variables": variables or {}}).encode()
    token = os.environ.get("LINEAR_TOKEN")
    if not token:
        raise SystemExit("LINEAR_TOKEN env var not set — load .env.local first.")

    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": token,
    })
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                payload = json.loads(r.read())
            if "errors" in payload:
                # Linear returns 200 + errors body for graphql errors
                raise RuntimeError(payload["errors"])
            return payload["data"]
        except (urllib.error.URLError, RuntimeError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            raise


ISSUES_QUERY_FIRST = """
query Issues($projectId: ID!) {
  issues(filter: {project: {id: {eq: $projectId}}},
         first: 100,
         includeArchived: true) {
    pageInfo { hasNextPage endCursor }
    nodes { %s }
  }
}
"""

ISSUES_QUERY_NEXT = """
query Issues($projectId: ID!, $cursor: String!) {
  issues(filter: {project: {id: {eq: $projectId}}},
         first: 100, after: $cursor,
         includeArchived: true) {
    pageInfo { hasNextPage endCursor }
    nodes { %s }
  }
}
"""

ISSUE_FIELDS = """
  id
  identifier
  title
  description
  createdAt
  updatedAt
  state { name }
  labels { nodes { name } }
  comments(first: 50) {
    nodes {
      id
      body
      createdAt
      user { name }
    }
  }
"""


def fetch_all_issues() -> list[dict]:
    """Linear's GraphQL refuses null `$cursor: String!`, so we use two
    query variants: one without the cursor for the first page, one with
    a non-null cursor for subsequent pages."""
    issues: list[dict] = []
    cursor: str | None = None
    page = 0
    while True:
        page += 1
        if cursor is None:
            data = graphql(ISSUES_QUERY_FIRST % ISSUE_FIELDS,
                           {"projectId": PROJECT_ID})
        else:
            data = graphql(ISSUES_QUERY_NEXT % ISSUE_FIELDS,
                           {"projectId": PROJECT_ID, "cursor": cursor})
        conn = data["issues"]
        issues.extend(conn["nodes"])
        print(f"  page {page}: +{len(conn['nodes'])} (total {len(issues)})",
              file=sys.stderr)
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
        time.sleep(0.2)  # gentle rate-limit buffer
    return issues


# ---------- Filtering & shaping ----------

def title_date(title: str) -> dt.date | None:
    m = TITLE_DATE_RE.match(title)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def title_platform(title: str) -> str:
    """Second " - " segment of the title — usually the platform/area name."""
    parts = [p.strip() for p in title.split(" - ")]
    return parts[1] if len(parts) > 1 else ""


def in_window(issue: dict, start: dt.date, end: dt.date) -> bool:
    d = title_date(issue["title"])
    return d is not None and start <= d <= end


def is_real_release(issue: dict) -> bool:
    title = issue["title"]
    if not TITLE_DATE_RE.match(title):
        return False
    if JUNK_RE.search(title):
        return False
    return True


def dedup_by_title(issues: list[dict]) -> list[dict]:
    """Many releases were re-imported during MOL migration. Keep the latest
    by createdAt for each title."""
    by_title: dict[str, dict] = {}
    for it in issues:
        prev = by_title.get(it["title"])
        if prev is None or it["createdAt"] > prev["createdAt"]:
            by_title[it["title"]] = it
    return sorted(by_title.values(),
                  key=lambda i: title_date(i["title"]) or dt.date.min)


# ---------- Bet assignment heuristics ----------
#
# We bucket each release into one of the four bets. The rules are
# pragmatic, not exhaustive — the model can override during synthesis if a
# release fits a different narrative angle for the window.

# Bet rules — each entry is (bet_name, [(weight, regex)]). Title segments
# carry more weight than body text. Most signals are matched as word
# boundaries to avoid common false positives like "ai" matching "Admin",
# "buy" matching "Buynana" partials, etc.
def _wb(*words: str) -> re.Pattern:
    """Word-boundary regex matching any of the given keywords/phrases."""
    parts = [re.escape(w) for w in words]
    return re.compile(r"(?<![\w-])(?:" + "|".join(parts) + r")(?![\w-])",
                      re.IGNORECASE)


BET_RULES: list[tuple[str, re.Pattern]] = [
    # AI bet — looking for the first-touch surfaces. "AI" alone is too
    # noisy; require it to be part of a compound term we actually use.
    ("AI", _wb(
        "AI Assistant", "AI on WhatsApp", "WhatsApp Assistant", "WhatsApp",
        "Salesbot", "Discord Salesbot", "AI bot", "LLM",
        "Perplexity", "ChatGPT", "Gemini",
    )),
    # Community bet
    ("Community", _wb(
        "WeMeet", "Community Portal", "Event Template", "Event Templates",
        "City Calendar", "Bulk Event", "Area Manager", "Self-hosted",
        "Self-Hosted", "Event Chat", "Event Timeline",
    )),
    # Operations bet
    ("Operations", _wb(
        "Buynana", "Partner Portal", "AdminCoord", "Admin-coord",
        "AdminBooking", "Appsmith", "Cost-Based", "Cost Submit",
        "Cost Submission", "Allotment", "TO_ALLOT", "P360",
        "Tour Operations", "Virtual Card", "Virtual Cards",
        "cancellation policy", "Auto pricing", "tour price",
        "Sellable Items", "Travel Diary", "Waiting-List", "Waiting Lists",
        "Itinerary Pre-Approval", "Post-Tour Survey", "Pax Details",
        "TP price", "TP push",
    )),
    # Conversion bet — checkout / search / discovery / SEO / identity
    ("Conversion", _wb(
        "Checkout", "deposit", "Compare", "Search", "Notify-me", "Notify me",
        "Wishlist", "Booking pillars", "Payment-terms", "Payment terms",
        "SSO Login", "MyWeRoad", "+1 Account", "+1 Accounts",
        "ICAO", "Performance", "SEO-boost", "SEO", "CWV",
        "Core Web Vitals", "Blog migration", "Departure modal",
        "Zero-Deposit", "Waiting List", "Recently-viewed", "Recently viewed",
        "Best-tour", "Best tour", "Group Flight", "Travel-near-you",
        "Travel near you", "Megamenu", "UTM",
    )),
]


def assign_bet(title: str, description: str, labels: list[str]) -> str:
    """Score each bet and return the winner.

    Title matches count 3×, label matches 2×, description 1×. Ties go to
    the first matching bet in the list (AI > Community > Operations >
    Conversion) so that a release that mentions both AI and a checkout
    surface (e.g. AI Assistant on the booking page) lands in AI rather
    than Conversion.
    """
    title_l = title or ""
    desc_l = description or ""
    labels_l = " ".join(labels)

    scores: dict[str, int] = {}
    for bet, pat in BET_RULES:
        s = (
            3 * len(pat.findall(title_l))
            + 2 * len(pat.findall(labels_l))
            + 1 * len(pat.findall(desc_l))
        )
        if s > 0:
            scores[bet] = s
    if not scores:
        return "Operations"  # internal-tooling catch-all
    # Highest score wins; ties broken by the order in BET_RULES (preserved)
    best = max(scores.items(), key=lambda kv: (kv[1], -[
        "AI", "Community", "Operations", "Conversion"
    ].index(kv[0])))
    return best[0]


# ---------- Impact comment extraction ----------

def is_impact_comment(body: str) -> bool:
    return any(p.search(body) for p in IMPACT_PATTERNS)


def extract_images(text: str) -> list[dict]:
    return [
        {"alt": m.group("alt"), "url": m.group("url")}
        for m in IMG_RE.finditer(text or "")
    ]


# ---------- Narrative builder ----------

def build_record(issue: dict) -> dict:
    title = issue["title"]
    description = issue.get("description") or ""
    labels = [n["name"] for n in issue.get("labels", {}).get("nodes", [])]
    comments = issue.get("comments", {}).get("nodes", [])

    # Shape comments + flag impact ones
    comments_out = []
    impact_comments = []
    for c in comments:
        body = c.get("body") or ""
        author = (c.get("user") or {}).get("name") or "(unknown)"
        rec = {
            "author": author,
            "createdAt": c["createdAt"],
            "body": body,
            "is_impact": is_impact_comment(body),
            "images": extract_images(body),
        }
        comments_out.append(rec)
        if rec["is_impact"]:
            impact_comments.append(rec)

    description_images = extract_images(description)
    has_gif = any(img["alt"].lower().endswith(".gif")
                  for img in description_images)

    return {
        "id": issue["identifier"],
        "uuid": issue["id"],
        "ship_date": (title_date(title) or dt.date.min).isoformat(),
        "title": title,
        "platform": title_platform(title),
        "state": issue.get("state", {}).get("name"),
        "labels": labels,
        "linear_url": f"https://linear.app/weroad/issue/{issue['identifier']}",
        "release_url": f"https://ask.weroad.app/releases/{issue['identifier']}",
        "description": description,
        "description_images": description_images,
        "has_gif_in_description": has_gif,
        "comments": comments_out,
        "impact_comments": impact_comments,
        "is_impact": bool(impact_comments),
        "bet": assign_bet(title, description, labels),
        "slide_worthy": (
            bool(impact_comments)
            or bool(description_images)
            or any(c["images"] for c in comments_out)
        ),
    }


def build_narrative(window: tuple[dt.date, dt.date, str, str],
                    issues_raw: list[dict]) -> dict:
    start, end, slug, label = window

    in_scope = [
        i for i in issues_raw
        if is_real_release(i) and in_window(i, start, end)
    ]
    deduped = dedup_by_title(in_scope)
    records = [build_record(i) for i in deduped]

    # Aggregates
    by_bet: dict[str, list[str]] = {}
    by_platform: dict[str, int] = {}
    impact_records: list[dict] = []
    for r in records:
        by_bet.setdefault(r["bet"], []).append(r["id"])
        by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
        if r["is_impact"]:
            impact_records.append(r)

    return {
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "slug": slug,
            "label": label,
        },
        "source": {
            "project_id": PROJECT_ID,
            "url": PROJECT_URL,
            "team": "MOL (Triage)",
            "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        "totals": {
            "release_count": len(records),
            "impact_count": sum(1 for r in records if r["is_impact"]),
            "with_images": sum(1 for r in records
                               if r["description_images"]),
            "with_gif": sum(1 for r in records
                            if r["has_gif_in_description"]),
        },
        "by_bet": by_bet,
        "by_platform": by_platform,
        "impact_releases": [r["id"] for r in impact_records],
        "releases": records,
    }


# ---------- Main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", required=True,
                    help='e.g. "2026-05", "Q1 2026", "2026-01..2026-04", '
                         '"last 30 days"')
    ap.add_argument("--output", type=Path,
                    help="path to write narrative.json (default: derived "
                         "from window slug)")
    ap.add_argument("--cache", type=Path,
                    help="cache file for the raw Linear pull (skip API "
                         "round-trip when present)")
    args = ap.parse_args()

    today = dt.date.today()
    window = parse_window(args.window, today)
    start, end, slug, label = window
    print(f"window: {label}  ({start} → {end})  slug={slug}")

    cache_path = args.cache or Path(f"outputs/releases-decks/{slug}/{slug}-raw.json")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.is_file():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        print(f"reusing cached raw pull ({age_h:.1f}h old): {cache_path}")
        issues = json.loads(cache_path.read_text())
    else:
        print("fetching all issues from Linear (paginated)…")
        issues = fetch_all_issues()
        cache_path.write_text(json.dumps(issues, indent=2))
        print(f"  pulled {len(issues)} issues → {cache_path}")

    narrative = build_narrative(window, issues)

    out = args.output or Path(f"outputs/releases-decks/{slug}/{slug}-narrative.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(narrative, indent=2))

    t = narrative["totals"]
    by_bet = {k: len(v) for k, v in narrative["by_bet"].items()}
    print(
        f"wrote {out}\n"
        f"  releases: {t['release_count']}  "
        f"impact: {t['impact_count']}  "
        f"with_images: {t['with_images']}  "
        f"with_gif: {t['with_gif']}\n"
        f"  by_bet: {by_bet}"
    )


if __name__ == "__main__":
    main()
