#!/usr/bin/env python3
"""
ClickUp Project/Folder -> Markdown exporter.

Usage:
    python clickup_prj_to_md.py <clickup_view_or_folder_url> [--token TOKEN]

Examples:
    python clickup_prj_to_md.py https://app.clickup.com/2408428/v/l/29fzc-96955?pr=2414052

Output is saved to: src/clickup/<folder_name>/

Environment:
    CLICKUP_TOKEN  -- Personal API token (if --token not provided)
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

# -- Load .env.local from project root -----------------------------------------

def _git_root() -> str:
    import subprocess
    return subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    ).stdout.strip()


def load_dotenv(root: str):
    env_path = os.path.join(root, ".env.local")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


PROJECT_ROOT = _git_root()
load_dotenv(PROJECT_ROOT)
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "clickup")
BASE = "https://api.clickup.com/api/v2"


# -- URL parsing ---------------------------------------------------------------

URL_PATTERN = re.compile(
    r"app\.clickup\.com/(\d+)/v/l/([\w-]+)"
)


def parse_url(url: str) -> tuple[str, str, Optional[str]]:
    """Extract (workspace_id, view_id, project_id) from URL."""
    m = URL_PATTERN.search(url)
    if not m:
        print(f"ERROR: Could not parse URL: {url}", file=sys.stderr)
        sys.exit(1)
    workspace_id = m.group(1)
    view_id = m.group(2)
    # Extract project filter from query params
    project_match = re.search(r'[?&]pr=(\d+)', url)
    project_id = project_match.group(1) if project_match else None
    return workspace_id, view_id, project_id


# -- API helpers ----------------------------------------------------------------

def api_get(url: str, token: str, retries: int = 3):
    req = urllib.request.Request(url, headers={
        "Authorization": token,
        "Content-Type": "application/json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(2 ** attempt, 10)
                time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            raise


def get_view(view_id: str, token: str) -> dict:
    return api_get(f"{BASE}/view/{view_id}", token).get("view", {})


def get_folder_lists(folder_id: str, token: str) -> list[dict]:
    return api_get(f"{BASE}/folder/{folder_id}/list", token).get("lists", [])


def get_list_tasks(list_id: str, token: str, include_closed: bool = True) -> list[dict]:
    """Fetch all tasks from a list, paginating as needed."""
    all_tasks = []
    page = 0
    while True:
        params = f"page={page}&include_closed={'true' if include_closed else 'false'}&subtasks=true"
        data = api_get(f"{BASE}/list/{list_id}/task?{params}", token)
        tasks = data.get("tasks", [])
        all_tasks.extend(tasks)
        if data.get("last_page", True) or not tasks:
            break
        page += 1
    return all_tasks


# -- Markdown formatting --------------------------------------------------------

def task_to_md(task: dict) -> str:
    """Convert a single task to markdown."""
    lines = []
    name = task.get("name", "Untitled")
    status = task.get("status", {}).get("status", "unknown")
    priority = task.get("priority")
    priority_name = priority.get("priority", "none") if priority else "none"
    assignees = ", ".join(a.get("username", a.get("email", "?")) for a in task.get("assignees", []))
    due = task.get("due_date")
    due_str = ""
    if due:
        try:
            due_str = datetime.fromtimestamp(int(due) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            due_str = str(due)

    url = task.get("url", "")
    task_id = task.get("id", "")
    tags = ", ".join(t.get("name", "") for t in task.get("tags", []))
    description = (task.get("description") or "").strip()

    lines.append(f"### {name}")
    lines.append(f"- **Status:** {status} | **Priority:** {priority_name}")
    if assignees:
        lines.append(f"- **Assignees:** {assignees}")
    if due_str:
        lines.append(f"- **Due:** {due_str}")
    if tags:
        lines.append(f"- **Tags:** {tags}")
    if url:
        lines.append(f"- **URL:** [{task_id}]({url})")
    if description:
        # Truncate very long descriptions
        if len(description) > 500:
            description = description[:500] + "..."
        lines.append(f"\n{description}")
    lines.append("")
    return "\n".join(lines)


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    name = re.sub(r'[^\w\s-]', '', name).strip()
    name = re.sub(r'[\s]+', '-', name)
    return name[:80]


# -- Main -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export ClickUp project/folder tasks to Markdown")
    parser.add_argument("url", help="ClickUp view URL")
    parser.add_argument("--token", default=os.environ.get("CLICKUP_TOKEN"), help="ClickUp API token")
    args = parser.parse_args()

    token = args.token
    if not token:
        print("ERROR: No CLICKUP_TOKEN found in environment or --token argument", file=sys.stderr)
        sys.exit(1)

    workspace_id, view_id, project_id = parse_url(args.url)

    # Get view info to find parent folder
    print(f"Fetching view {view_id}...")
    view = get_view(view_id, token)
    view_name = view.get("name", view_id)
    parent = view.get("parent", {})
    parent_id = parent.get("id")
    parent_type = parent.get("type")

    print(f"  View: {view_name}")

    # Determine output folder
    folder_name = sanitize_filename(view_name)
    out_dir = os.path.join(OUTPUT_BASE, folder_name)
    os.makedirs(out_dir, exist_ok=True)

    all_tasks_by_list = {}
    total_tasks = 0

    if parent_type == 5:  # folder
        print(f"  Parent folder: {parent_id}")
        lists = get_folder_lists(parent_id, token)
        print(f"  Found {len(lists)} lists")

        for lst in lists:
            list_id = lst["id"]
            list_name = lst.get("name", list_id)
            task_count = lst.get("task_count", 0)

            if task_count == 0:
                continue

            print(f"  Fetching {list_name} ({task_count} tasks)...")
            tasks = get_list_tasks(list_id, token)
            if tasks:
                all_tasks_by_list[list_name] = tasks
                total_tasks += len(tasks)
    else:
        # Fallback: try fetching tasks directly from the view
        print(f"  Fetching tasks from view...")
        data = api_get(f"{BASE}/view/{view_id}/task?page=0", token)
        tasks = data.get("tasks", [])
        if tasks:
            all_tasks_by_list[view_name] = tasks
            total_tasks = len(tasks)

    print(f"\nTotal: {total_tasks} tasks across {len(all_tasks_by_list)} lists")

    if total_tasks == 0:
        print("No tasks found.")
        return

    # Write per-list markdown files
    new_count = 0
    updated_count = 0
    for list_name, tasks in sorted(all_tasks_by_list.items()):
        filename = sanitize_filename(list_name) + ".md"
        filepath = os.path.join(out_dir, filename)

        lines = [f"# {list_name}\n"]
        lines.append(f"**Exported:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"**Tasks:** {len(tasks)}\n")

        # Group by status
        by_status = {}
        for t in tasks:
            s = t.get("status", {}).get("status", "unknown")
            by_status.setdefault(s, []).append(t)

        for status, status_tasks in sorted(by_status.items()):
            lines.append(f"\n## {status.title()} ({len(status_tasks)})\n")
            for t in status_tasks:
                lines.append(task_to_md(t))

        content = "\n".join(lines)
        existed = os.path.isfile(filepath)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        if existed:
            updated_count += 1
        else:
            new_count += 1

    # Write index
    index_path = os.path.join(out_dir, "index.md")
    index_lines = [f"# {view_name}\n"]
    index_lines.append(f"**Exported:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    index_lines.append(f"**Total tasks:** {total_tasks}\n")
    index_lines.append("| List | Tasks |")
    index_lines.append("|------|-------|")
    for list_name, tasks in sorted(all_tasks_by_list.items()):
        filename = sanitize_filename(list_name) + ".md"
        index_lines.append(f"| [{list_name}]({filename}) | {len(tasks)} |")

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(index_lines) + "\n")

    unchanged = 0
    print(f"\nDone! {new_count} new, {updated_count} updated, {unchanged} unchanged")
    print(f"Output: {os.path.relpath(out_dir, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
