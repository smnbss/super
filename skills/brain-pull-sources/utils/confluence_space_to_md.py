#!/usr/bin/env python3
from __future__ import annotations
"""
Confluence Space -> Markdown exporter with incremental sync.

Usage:
    python confluence_space_to_md.py <confluence_space_url> [--token TOKEN] [--email EMAIL]

Examples:
    # Export a space by URL
    python confluence_space_to_md.py https://<your-org>.atlassian.net/wiki/spaces/ABC123/overview

    # With explicit credentials
    python confluence_space_to_md.py https://<your-org>.atlassian.net/wiki/spaces/ABC123/overview \
        --token xxx --email user@example.com

    # Force re-export all pages
    python confluence_space_to_md.py https://<your-org>.atlassian.net/wiki/spaces/ABC123/overview --force

Output is saved to:  src/confluence/<space name>/

Environment:
    CONFLUENCE_TOKEN  -- API token (if --token not provided)
    CONFLUENCE_EMAIL  -- User email (if --email not provided)
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser

from rewrite_links import build_link_map, rewrite_links


# -- Project root (use git to find repo root, not relative path) --------------

import subprocess as _sp
PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()


# -- Load .env from project root ----------------------------------------------

def load_dotenv():
    """Load key=value pairs from .env.local file in the project root."""
    env_path = os.path.join(PROJECT_ROOT, ".env.local")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "confluence")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")


# -- Registry -----------------------------------------------------------------

def load_registry() -> list[dict]:
    """Load the export registry from disk."""
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_registry(entries: list[dict]):
    """Persist the export registry to disk."""
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def get_existing_page_map(space_key: str) -> dict[str, dict]:
    """Get a map of page_id -> page info from existing registry."""
    entries = load_registry()
    for entry in entries:
        if entry["space_key"] == space_key:
            return {p["page_id"]: p for p in entry.get("pages", [])}
    return {}


def upsert_registry(url: str, base_url: str, space_key: str, space_name: str,
                    output_path: str, page_count: int, pages: list[dict],
                    space_id: str | None = None, stats: dict = None):
    """Add or update a registry entry for the given space, including all page nodes."""
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()

    # Build the pages manifest with version info
    pages_manifest = []
    for p in pages:
        pages_manifest.append({
            "page_id": p["id"],
            "title": p.get("title", "Untitled"),
            "parent_id": p.get("parent_id"),
            "file_path": p.get("_file_path", ""),
            "version": p.get("version", 1),
            "last_exported": now if p.get("_exported") else p.get("_last_exported"),
        })

    # Find existing entry by space_key or space_id
    existing = next((e for e in entries if e["space_key"] == space_key or 
                     (space_id and e.get("space_id") == space_id)), None)
    if existing:
        existing["url"] = url
        existing["space_name"] = space_name
        existing["output_path"] = output_path
        existing["page_count"] = page_count
        existing["last_exported"] = now
        existing["export_count"] = existing.get("export_count", 0) + 1
        existing["pages"] = pages_manifest
        if space_id:
            existing["space_id"] = space_id
        if stats:
            existing["stats"] = stats
    else:
        entry = {
            "url": url,
            "base_url": base_url,
            "space_key": space_key,
            "space_name": space_name,
            "output_path": output_path,
            "page_count": page_count,
            "first_exported": now,
            "last_exported": now,
            "export_count": 1,
            "pages": pages_manifest,
            "stats": stats,
        }
        if space_id:
            entry["space_id"] = space_id
        entries.append(entry)

    save_registry(entries)


def print_registry(verbose: bool = False):
    """Print a formatted table of all previously exported spaces."""
    entries = load_registry()
    if not entries:
        print("No spaces exported yet.")
        return

    print(f"{'Space Name':<50} {'Pages':>5}  {'Exports':>7}  {'Last Exported':<20}  URL")
    print("-" * 130)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        stats = e.get("stats", {})
        page_info = f"{stats.get('updated', 0)}/{stats.get('total', e['page_count'])} updated" if stats else str(e['page_count'])
        print(f"{e['space_name'][:50]:<50} {page_info:>12}  {e.get('export_count', 1):>7}  {last:<20}  {e['url']}")
        if verbose:
            for p in e.get("pages", []):
                indent = "  ├── " if p.get("parent_id") else "  "
                version_info = f" v{p['version']}" if p.get("version") else ""
                print(f"{indent}{p['title'][:60]:<64} {p.get('file_path', '')}{version_info}")


# -- URL parsing --------------------------------------------------------------

URL_PATTERN = re.compile(
    r"https?://([^/]+)/wiki/spaces/([^/]+)(?:/|$)"
)


def parse_confluence_url(url: str) -> tuple[str, str]:
    """Extract (base_url, space_key) from a Confluence space URL."""
    m = URL_PATTERN.search(url)
    if not m:
        print(f"ERROR: Could not parse Confluence URL: {url}", file=sys.stderr)
        print("Expected format: https://<domain>/wiki/spaces/<space_key>/...", file=sys.stderr)
        sys.exit(1)
    base_url = f"https://{m.group(1)}"
    return base_url, m.group(2)


# -- API helpers --------------------------------------------------------------

def api_get(url: str, email: str, token: str):
    """Make authenticated GET request to Confluence API."""
    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {credentials}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_get_with_params(base_url: str, path: str, params: dict, email: str, token: str):
    """Make authenticated GET request with query parameters."""
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{base_url}{path}?{query}"
    return api_get(url, email, token)


# -- Confluence endpoints -----------------------------------------------------

def get_space_info(base_url: str, space_key_or_id: str, email: str, token: str) -> dict:
    """Fetch space metadata (name, etc.).
    
    Tries by key first, then by ID if that fails.
    """
    # Try by key first
    try:
        url = f"{base_url}/wiki/rest/api/space/{space_key_or_id}"
        return api_get(url, email, token)
    except urllib.error.HTTPError as e:
        if e.code == 404 or e.code == 403:
            # Try looking up by ID using the spaces list endpoint
            try:
                url = f"{base_url}/wiki/rest/api/space?spaceKey={space_key_or_id}"
                resp = api_get(url, email, token)
                if resp.get("results"):
                    return resp["results"][0]
            except:
                pass
            # Try using space ID directly with v2 API
            try:
                url = f"{base_url}/wiki/api/v2/spaces/{space_key_or_id}"
                resp = api_get(url, email, token)
                # Convert v2 format to v1-like format
                return {
                    "key": resp.get("key", space_key_or_id),
                    "name": resp.get("name", space_key_or_id),
                    "id": resp.get("id", space_key_or_id),
                    "_v2_format": True,
                }
            except:
                pass
        raise


def get_page_info(base_url: str, page_id: str, email: str, token: str) -> dict | None:
    """Fetch a single page's metadata."""
    try:
        url = f"{base_url}/wiki/api/v2/pages/{page_id}"
        resp = api_get(url, email, token)
        return {
            "id": str(resp["id"]),
            "title": resp.get("title", "Untitled"),
            "type": "page",
            "status": "current",
            "parent_id": str(resp["parentId"]) if resp.get("parentId") else None,
            "version": resp.get("version", {}).get("number", 1),
        }
    except Exception:
        return None


