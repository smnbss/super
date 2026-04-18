#!/usr/bin/env python3
from __future__ import annotations
"""
Linear -> Markdown exporter with incremental sync.

Exports all projects (and their issues) for a Linear team or entire workspace.

Usage:
    # Single team
    python linear_to_md.py https://linear.app/<workspace>/team/<team>/projects/all

    # All workspace projects
    python linear_to_md.py https://linear.app/<workspace>/projects/all

    python linear_to_md.py --force   # re-export everything
    python linear_to_md.py --list

Output is saved to:
    src/linear/<workspace>/<team>/   (team mode)
    src/linear/<workspace>/all/      (workspace mode)

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


# -- Project root (use git to find repo root, not relative path) --------------

import subprocess as _sp
PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()


# -- Load .env from project root ----------------------------------------------

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


# -- Paths --------------------------------------------------------------------
OUTPUT_BASE  = os.path.join(PROJECT_ROOT, "src", "linear")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")

LINEAR_API = "https://api.linear.app/graphql"

PRIORITY_LABELS = {0: "No priority", 1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}

INVALID_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')


# -- Registry -----------------------------------------------------------------

def load_registry() -> list[dict]:
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_registry(entries: list[dict]):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def get_existing_project_map(team_key: str) -> dict[str, dict]:
    """Return {project_id: entry} for a team from the registry."""
    for entry in load_registry():
        if entry.get("team_key") == team_key:
            return {p["project_id"]: p for p in entry.get("projects", [])}
    return {}


def upsert_registry(url: str, workspace: str, team_key: str, team_name: str,
                    output_path: str, projects: list[dict], stats: dict):
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()
    existing = next((e for e in entries if e.get("team_key") == team_key), None)

    project_manifest = [
        {
            "project_id":   p["id"],
            "name":         p["name"],
            "state":        p.get("state", ""),
            "updated_at":   p.get("updatedAt", ""),
            "file_path":    p.get("_file_path", ""),
            "last_exported": now if p.get("_exported") else
                             (existing or {}).get("projects", [{}])[0].get("last_exported", ""),
        }
        for p in projects
    ]

    if existing:
        existing.update({
            "url": url,
            "team_name": team_name,
            "output_path": output_path,
            "last_exported": now,
            "export_count": existing.get("export_count", 0) + 1,
            "projects": project_manifest,
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
            "projects": project_manifest,
            "stats": stats,
        })

    save_registry(entries)


def print_registry():
    entries = load_registry()
    if not entries:
        print("No Linear teams exported yet.")
        return
    print(f"{'Team':<30} {'Projects':>8}  {'Exports':>7}  {'Last Exported':<20}  URL")
    print("-" * 110)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        n = len(e.get("projects", []))
        print(f"{e.get('team_name','')[:30]:<30} {n:>8}  {e.get('export_count',1):>7}  {last:<20}  {e['url']}")


# -- URL parsing --------------------------------------------------------------

TEAM_URL_PATTERN      = re.compile(r"https?://linear\.app/([^/]+)/team/([^/]+)")
WORKSPACE_URL_PATTERN = re.compile(r"https?://linear\.app/([^/]+)/projects")


def parse_linear_url(url: str) -> tuple[str, Optional[str]]:
    """Return (workspace, team_key) from a Linear URL.
    team_key is None for workspace-level URLs."""
    m = TEAM_URL_PATTERN.search(url)
    if m:
        return m.group(1), m.group(2)
    m = WORKSPACE_URL_PATTERN.search(url)
    if m:
        return m.group(1), None
    print(f"ERROR: Could not parse Linear URL: {url}", file=sys.stderr)
    print("Expected: https://linear.app/<workspace>/team/<team>/projects/all", file=sys.stderr)
    print("      or: https://linear.app/<workspace>/projects/all", file=sys.stderr)
    sys.exit(1)


# -- GraphQL client -----------------------------------------------------------

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


# -- Linear queries -----------------------------------------------------------

TEAM_QUERY = """
query GetTeam($key: String!) {
  teams(filter: { key: { eq: $key } }) {
    nodes { id name key }
  }
}
"""

PROJECTS_QUERY = """
query GetProjects($teamId: String!, $after: String) {
  team(id: $teamId) {
    projects(first: 50, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        name
        description
        state
        startDate
        targetDate
        progress
        updatedAt
        url
      }
    }
  }
}
"""

ISSUES_QUERY = """
query GetIssues($projectId: String!, $after: String) {
  project(id: $projectId) {
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
        state    { name type }
        assignee { name }
        labels   { nodes { name } }
        parent            { identifier title }
        projectMilestone  { id name }
      }
    }
  }
}
"""

ALL_PROJECTS_QUERY = """
query GetAllProjects($after: String) {
  projects(first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      description
      state
      startDate
      targetDate
      progress
      updatedAt
      url
    }
  }
}
"""

MILESTONES_QUERY = """
query GetMilestones($projectId: String!) {
  project(id: $projectId) {
    projectMilestones {
      nodes {
        id
        name
        description
        targetDate
        sortOrder
      }
    }
  }
}
"""


def fetch_team(team_key: str, token: str) -> Optional[dict]:
    data = gql(TEAM_QUERY, {"key": team_key}, token)
    nodes = data.get("teams", {}).get("nodes", [])
    if not nodes:
        print(f"ERROR: Team '{team_key}' not found.", file=sys.stderr)
        sys.exit(1)
    return nodes[0]


def fetch_projects(team_id: str, token: str) -> list[dict]:
    projects = []
    cursor = None
    while True:
        data = gql(PROJECTS_QUERY, {"teamId": team_id, "after": cursor}, token)
        page = data.get("team", {}).get("projects", {})
        projects.extend(page.get("nodes", []))
        info = page.get("pageInfo", {})
        if not info.get("hasNextPage"):
            break
        cursor = info["endCursor"]
    return projects


def fetch_issues(project_id: str, token: str) -> list[dict]:
    issues = []
    cursor = None
    while True:
        data = gql(ISSUES_QUERY, {"projectId": project_id, "after": cursor}, token)
        page = data.get("project", {}).get("issues", {})
        issues.extend(page.get("nodes", []))
        info = page.get("pageInfo", {})
        if not info.get("hasNextPage"):
            break
        cursor = info["endCursor"]
    return issues


def fetch_all_projects(token: str) -> list[dict]:
    """Fetch all projects in the workspace, regardless of team."""
    projects = []
    cursor = None
    while True:
        data = gql(ALL_PROJECTS_QUERY, {"after": cursor}, token)
        page = data.get("projects", {})
        projects.extend(page.get("nodes", []))
        info = page.get("pageInfo", {})
        if not info.get("hasNextPage"):
            break
        cursor = info["endCursor"]
    return projects


def fetch_milestones(project_id: str, token: str) -> list[dict]:
    data = gql(MILESTONES_QUERY, {"projectId": project_id}, token)
    nodes = data.get("project", {}).get("projectMilestones", {}).get("nodes", [])
    return sorted(nodes, key=lambda m: m.get("sortOrder", 0))


# -- Markdown rendering -------------------------------------------------------

def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    return name[:150]


def render_issue(issue: dict) -> list[str]:
    lines = []
    identifier = issue.get("identifier", "")
    title      = issue.get("title", "Untitled")
    assignee   = (issue.get("assignee") or {}).get("name", "—")
    priority   = PRIORITY_LABELS.get(issue.get("priority", 0), "—")
    labels     = ", ".join(l["name"] for l in issue.get("labels", {}).get("nodes", []))
    parent     = issue.get("parent")
    issue_url  = issue.get("url", "")

    lines.append(f"#### [{identifier}] {title}")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Assignee | {assignee} |")
    lines.append(f"| Priority | {priority} |")
    if labels:
        lines.append(f"| Labels | {labels} |")
    if parent:
        lines.append(f"| Parent | {parent['identifier']} – {parent['title']} |")
    if issue.get("dueDate"):
        lines.append(f"| Due | {issue['dueDate']} |")
    lines.append(f"| URL | {issue_url} |")
    lines.append("")

    body = (issue.get("description") or "").strip()
    if body:
        lines.append(body)
        lines.append("")
    return lines


def render_project(project: dict, issues: list[dict], milestones: list[dict]) -> str:
    lines = []

    # Header
    lines.append(f"# {project['name']}")
    lines.append("")

    # Meta table
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Status | {project.get('state', '—')} |")
    progress = project.get("progress")
    if progress is not None:
        lines.append(f"| Progress | {int(progress * 100)}% |")
    if project.get("startDate"):
        lines.append(f"| Start date | {project['startDate']} |")
    if project.get("targetDate"):
        lines.append(f"| Target date | {project['targetDate']} |")
    lines.append(f"| Linear URL | {project.get('url', '—')} |")
    lines.append("")

    # Description
    desc = (project.get("description") or "").strip()
    if desc:
        lines.append("## Description")
        lines.append("")
        lines.append(desc)
        lines.append("")

    # Milestones
    if milestones:
        lines.append("## Milestones")
        lines.append("")
        lines.append("| Milestone | Target date |")
        lines.append("|-----------|-------------|")
        for m in milestones:
            target = m.get("targetDate") or "—"
            lines.append(f"| {m['name']} | {target} |")
        lines.append("")

    if not issues:
        lines.append("*No issues.*")
        return "\n".join(lines)

    # Build milestone lookup: id -> name
    milestone_by_id = {m["id"]: m["name"] for m in milestones}

    # Group issues by milestone first, then by state type within each milestone
    # Issues without a milestone go into a "No milestone" bucket
    milestone_order = [m["id"] for m in milestones] + [None]
    milestone_names = {m["id"]: m["name"] for m in milestones}
    milestone_names[None] = "No milestone"

    by_milestone: dict = {mid: [] for mid in milestone_order}
    for issue in issues:
        mid = (issue.get("projectMilestone") or {}).get("id")
        if mid not in by_milestone:
            mid = None
        by_milestone[mid].append(issue)

    STATE_ORDER = ["started", "unstarted", "backlog", "completed", "cancelled", "other"]

    lines.append("## Issues")
    lines.append("")

    for mid in milestone_order:
        milestone_issues = by_milestone.get(mid, [])
        if not milestone_issues:
            continue

        # Only add milestone grouping header if milestones exist
        if milestones:
            lines.append(f"### {milestone_names[mid]}")
            lines.append("")

        # Sub-group by state
        groups: dict[str, list[dict]] = {}
        for issue in milestone_issues:
            state_type = issue.get("state", {}).get("type", "other")
            groups.setdefault(state_type, []).append(issue)

        for group_key in STATE_ORDER:
            group_issues = groups.get(group_key)
            if not group_issues:
                continue

            state_name = group_issues[0].get("state", {}).get("name", group_key.title())
            heading_level = "####" if milestones else "###"
            lines.append(f"{heading_level} {state_name}")
            lines.append("")

            for issue in sorted(group_issues, key=lambda i: i.get("identifier", "")):
                lines.extend(render_issue(issue))

    return "\n".join(lines)


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export Linear projects to src/linear/<workspace>/<team|all>/ as Markdown."
    )
    parser.add_argument("url", nargs="?",
                        help="Linear URL — team: https://linear.app/org/team/HD/projects/all  "
                             "or workspace: https://linear.app/org/projects/all")
    parser.add_argument("--token", default=os.environ.get("LINEAR_TOKEN", ""),
                        help="Linear API key (or set LINEAR_TOKEN env var)")
    parser.add_argument("--list", action="store_true",
                        help="List all previously exported teams and exit")
    parser.add_argument("--force", action="store_true",
                        help="Re-export all projects even if unchanged")
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

    if team_key is not None:
        # Team-scoped export
        print(f"Fetching team '{team_key}'...")
        team      = fetch_team(team_key, token)
        team_name = team["name"]
        team_id   = team["id"]
        print(f"  Team: {team_name} ({team_key})")
        registry_key = team_key
        out_dir = os.path.join(OUTPUT_BASE, workspace, team_key)
    else:
        # Workspace-wide export
        print(f"Exporting all projects in workspace '{workspace}'...")
        team_name    = workspace
        team_id      = None
        registry_key = "all"
        out_dir = os.path.join(OUTPUT_BASE, workspace, "all")

    os.makedirs(out_dir, exist_ok=True)
    print(f"Output folder: {os.path.relpath(out_dir, PROJECT_ROOT)}")

    existing = get_existing_project_map(registry_key)
    if existing:
        print(f"  Found {len(existing)} projects in registry")

    print(f"Fetching projects...")
    if team_id is not None:
        projects = fetch_projects(team_id, token)
    else:
        projects = fetch_all_projects(token)
    print(f"  {len(projects)} projects found")

    stats = {"total": len(projects), "new": 0, "updated": 0, "unchanged": 0}

    for i, project in enumerate(projects, 1):
        pid        = project["id"]
        pname      = project["name"]
        updated_at = project.get("updatedAt", "")
        existing_p = existing.get(pid)

        safe_name  = sanitize(pname)
        file_path  = os.path.join(out_dir, f"{safe_name}.md")
        rel_path   = os.path.relpath(file_path, PROJECT_ROOT)
        project["_file_path"] = rel_path

        # Incremental: skip if file exists and updatedAt unchanged
        if (not args.force
                and existing_p
                and existing_p.get("updated_at") == updated_at
                and os.path.isfile(file_path)):
            project["_exported"] = False
            stats["unchanged"] += 1
            print(f"  [{i}/{len(projects)}] ✓ {pname} (unchanged)")
            continue

        print(f"  [{i}/{len(projects)}] Fetching issues + milestones for: {pname}...", flush=True)
        issues     = fetch_issues(pid, token)
        milestones = fetch_milestones(pid, token)
        if milestones:
            print(f"    {len(milestones)} milestones, {len(issues)} issues")

        content = render_project(project, issues, milestones)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        project["_exported"] = True
        if existing_p:
            stats["updated"] += 1
        else:
            stats["new"] += 1

    upsert_registry(
        url=args.url,
        workspace=workspace,
        team_key=registry_key,
        team_name=team_name,
        output_path=os.path.relpath(out_dir, PROJECT_ROOT),
        projects=projects,
        stats=stats,
    )

    print(f"\nDone! {stats['new']} new, {stats['updated']} updated, {stats['unchanged']} unchanged")
    print(f"Output: {os.path.relpath(out_dir, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
