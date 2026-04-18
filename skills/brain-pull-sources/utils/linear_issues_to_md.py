#!/usr/bin/env python3
from __future__ import annotations
"""
Linear Issues -> Markdown exporter with incremental sync.

Exports ALL issues for a Linear team, including triage and backlog issues
that are not assigned to any project. This complements `linear_to_md.py`
which only exports project-bound issues.

Usage:
    # Team issues (all states including triage)
    python linear_issues_to_md.py https://linear.app/<workspace>/team/<team>/...

    python linear_issues_to_md.py --force   # re-export everything
    python linear_issues_to_md.py --list

Output is saved to:
    src/linear/<workspace>/<team>-issues/all.md

Environment:
    LINEAR_TOKEN  -- Linear Personal API key
                     Get from: https://linear.app/settings/api
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional


# -- Project root (use git to find repo root) ----------------------------------

import subprocess as _sp
PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()


# -- Load .env from project root -----------------------------------------------

def load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env.local")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()


# -- Paths ---------------------------------------------------------------------
OUTPUT_BASE   = os.path.join(PROJECT_ROOT, "src", "linear")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".issues-registry.json")

LINEAR_API = "https://api.linear.app/graphql"

PRIORITY_LABELS = {0: "No priority", 1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}

# Ordering for state types when rendering
STATE_TYPE_ORDER = ["triage", "started", "unstarted", "backlog", "completed", "cancelled"]


# -- Registry ------------------------------------------------------------------

def load_registry() -> list[dict]:
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_registry(entries: list[dict]):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def upsert_registry(url: str, workspace: str, team_key: str, team_name: str,
                    output_path: str, stats: dict):
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()
    existing = next((e for e in entries if e.get("team_key") == team_key), None)

    if existing:
        existing.update({
            "url": url,
            "team_name": team_name,
            "output_path": output_path,
            "last_exported": now,
            "export_count": existing.get("export_count", 0) + 1,
            "stats": stats,
        })
    else:
        entries.append({
            "url": url,
            "workspace": workspace,
            "team_key": team_key,
            "team_name": team_name,
            "output_path": output_path,
            "first_exported": now,
            "last_exported": now,
            "export_count": 1,
            "stats": stats,
        })

    save_registry(entries)


def print_registry():
    entries = load_registry()
    if not entries:
        print("No Linear team issues exported yet.")
        return
    print(f"{'Team':<30} {'Issues':>8}  {'Exports':>7}  {'Last Exported':<20}  URL")
    print("-" * 110)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        n = e.get("stats", {}).get("total", 0)
        print(f"{e.get('team_name','')[:30]:<30} {n:>8}  {e.get('export_count',1):>7}  {last:<20}  {e['url']}")


# -- URL parsing ---------------------------------------------------------------

TEAM_URL_PATTERN = re.compile(r"https?://linear\.app/([^/]+)/team/([^/]+)")


def parse_linear_url(url: str) -> tuple[str, str]:
    """Return (workspace, team_key) from a Linear team URL."""
    m = TEAM_URL_PATTERN.search(url)
    if m:
        return m.group(1), m.group(2)
    print(f"ERROR: Could not parse Linear team URL: {url}", file=sys.stderr)
    print("Expected: https://linear.app/<workspace>/team/<team>/...", file=sys.stderr)
    sys.exit(1)


# -- GraphQL client ------------------------------------------------------------

def gql(query: str, variables: dict, token: str, retries: int = 5) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        LINEAR_API,
        data=body,
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                if "errors" in data:
                    raise RuntimeError(f"GraphQL errors: {data['errors']}")
                return data.get("data", {})
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                wait = 10 * (attempt + 1) if e.code == 429 else 3 * (attempt + 1)
                print(f"  HTTP {e.code}, retrying in {wait}s…", flush=True)
                time.sleep(wait)
            else:
                raise
        except (urllib.error.URLError, ConnectionResetError, OSError) as e:
            if attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"  Connection error ({e}), retrying in {wait}s…", flush=True)
                time.sleep(wait)
            else:
                raise


# -- Linear queries ------------------------------------------------------------

TEAM_QUERY = """
query GetTeam($key: String!) {
  teams(filter: { key: { eq: $key } }) {
    nodes { id name key }
  }
}
"""

TEAM_ISSUES_QUERY = """
query GetTeamIssues($teamId: String!, $after: String) {
  team(id: $teamId) {
    issues(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        identifier
        title
        description
        priority
        estimate
        dueDate
        createdAt
        updatedAt
        url
        triagedAt
        snoozedUntilAt
        state      { name type }
        assignee   { name }
        labels     { nodes { name } }
        parent     { identifier title }
        project    { name url }
        projectMilestone { id name }
        cycle      { name number }
      }
    }
  }
}
"""

def fetch_team(team_key: str, token: str) -> dict:
    data = gql(TEAM_QUERY, {"key": team_key}, token)
    nodes = data.get("teams", {}).get("nodes", [])
    if not nodes:
        print(f"ERROR: Team '{team_key}' not found.", file=sys.stderr)
        sys.exit(1)
    return nodes[0]


def fetch_all_team_issues(team_id: str, token: str) -> list[dict]:
    """Fetch every issue for a team, paginated."""
    issues = []
    cursor = None
    page_num = 0
    while True:
        page_num += 1
        data = gql(TEAM_ISSUES_QUERY, {"teamId": team_id, "after": cursor}, token)
        page = data.get("team", {}).get("issues", {})
        batch = page.get("nodes", [])
        issues.extend(batch)
        info = page.get("pageInfo", {})
        if batch:
            print(f"  Page {page_num}: fetched {len(batch)} issues (total: {len(issues)})", flush=True)
        if not info.get("hasNextPage"):
            break
        cursor = info["endCursor"]
    return issues


# -- Markdown rendering --------------------------------------------------------

def render_issue_row(issue: dict) -> str:
    """Render a single issue as a compact markdown block."""
    identifier = issue.get("identifier", "")
    title      = issue.get("title", "Untitled")
    assignee   = (issue.get("assignee") or {}).get("name", "—")
    priority   = PRIORITY_LABELS.get(issue.get("priority", 0), "—")
    labels     = ", ".join(l["name"] for l in issue.get("labels", {}).get("nodes", []))
    parent     = issue.get("parent")
    project    = issue.get("project")
    issue_url  = issue.get("url", "")
    cycle      = issue.get("cycle")

    lines = []
    lines.append(f"#### [{identifier}] {title}")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Assignee | {assignee} |")
    lines.append(f"| Priority | {priority} |")
    if labels:
        lines.append(f"| Labels | {labels} |")
    if project:
        lines.append(f"| Project | {project['name']} |")
    if cycle:
        lines.append(f"| Cycle | {cycle.get('name', '')} |")
    if parent:
        lines.append(f"| Parent | {parent['identifier']} – {parent['title']} |")
    if issue.get("dueDate"):
        lines.append(f"| Due | {issue['dueDate']} |")
    if issue.get("snoozedUntilAt"):
        lines.append(f"| Snoozed until | {issue['snoozedUntilAt'][:10]} |")
    lines.append(f"| URL | {issue_url} |")
    lines.append("")

    body = (issue.get("description") or "").strip()
    if body:
        lines.append(body)
        lines.append("")

    return "\n".join(lines)


def render_all_issues(team_name: str, team_key: str, issues: list[dict],
                      export_time: str) -> str:
    """Render all issues grouped by workflow state."""
    lines = []

    lines.append(f"# {team_name} ({team_key}) — All Issues")
    lines.append("")
    lines.append(f"*Exported: {export_time}*")
    lines.append("")

    # Summary table
    state_counts: dict[str, int] = {}
    for issue in issues:
        state_type = issue.get("state", {}).get("type", "other")
        state_counts[state_type] = state_counts.get(state_type, 0) + 1

    lines.append("## Summary")
    lines.append("")
    lines.append(f"**Total issues: {len(issues)}**")
    lines.append("")
    lines.append("| State | Count |")
    lines.append("|-------|------:|")
    for st in STATE_TYPE_ORDER:
        if st in state_counts:
            # Use the actual state name from the first issue in this type
            label = st.title()
            lines.append(f"| {label} | {state_counts[st]} |")
    # Any state types not in our ordering
    for st, count in state_counts.items():
        if st not in STATE_TYPE_ORDER:
            lines.append(f"| {st.title()} | {count} |")
    lines.append("")

    # Group issues by state type, then by state name within each type
    by_state_type: dict[str, list[dict]] = {}
    for issue in issues:
        state_type = issue.get("state", {}).get("type", "other")
        by_state_type.setdefault(state_type, []).append(issue)

    # Render each state group
    for state_type in STATE_TYPE_ORDER:
        group = by_state_type.get(state_type)
        if not group:
            continue

        # Sub-group by actual state name (e.g. "In Progress", "In Review" are both "started")
        by_state_name: dict[str, list[dict]] = {}
        for issue in group:
            state_name = issue.get("state", {}).get("name", state_type.title())
            by_state_name.setdefault(state_name, []).append(issue)

        for state_name, state_issues in by_state_name.items():
            lines.append(f"## {state_name} ({len(state_issues)})")
            lines.append("")

            # Sort by priority (1=urgent first), then identifier
            sorted_issues = sorted(
                state_issues,
                key=lambda i: (i.get("priority", 99) or 99, i.get("identifier", ""))
            )

            for issue in sorted_issues:
                lines.append(render_issue_row(issue))

    # Any leftover state types
    for state_type, group in by_state_type.items():
        if state_type in STATE_TYPE_ORDER:
            continue
        state_name = group[0].get("state", {}).get("name", state_type.title())
        lines.append(f"## {state_name} ({len(group)})")
        lines.append("")
        for issue in sorted(group, key=lambda i: (i.get("priority", 99) or 99, i.get("identifier", ""))):
            lines.append(render_issue_row(issue))

    return "\n".join(lines)


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export ALL Linear team issues (including triage) to Markdown."
    )
    parser.add_argument("url", nargs="?",
                        help="Linear team URL — e.g. https://linear.app/org/team/MOL/...")
    parser.add_argument("--token", default=os.environ.get("LINEAR_TOKEN", ""),
                        help="Linear API key (or set LINEAR_TOKEN env var)")
    parser.add_argument("--list", action="store_true",
                        help="List all previously exported teams and exit")
    parser.add_argument("--force", action="store_true",
                        help="Re-export even if recently exported")
    args = parser.parse_args()

    if args.list:
        print_registry()
        return

    if not args.url:
        parser.error("url is required (unless using --list)")

    token = args.token
    if not token:
        print("ERROR: No API key. Set LINEAR_TOKEN or use --token.", file=sys.stderr)
        print("Get your key from: https://linear.app/settings/api", file=sys.stderr)
        sys.exit(1)

    workspace, team_key = parse_linear_url(args.url)

    print(f"Fetching team '{team_key}'...")
    team      = fetch_team(team_key, token)
    team_name = team["name"]
    team_id   = team["id"]
    print(f"  Team: {team_name} ({team_key})")

    out_dir = os.path.join(OUTPUT_BASE, workspace, f"{team_key}-issues")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "all.md")
    rel_path = os.path.relpath(out_dir, PROJECT_ROOT)
    print(f"Output folder: {rel_path}")

    print("Fetching all team issues (including triage)...")
    issues = fetch_all_team_issues(team_id, token)
    print(f"  Total: {len(issues)} issues")

    now = datetime.now(timezone.utc)
    export_time = now.strftime("%Y-%m-%d %H:%M UTC")

    content = render_all_issues(team_name, team_key, issues, export_time)

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(content)

    # Build stats
    state_counts: dict[str, int] = {}
    for issue in issues:
        state_type = issue.get("state", {}).get("type", "other")
        state_counts[state_type] = state_counts.get(state_type, 0) + 1

    stats = {
        "total": len(issues),
        "by_state": state_counts,
    }

    upsert_registry(
        url=args.url,
        workspace=workspace,
        team_key=team_key,
        team_name=team_name,
        output_path=rel_path,
        stats=stats,
    )

    print(f"\nDone! {len(issues)} issues exported to {rel_path}/all.md")
    for st in STATE_TYPE_ORDER:
        if st in state_counts:
            print(f"  {st.title()}: {state_counts[st]}")


if __name__ == "__main__":
    main()