def list_all_pages(base_url: str, space_key: str, space_id: str | None, email: str, token: str) -> list[dict]:
    """Return list of all pages in the space with their metadata.
    
    Also fetches any parent pages that are referenced but not in the initial list
    to ensure proper hierarchy reconstruction.
    """
    pages = []
    start = 0
    limit = 100
    
    while True:
        # Try spaceKey first, fall back to space ID via v2 API
        try:
            url = f"{base_url}/wiki/rest/api/content?spaceKey={space_key}&start={start}&limit={limit}&expand=ancestors,version"
            resp = api_get(url, email, token)
        except urllib.error.HTTPError as e:
            if (e.code == 403 or e.code == 404) and space_id:
                # Try v2 API with space ID
                url = f"{base_url}/wiki/api/v2/spaces/{space_id}/pages?start={start}&limit={limit}"
                resp = api_get(url, email, token)
                # Convert v2 format to v1-like format
                v2_pages = resp.get("results", [])
                for p in v2_pages:
                    pages.append({
                        "id": str(p["id"]),
                        "title": p.get("title", "Untitled"),
                        "type": "page",
                        "status": "current",
                        "parent_id": str(p["parentId"]) if p.get("parentId") else None,
                        "version": p.get("version", {}).get("number", 1),
                    })
                # Check if there are more pages
                if len(v2_pages) < limit:
                    break
                start += limit
                continue
            else:
                raise
        
        results = resp.get("results", [])
        if not results:
            break
            
        for page in results:
            # Extract parent from ancestors
            ancestors = page.get("ancestors", [])
            parent_id = ancestors[-1]["id"] if ancestors else None
            
            pages.append({
                "id": page["id"],
                "title": page.get("title", "Untitled"),
                "type": page.get("type", "page"),
                "status": page.get("status", "current"),
                "parent_id": parent_id,
                "version": page.get("version", {}).get("number", 1),
            })
        
        # Check if there are more pages
        size = resp.get("size", 0)
        if len(results) < limit or start + len(results) >= resp.get("totalSize", 0):
            break
        start += limit
    
    # Now fetch any missing parent pages to build proper hierarchy
    page_ids = {p["id"] for p in pages}
    parent_ids = {p.get("parent_id") for p in pages if p.get("parent_id")}
    missing_parents = parent_ids - page_ids
    
    # Fetch missing parents recursively
    fetched_parents = set()
    while missing_parents:
        to_fetch = missing_parents - fetched_parents
        if not to_fetch:
            break
            
        for parent_id in list(to_fetch)[:10]:  # Batch fetch to avoid overwhelming API
            if parent_page := get_page_info(base_url, parent_id, email, token):
                pages.append(parent_page)
                fetched_parents.add(parent_id)
                # Check if this parent has its own parent
                if parent_page.get("parent_id") and parent_page["parent_id"] not in page_ids:
                    missing_parents.add(parent_page["parent_id"])
            else:
                fetched_parents.add(parent_id)  # Mark as fetched even if failed
        
        # Update missing parents list
        page_ids = {p["id"] for p in pages}
        missing_parents = {p for p in missing_parents if p not in page_ids}
    
    return pages


