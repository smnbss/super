"""
Shared link rewriting utility for exported markdown files.

Rewrites links pointing to Confluence, ClickUp, Google Drive, and GitHub
to relative local file paths using the registry files.
"""

from __future__ import annotations

import json
import os
import re


import subprocess as _sp
PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()

REGISTRY_PATHS = {
    "confluence": os.path.join(PROJECT_ROOT, "src", "confluence", ".registry.json"),
    "clickup": os.path.join(PROJECT_ROOT, "src", "clickup", ".registry.json"),
    "gdrive": os.path.join(PROJECT_ROOT, "src", "gdrive", ".registry.json"),
    "github": os.path.join(PROJECT_ROOT, "src", "github", ".registry.json"),
}

# Patterns to extract identifiers from URLs
# Confluence: /wiki/spaces/<space>/pages/<page_id>/Title or full URL
CONFLUENCE_RELATIVE_RE = re.compile(
    r"/wiki/spaces/[^/]+/pages/(\d+)(?:/[^)\"]*)?")
CONFLUENCE_ABSOLUTE_RE = re.compile(
    r"https?://[^/]+/wiki/spaces/[^/]+/pages/(\d+)(?:/[^)\"]*)?")

# ClickUp docs: https://app.clickup.com/<ws>/v/dc/<doc_id>/<page_id>
CLICKUP_DOC_RE = re.compile(
    r"https?://app\.clickup\.com/\d+/v/dc/([\w-]+)/([\w-]+)")
CLICKUP_DOC_ONLY_RE = re.compile(
    r"https?://app\.clickup\.com/\d+/v/dc/([\w-]+)/?$")

# Google Drive folders
GDRIVE_FOLDER_RE = re.compile(
    r"https?://drive\.google\.com/drive(?:/u/\d+)?/folders/([\w-]+)")

# Google Docs/Sheets/Slides: https://docs.google.com/.../d/<file_id>/...
GDOCS_RE = re.compile(
    r"https?://docs\.google\.com/(?:document|spreadsheets|presentation)/d/([\w-]+)")

# GitHub blob links: https://github.com/<owner>/<repo>/blob/<branch>/<path>
GITHUB_BLOB_RE = re.compile(
    r"https?://github\.com/([^/]+/[^/]+)/blob/[^/]+/(.*)")

# Markdown link pattern: [text](url)
MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')


def _load_json(path: str) -> list[dict]:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def build_link_map() -> dict[str, str]:
    """
    Load all 4 registry files and build a unified identifier -> file_path map.

    Keys are platform-specific identifiers, values are file paths relative to PROJECT_ROOT.
    """
    link_map: dict[str, str] = {}

    # Confluence: page_id -> file_path
    for entry in _load_json(REGISTRY_PATHS["confluence"]):
        for page in entry.get("pages", []):
            page_id = page.get("page_id")
            file_path = page.get("file_path")
            if page_id and file_path:
                link_map[f"confluence:{page_id}"] = file_path

    # ClickUp: page_id -> file_path
    for entry in _load_json(REGISTRY_PATHS["clickup"]):
        for page in entry.get("pages", []):
            page_id = page.get("page_id")
            file_path = page.get("file_path")
            if page_id and file_path:
                link_map[f"clickup:{page_id}"] = file_path

    # Google Drive: file_id -> file_path
    for entry in _load_json(REGISTRY_PATHS["gdrive"]):
        folder_id = entry.get("folder_id")
        output_path = entry.get("output_path", "")
        if folder_id and output_path:
            link_map[f"gdrive:{folder_id}"] = output_path
        for f in entry.get("files", []):
            file_id = f.get("file_id")
            file_path = f.get("file_path")
            if file_id and file_path:
                # Normalize: file_path may be absolute or relative
                if os.path.isabs(file_path):
                    file_path = os.path.relpath(file_path, PROJECT_ROOT)
                link_map[f"gdrive:{file_id}"] = file_path

    # GitHub: html_url -> file_path (also owner/repo + path)
    for entry in _load_json(REGISTRY_PATHS["github"]):
        output_path = entry.get("output_path", "")
        if os.path.isabs(output_path):
            output_path = os.path.relpath(output_path, PROJECT_ROOT)
        for f in entry.get("files", []):
            html_url = f.get("html_url", "")
            file_path_in_repo = f.get("path", "")
            if html_url and file_path_in_repo and output_path:
                full_path = os.path.join(output_path, file_path_in_repo)
                link_map[f"github:{html_url}"] = full_path

    return link_map


def _try_resolve(url: str, link_map: dict[str, str]) -> str | None:
    """Try to resolve a URL to a local file path key in link_map. Returns the file_path or None."""

    # Confluence absolute URL
    m = CONFLUENCE_ABSOLUTE_RE.match(url)
    if m:
        return link_map.get(f"confluence:{m.group(1)}")

    # Confluence relative URL
    m = CONFLUENCE_RELATIVE_RE.match(url)
    if m:
        return link_map.get(f"confluence:{m.group(1)}")

    # ClickUp doc + page
    m = CLICKUP_DOC_RE.match(url)
    if m:
        return link_map.get(f"clickup:{m.group(2)}")

    # ClickUp doc only (no page_id)
    m = CLICKUP_DOC_ONLY_RE.match(url)
    if m:
        return link_map.get(f"clickup:{m.group(1)}")

    # Google Drive folder
    m = GDRIVE_FOLDER_RE.match(url)
    if m:
        return link_map.get(f"gdrive:{m.group(1)}")

    # Google Docs/Sheets/Slides
    m = GDOCS_RE.match(url)
    if m:
        return link_map.get(f"gdrive:{m.group(1)}")

    # GitHub blob URL
    m = GITHUB_BLOB_RE.match(url)
    if m:
        return link_map.get(f"github:{url}")

    return None


def _is_confluence_relative(url: str) -> bool:
    """Check if URL is a relative Confluence link (starts with /wiki/)."""
    return url.startswith("/wiki/")


def rewrite_links(content: str, current_file_path: str, link_map: dict[str, str]) -> str:
    """
    Rewrite markdown links in content to point to local files.

    Args:
        content: Markdown content with links to rewrite.
        current_file_path: Path of the current file relative to PROJECT_ROOT
                          (e.g. "src/confluence/Monkeys Wiki/Page.md").
        link_map: Unified identifier -> file_path map from build_link_map().

    Returns:
        Content with rewritten links.
    """
    current_dir = os.path.dirname(current_file_path)

    def _replace_link(match: re.Match) -> str:
        text = match.group(1)
        url = match.group(2)

        # Try to resolve URL to a local path
        target_path = _try_resolve(url, link_map)

        if target_path:
            # Compute relative path from current file to target
            rel = os.path.relpath(target_path, current_dir)
            return f"[{text}]({rel})"

        # For unresolved Confluence relative URLs, prepend base URL from env
        if _is_confluence_relative(url):
            base = os.getenv("CONFLUENCE_BASE_URL", "https://<your-org>.atlassian.net").rstrip("/")
            return f"[{text}]({base}{url})"

        # Keep original URL as-is
        return match.group(0)

    return MD_LINK_RE.sub(_replace_link, content)