def get_page_content(base_url: str, page_id: str, email: str, token: str) -> str:
    """Fetch page content in storage format and convert to markdown."""
    # Try to get content in view format (HTML) which is easier to convert
    url = f"{base_url}/wiki/rest/api/content/{page_id}?expand=body.view,body.storage"
    resp = api_get(url, email, token)
    
    body = resp.get("body", {})
    
    # Prefer view format (rendered HTML) if available
    if "view" in body and body["view"].get("value"):
        html_content = body["view"]["value"]
        return html_to_markdown(html_content, resp.get("title", "Untitled"))
    
    # Fall back to storage format (XML-like)
    if "storage" in body and body["storage"].get("value"):
        storage_content = body["storage"]["value"]
        return storage_to_markdown(storage_content, resp.get("title", "Untitled"))
    
    return ""


# -- HTML to Markdown converter -----------------------------------------------

class HTMLToMarkdownParser(HTMLParser):
    """Simple HTML to Markdown converter."""
    
    def __init__(self):
        super().__init__()
        self.result = []
        self.in_code = False
        self.in_pre = False
        self.in_link = False
        self.link_url = ""
        self.list_stack = []
        self.header_level = 0
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            self.header_level = int(tag[1])
            self.result.append("\n" + "#" * self.header_level + " ")
        elif tag == "p":
            if self.result and not self.result[-1].endswith("\n"):
                self.result.append("\n\n")
            else:
                self.result.append("\n")
        elif tag == "br":
            self.result.append("\n")
        elif tag == "strong" or tag == "b":
            self.result.append("**")
        elif tag == "em" or tag == "i":
            self.result.append("*")
        elif tag == "code":
            if not self.in_pre:
                self.result.append("`")
            self.in_code = True
        elif tag == "pre":
            self.in_pre = True
            self.result.append("\n```\n")
        elif tag == "a":
            self.in_link = True
            self.link_url = attrs_dict.get("href", "")
            self.result.append("[")
        elif tag == "ul":
            self.list_stack.append("ul")
        elif tag == "ol":
            self.list_stack.append("ol")
        elif tag == "li":
            indent = "  " * (len(self.list_stack) - 1)
            marker = "- " if self.list_stack[-1] == "ul" else "1. "
            self.result.append(f"\n{indent}{marker}")
        elif tag == "img":
            alt = attrs_dict.get("alt", "")
            src = attrs_dict.get("src", "")
            self.result.append(f"![{alt}]({src})")
        elif tag == "hr":
            self.result.append("\n---\n")
        elif tag == "blockquote":
            self.result.append("\n> ")
            
    def handle_endtag(self, tag):
        if tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            self.result.append("\n")
            self.header_level = 0
        elif tag == "p":
            self.result.append("\n\n")
        elif tag == "strong" or tag == "b":
            self.result.append("**")
        elif tag == "em" or tag == "i":
            self.result.append("*")
        elif tag == "code":
            if not self.in_pre:
                self.result.append("`")
            self.in_code = False
        elif tag == "pre":
            self.in_pre = False
            self.result.append("\n```\n")
        elif tag == "a":
            if self.in_link:
                self.result.append(f"]({self.link_url})")
                self.in_link = False
        elif tag in ["ul", "ol"]:
            if self.list_stack:
                self.list_stack.pop()
            self.result.append("\n")
        elif tag == "blockquote":
            self.result.append("\n")
            
    def handle_data(self, data):
        if data.strip() or self.in_pre:
            # Escape markdown characters in text unless in code
            if not self.in_code and not self.in_pre:
                data = data.replace("*", "\\*").replace("_", "\\_")
            self.result.append(data)
    
    def get_markdown(self) -> str:
        return "".join(self.result)


def html_to_markdown(html: str, title: str) -> str:
    """Convert HTML content to Markdown."""
    parser = HTMLToMarkdownParser()
    try:
        parser.feed(html)
        md = parser.get_markdown()
        # Clean up excessive newlines
        md = re.sub(r'\n{3,}', '\n\n', md)
        return md.strip()
    except Exception as e:
        # If parsing fails, return stripped HTML as fallback
        return re.sub(r'<[^>]+>', '', html)


def storage_to_markdown(storage: str, title: str) -> str:
    """Convert Confluence storage format (XML) to Markdown."""
    # Basic conversion for common Confluence tags
    md = storage
    
    # Headers
    md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n', md, flags=re.DOTALL)
    md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n', md, flags=re.DOTALL)
    md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n', md, flags=re.DOTALL)
    md = re.sub(r'<h4[^>]*>(.*?)</h4>', r'#### \1\n', md, flags=re.DOTALL)
    md = re.sub(r'<h5[^>]*>(.*?)</h5>', r'##### \1\n', md, flags=re.DOTALL)
    md = re.sub(r'<h6[^>]*>(.*?)</h6>', r'###### \1\n', md, flags=re.DOTALL)
    
    # Formatting
    md = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', md, flags=re.DOTALL)
    md = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', md, flags=re.DOTALL)
    md = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', md, flags=re.DOTALL)
    md = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', md, flags=re.DOTALL)
    md = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', md, flags=re.DOTALL)
    md = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n', md, flags=re.DOTALL)
    
    # Links
    md = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', md, flags=re.DOTALL)
    
    # Lists
    md = re.sub(r'<ul[^>]*>(.*?)</ul>', r'\n\1\n', md, flags=re.DOTALL)
    md = re.sub(r'<ol[^>]*>(.*?)</ol>', r'\n\1\n', md, flags=re.DOTALL)
    md = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', md, flags=re.DOTALL)
    
    # Paragraphs and breaks
    md = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\1\n', md, flags=re.DOTALL)
    md = re.sub(r'<br\s*/?>', r'\n', md)
    
    # Tables (basic)
    md = re.sub(r'<table[^>]*>(.*?)</table>', r'\n[Table]\n', md, flags=re.DOTALL)
    
    # Remove remaining tags
    md = re.sub(r'<[^>]+>', '', md)
    
    # Clean up
    md = re.sub(r'\n{3,}', '\n\n', md)
    
    return md.strip()


# -- Tree building ------------------------------------------------------------

def build_tree(pages: list[dict]) -> tuple[list[dict], dict]:
    """
    Build a parent->children mapping from the flat page list.
    Returns (root_nodes, children_map) where children_map[parent_id] = [child, ...]
    """
    by_id = {p["id"]: p for p in pages}
    children: dict[str, list[dict]] = {}
    roots: list[dict] = []

    for p in pages:
        pid = p.get("parent_id")
        if pid and pid in by_id:
            children.setdefault(pid, []).append(p)
        else:
            roots.append(p)

    # Sort roots and children by title for consistency
    roots.sort(key=lambda p: p.get("title", "").lower())
    for k in children:
        children[k].sort(key=lambda p: p.get("title", "").lower())

    return roots, children


# -- File writing -------------------------------------------------------------

INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    # Collapse repeated dashes
    name = re.sub(r"-{2,}", "-", name)
    return name[:200]  # filesystem limit safety


def assign_paths(node: dict, children_map: dict, parent_dir: str,
                 existing_pages: dict[str, dict], force: bool = False):
    """
    Pass 1: Recursively assign _file_path to each node without writing files.
    Also sets _needs_update to indicate whether the file needs to be written.
    """
    title = node.get("title", "Untitled")
    if not title.strip():
        return
    safe_title = sanitize_filename(title)
    node_id = node["id"]
    kids = children_map.get(node_id, [])
    version = node.get("version", 1)

    existing = existing_pages.get(node_id)
    needs_update = force or not existing or existing.get("version") != version

    if kids:
        node_dir = os.path.join(parent_dir, safe_title)
        fpath = os.path.join(node_dir, f"{safe_title}.md")
    else:
        fpath = os.path.join(parent_dir, f"{safe_title}.md")
        node_dir = parent_dir

    if needs_update:
        node["_file_path"] = os.path.relpath(fpath, PROJECT_ROOT)
        node["_needs_update"] = True
    elif existing and existing.get("file_path"):
        node["_file_path"] = existing["file_path"]
        node["_last_exported"] = existing.get("last_exported")
        node["_needs_update"] = False
    else:
        node["_file_path"] = os.path.relpath(fpath, PROJECT_ROOT)
        node["_needs_update"] = True

    for child in kids:
        child_parent = os.path.join(parent_dir, safe_title) if kids else parent_dir
        assign_paths(child, children_map, child_parent, existing_pages, force)


def write_tree(node: dict, children_map: dict, content_map: dict,
               parent_dir: str, link_map: dict[str, str]) -> tuple[int, bool]:
    """
    Pass 2: Recursively write pages that need updating, with link rewriting.
    Returns (count, was_updated).
    """
    title = node.get("title", "Untitled")
    if not title.strip():
        return 0, False
    safe_title = sanitize_filename(title)
    node_id = node["id"]
    kids = children_map.get(node_id, [])
    needs_update = node.get("_needs_update", False)
    file_path = node.get("_file_path", "")

    count = 0
    was_updated = False

    if needs_update and file_path:
        content = content_map.get(node_id, "")
        content = rewrite_links(content, file_path, link_map)

        fpath = os.path.join(PROJECT_ROOT, file_path)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n{content}\n")
        node["_exported"] = True
        count += 1
        was_updated = True

    child_dir = os.path.join(parent_dir, safe_title) if kids else parent_dir
    for child in kids:
        cc, _ = write_tree(child, children_map, content_map, child_dir, link_map)
        count += cc

    return count, was_updated


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export a Confluence space to src/confluence/<space name>/ as Markdown files."
    )
    parser.add_argument("url", nargs="?", help="Confluence space URL (e.g. https://<your-org>.atlassian.net/wiki/spaces/ABC123/overview)")
    parser.add_argument("--token", default=os.environ.get("CONFLUENCE_TOKEN", ""),
                        help="Confluence API token (or set CONFLUENCE_TOKEN env var)")
    parser.add_argument("--email", default=os.environ.get("CONFLUENCE_EMAIL", ""),
                        help="Confluence user email (or set CONFLUENCE_EMAIL env var)")
    parser.add_argument("--flat", action="store_true",
                        help="Write all files flat in output_dir (no subdirectories)")
    parser.add_argument("--list", action="store_true",
                        help="List all previously exported spaces and exit")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="With --list, show all individual pages per space")
    parser.add_argument("--skip-content", action="store_true",
                        help="Skip fetching content (only create structure with titles)")
    parser.add_argument("--force", action="store_true",
                        help="Force re-export all pages even if unchanged")
    args = parser.parse_args()

    if args.list:
        print_registry(verbose=args.verbose)
        return

    if not args.url:
        parser.error("url is required (unless using --list)")

    token = args.token
    email = args.email
    if not token or not email:
        print("ERROR: Both token and email are required. Set CONFLUENCE_TOKEN/CONFLUENCE_EMAIL or use --token/--email.", file=sys.stderr)
        sys.exit(1)

    # Parse URL -> base_url + space_key (which might be a space ID)
    base_url, space_key_or_id = parse_confluence_url(args.url)
    
    # Check if it looks like a space ID (long alphanumeric)
    is_space_id = len(space_key_or_id) > 20 and '-' in space_key_or_id
    space_id = space_key_or_id if is_space_id else None

    # Load existing registry for comparison
    existing_pages = get_existing_page_map(space_key_or_id)
    
    # Fetch space info from API
    print(f"Fetching space info for {space_key_or_id}...")
    space_key = space_key_or_id  # Default to using the ID as key if lookup fails
    try:
        space_info = get_space_info(base_url, space_key_or_id, email, token)
        space_name = space_info.get("name", space_key_or_id)
        # Get the actual space key for API calls
        space_key = space_info.get("key", space_key_or_id)
        # Get space ID if available
        if "id" in space_info:
            space_id = space_info["id"]
    except urllib.error.HTTPError as e:
        print(f"  Could not fetch space info: {e}", file=sys.stderr)
        print("  Using space identifier as folder name.")
        space_name = space_key_or_id

    safe_space_name = sanitize_filename(space_name)
    out = os.path.join(OUTPUT_BASE, safe_space_name)
    os.makedirs(out, exist_ok=True)
    print(f"Output folder: {os.path.relpath(out, PROJECT_ROOT)}")

    if existing_pages and not args.force:
        print(f"  Found {len(existing_pages)} pages in registry (comparing for changes)...")
    elif args.force:
        print("  Force mode: re-exporting all pages")

    # Step 1: List all pages
    print(f"Listing pages in space \"{space_name}\"...")
    try:
        pages = list_all_pages(base_url, space_key, space_id, email, token)
        print(f"  Found {len(pages)} pages.")
    except urllib.error.HTTPError as e:
        print(f"ERROR: Could not fetch pages: {e}", file=sys.stderr)
        sys.exit(1)

    if not pages:
        print("No pages found. Exiting.")
        return

    # Count changes
    new_count = 0
    updated_count = 0
    unchanged_count = 0
    for p in pages:
        existing = existing_pages.get(p["id"])
        if not existing:
            new_count += 1
        elif existing.get("version") != p.get("version"):
            updated_count += 1
        else:
            unchanged_count += 1
    
    if not args.force:
        print(f"  New: {new_count}, Updated: {updated_count}, Unchanged: {unchanged_count}")

    # Step 2: Fetch content for each page
    content_map: dict[str, str] = {}
    if not args.skip_content:
        print("Fetching page content...")
        for i, page in enumerate(pages):
            page_id = page["id"]
            title = page.get("title", "Untitled")
            version = page.get("version", 1)
            
            # Check if we need to fetch content
            existing = existing_pages.get(page_id)
            if not args.force and existing and existing.get("version") == version:
                # Skip fetching, will use existing file
                page["_skipped"] = True
                continue
            
            print(f"  [{i+1}/{len(pages)}] {title[:60]}...", end="\r")
            try:
                content = get_page_content(base_url, page_id, email, token)
                content_map[page_id] = content
            except Exception as e:
                print(f"\n  Warning: Could not fetch content for {title}: {e}")
                content_map[page_id] = ""
        print(f"  [{len(pages)}/{len(pages)}] Done!")
    else:
        # Just use empty content for structure only
        for page in pages:
            content_map[page["id"]] = ""

    # Filter out unnamed empty pages
    pages = [p for p in pages if p.get("title", "").strip()]

    # Step 3: Build tree, assign paths, build link map, then write with rewritten links
    roots, children_map = build_tree(pages)

    stats = {"total": len(pages), "new": 0, "updated": 0, "unchanged": 0}

    if args.flat:
        # Flat mode: assign paths first
        for p in pages:
            title = p.get("title", "Untitled")
            if not title.strip():
                continue
            safe = sanitize_filename(title)
            existing = existing_pages.get(p["id"])
            needs_update = args.force or not existing or existing.get("version") != p.get("version")
            fpath = os.path.join(out, f"{safe}.md")
            if needs_update:
                p["_file_path"] = os.path.relpath(fpath, PROJECT_ROOT)
                p["_needs_update"] = True
            else:
                p["_file_path"] = existing.get("file_path", "")
                p["_last_exported"] = existing.get("last_exported")
                p["_needs_update"] = False

        # Build link map with current export paths
        link_map = build_link_map()
        for p in pages:
            pid = p.get("id")
            fp = p.get("_file_path")
            if pid and fp:
                link_map[f"confluence:{pid}"] = fp

        # Write files with link rewriting
        count = 0
        for p in pages:
            if not p.get("_needs_update"):
                if existing_pages.get(p["id"]):
                    stats["unchanged"] += 1
                continue
            title = p.get("title", "Untitled")
            if not title.strip():
                continue
            file_path = p.get("_file_path", "")
            content = content_map.get(p["id"], "")
            content = rewrite_links(content, file_path, link_map)
            fpath = os.path.join(PROJECT_ROOT, file_path)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n{content}\n")
            p["_exported"] = True
            count += 1
            if not existing_pages.get(p["id"]):
                stats["new"] += 1
            else:
                stats["updated"] += 1
    else:
        # Pass 1: assign file paths
        for root in roots:
            assign_paths(root, children_map, out, existing_pages, args.force)

        # Build link map with current export paths
        link_map = build_link_map()
        for p in pages:
            pid = p.get("id")
            fp = p.get("_file_path")
            if pid and fp:
                link_map[f"confluence:{pid}"] = fp

        # Pass 2: write files with link rewriting
        count = 0
        for root in roots:
            cc, _ = write_tree(root, children_map, content_map, out, link_map)
            count += cc

        # Calculate stats from pages
        for p in pages:
            if p.get("_exported"):
                if existing_pages.get(p["id"]):
                    stats["updated"] += 1
                else:
                    stats["new"] += 1
            elif existing_pages.get(p["id"]):
                stats["unchanged"] += 1

    # Update registry (includes every page node)
    upsert_registry(
        url=args.url,
        base_url=base_url,
        space_key=space_key,
        space_name=space_name,
        output_path=os.path.relpath(out, PROJECT_ROOT),
        page_count=count,
        pages=pages,
        space_id=space_id,
        stats=stats,
    )

    print(f"\nDone! {stats['new']} new, {stats['updated']} updated, {stats['unchanged']} unchanged in {os.path.relpath(out, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
