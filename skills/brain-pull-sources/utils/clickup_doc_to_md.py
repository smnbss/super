#!/usr/bin/env python3
from __future__ import annotations
"""
ClickUp Document -> Markdown exporter with incremental sync.

Usage:
    python clickup_doc_to_md.py <clickup_doc_url> [--token TOKEN]

Examples:
    # Export a document by URL (specific page or document root)
    python clickup_doc_to_md.py https://app.clickup.com/2408428/v/dc/29fzc-69755
    python clickup_doc_to_md.py https://app.clickup.com/2408428/v/dc/29fzc-69755/29fzc-69756

    # With explicit token
    python clickup_doc_to_md.py https://app.clickup.com/2408428/v/dc/29fzc-69755 --token pk_xxx

    # Force re-export all pages
    python clickup_doc_to_md.py https://app.clickup.com/2408428/v/dc/29fzc-69755 --force

Output is saved to:  src/clickup/<document name>/

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

from rewrite_links import build_link_map, rewrite_links


# -- Load .env from project root ----------------------------------------------

def _git_root() -> str:
    """Return the git repository root directory."""
    import subprocess
    return subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    ).stdout.strip()


def load_dotenv(root: str):
    """Load key=value pairs from .env.local file in the project root."""
    env_path = os.path.join(root, ".env.local")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


# -- Project root -------------------------------------------------------------

PROJECT_ROOT = _git_root()
load_dotenv(PROJECT_ROOT)
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "clickup")
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


def get_existing_page_map(doc_id: str) -> dict[str, dict]:
    """Get a map of page_id -> page info from existing registry."""
    entries = load_registry()
    for entry in entries:
        if entry["doc_id"] == doc_id:
            return {p["page_id"]: p for p in entry.get("pages", [])}
    return {}


def upsert_registry(url: str, workspace_id: str, doc_id: str,
                     doc_name: str, output_path: str, page_count: int,
                     pages: list[dict], stats: dict):
    """Add or update a registry entry for the given document, merging with existing pages."""
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()

    # Find existing entry by doc_id
    existing = next((e for e in entries if e["doc_id"] == doc_id), None)
    
    # Build a merged pages map from existing + new
    existing_pages_map = {}
    if existing:
        for p in existing.get("pages", []):
            existing_pages_map[p["page_id"]] = p
    
    # Update with new pages
    for p in pages:
        page_manifest = {
            "page_id": p["id"],
            "name": p.get("name", "Untitled"),
            "parent_page_id": p.get("parent_page_id"),
            "file_path": p.get("_file_path", existing_pages_map.get(p["id"], {}).get("file_path", "")),
            "date_updated": p.get("date_updated"),
            "last_exported": now if p.get("_exported") else existing_pages_map.get(p["id"], {}).get("last_exported"),
        }
        existing_pages_map[p["id"]] = page_manifest
    
    # Convert back to list
    pages_manifest = list(existing_pages_map.values())
    
    # Calculate total pages (unique)
    total_pages = len(pages_manifest)

    if existing:
        existing["url"] = url
        existing["doc_name"] = doc_name
        existing["output_path"] = output_path
        existing["page_count"] = total_pages
        existing["last_exported"] = now
        existing["export_count"] = existing.get("export_count", 0) + 1
        existing["pages"] = pages_manifest
        # Merge stats
        existing_stats = existing.get("stats", {})
        existing_stats.update(stats)
        existing["stats"] = existing_stats
    else:
        entries.append({
            "url": url,
            "workspace_id": workspace_id,
            "doc_id": doc_id,
            "doc_name": doc_name,
            "output_path": output_path,
            "page_count": total_pages,
            "first_exported": now,
            "last_exported": now,
            "export_count": 1,
            "pages": pages_manifest,
            "stats": stats,
        })

    save_registry(entries)


def print_registry(verbose: bool = False):
    """Print a formatted table of all previously exported documents."""
    entries = load_registry()
    if not entries:
        print("No documents exported yet.")
        return

    print(f"{'Doc Name':<50} {'Pages':>5}  {'Exports':>7}  {'Last Exported':<20}  URL")
    print("-" * 130)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        stats = e.get("stats", {})
        page_info = f"{stats.get('updated', 0)}/{stats.get('total', e['page_count'])} updated" if stats else str(e['page_count'])
        print(f"{e['doc_name'][:50]:<50} {page_info:>12}  {e.get('export_count', 1):>7}  {last:<20}  {e['url']}")
        if verbose:
            for p in e.get("pages", []):
                indent = "  ├── " if p.get("parent_page_id") else "  "
                updated_marker = " 📝" if p.get("date_updated") else ""
                print(f"{indent}{p['name'][:60]:<64} {p.get('file_path', '')}{updated_marker}")


# -- URL parsing --------------------------------------------------------------

URL_PATTERN = re.compile(
    r"https?://app\.clickup\.com/(\d+)/v/dc/([\w-]+)(?:/([\w-]+))?"
)


def parse_clickup_url(url: str) -> tuple[str, str, str | None]:
    """Extract (workspace_id, document_id, page_id) from a ClickUp document URL.
    
    Handles both doc URLs and specific page URLs:
    - https://app.clickup.com/<workspace>/v/dc/<doc_id>
    - https://app.clickup.com/<workspace>/v/dc/<doc_id>/<page_id>
    """
    m = URL_PATTERN.search(url)
    if not m:
        print(f"ERROR: Could not parse ClickUp doc URL: {url}", file=sys.stderr)
        print("Expected format: https://app.clickup.com/<workspace_id>/v/dc/<doc_id>", file=sys.stderr)
        print("               or https://app.clickup.com/<workspace_id>/v/dc/<doc_id>/<page_id>", file=sys.stderr)
        sys.exit(1)
    return m.group(1), m.group(2), m.group(3)


# -- API helpers --------------------------------------------------------------

def api_get(url: str, token: str, retries: int = 5):
    req = urllib.request.Request(url, headers={
        "Authorization": token,
        "Content-Type": "application/json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                wait = (10 if e.code == 429 else 3) * (attempt + 1)
                print(f"  ⚠ HTTP {e.code}, retrying in {wait}s… (attempt {attempt+1}/{retries})", flush=True)
                time.sleep(wait)
            else:
                raise


# -- ClickUp endpoints -------------------------------------------------------

BASE = "https://api.clickup.com/api/v3"


def get_doc_info(workspace_id: str, doc_id: str, token: str) -> dict:
    """Fetch document metadata (name, etc.)."""
    url = f"{BASE}/workspaces/{workspace_id}/docs/{doc_id}"
    return api_get(url, token)


def list_pages(workspace_id: str, doc_id: str, token: str) -> list[dict]:
    """Return list of top-level pages (with nested sub-pages in 'pages' field).
    Uses fewer retries since large docs always time out here."""
    url = f"{BASE}/workspaces/{workspace_id}/docs/{doc_id}/pages"
    resp = api_get(url, token, retries=2)
    if isinstance(resp, list):
        return resp
    return resp.get("pages", [])


def list_page_listing(workspace_id: str, doc_id: str, token: str) -> list[dict]:
    """Return the full page tree using the page_listing endpoint.

    This endpoint is lighter than list_pages (no content) and works
    reliably for large documents that cause list_pages to time out.
    Returns nested pages with id, name, parent_page_id, and sub-pages.
    """
    all_pages = []
    seen_ids = set()
    page_num = 0
    while True:
        url = f"{BASE}/workspaces/{workspace_id}/docs/{doc_id}/page_listing?page={page_num}"
        resp = api_get(url, token)
        if not resp:
            break
        if isinstance(resp, dict):
            items = resp.get("pages", resp.get("page_listing", []))
        else:
            items = resp
        if not items:
            break
        # Detect duplicates — the API may cycle instead of returning empty
        new_ids = {p["id"] for p in items}
        if new_ids.issubset(seen_ids):
            break
        seen_ids.update(new_ids)
        all_pages.extend(items)
        print(f"  page_listing page {page_num}: {len(items)} top-level items", flush=True)
        page_num += 1
        time.sleep(0.3)  # Avoid rate limiting
    return all_pages


def fetch_pages_with_content(workspace_id: str, doc_id: str, page_ids: list[dict],
                              token: str, existing_pages: dict[str, dict],
                              force: bool = False) -> list[dict]:
    """Fetch content for a list of pages discovered via page_listing.

    Each entry in page_ids should have 'id', 'name', 'parent_page_id'.
    Uses incremental sync: skips pages whose date_updated hasn't changed.
    """
    pages = []
    total = len(page_ids)
    new_count = 0
    updated_count = 0
    unchanged_count = 0

    for i, listing in enumerate(page_ids):
        page_id = listing["id"]
        existing = existing_pages.get(page_id)

        try:
            page_data = get_page(workspace_id, doc_id, page_id, token)
            if page_data is None:
                continue

            date_updated = page_data.get("date_updated")
            name = page_data.get("name", listing.get("name", "Untitled"))

            if not force and existing and existing.get("date_updated") == date_updated:
                pages.append({
                    "id": page_id,
                    "name": name,
                    "date_updated": date_updated,
                    "content": "",
                    "parent_page_id": listing.get("parent_page_id"),
                    "order_index": page_data.get("order_index", 0),
                    "_unchanged": True,
                    "_file_path": existing.get("file_path", ""),
                })
                unchanged_count += 1
            else:
                pages.append({
                    "id": page_id,
                    "name": name,
                    "date_updated": date_updated,
                    "content": page_data.get("content", ""),
                    "parent_page_id": listing.get("parent_page_id"),
                    "order_index": page_data.get("order_index", 0),
                })
                if existing:
                    updated_count += 1
                else:
                    new_count += 1

            if (i + 1) % 50 == 0 or (i + 1) == total:
                print(f"  Fetched {i + 1}/{total} pages ({new_count} new, {updated_count} updated, {unchanged_count} unchanged)", flush=True)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  ⚠ Page {page_id} not found, skipping")
            elif e.code in (429,):
                print(f"  ⚠ Rate limited, waiting 60s...")
                time.sleep(60)
                # Retry this page
                try:
                    page_data = get_page(workspace_id, doc_id, page_id, token)
                    if page_data:
                        pages.append({
                            "id": page_id,
                            "name": page_data.get("name", "Untitled"),
                            "date_updated": page_data.get("date_updated"),
                            "content": page_data.get("content", ""),
                            "parent_page_id": listing.get("parent_page_id"),
                            "order_index": page_data.get("order_index", 0),
                        })
                        new_count += 1
                except urllib.error.HTTPError:
                    print(f"  ⚠ Failed to fetch {page_id} after retry, skipping")
            else:
                print(f"  ⚠ Error fetching {page_id}: HTTP {e.code}")

    print(f"  Done: {new_count} new, {updated_count} updated, {unchanged_count} unchanged")
    return pages


def get_page(workspace_id: str, doc_id: str, page_id: str, token: str) -> Optional[dict]:
    """Fetch a single page by ID. Returns None if page not found."""
    url = f"{BASE}/workspaces/{workspace_id}/docs/{doc_id}/pages/{page_id}"
    try:
        return api_get(url, token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


# -- Incremental page discovery ----------------------------------------------

def discover_pages_incrementally(workspace_id: str, doc_id: str, start_page_id: str, 
                                  token: str, existing_pages: dict[str, dict],
                                  force: bool = False) -> list[dict]:
    """
    Discover and fetch pages incrementally starting from a specific page.
    
    This approach:
    1. Starts with the provided page ID
    2. Fetches that page
    3. Attempts to discover related pages (siblings, children) via ID patterns
    4. Builds up the page list incrementally
    5. Respects existing pages in registry to avoid unnecessary re-fetching
    
    Returns a flat list of page dicts with content.
    """
    pages_by_id: dict[str, dict] = {}
    to_process = [start_page_id]
    processed = set()
    
    print(f"Discovering pages incrementally starting from {start_page_id}...")
    
    while to_process:
        page_id = to_process.pop(0)
        if page_id in processed:
            continue
        processed.add(page_id)
        
        # Check if we already have this page up to date
        existing = existing_pages.get(page_id)
        
        # Fetch the page
        try:
            page_data = get_page(workspace_id, doc_id, page_id, token)
            if page_data is None:
                continue
                
            # Check if update needed
            date_updated = page_data.get("date_updated")
            if not force and existing and existing.get("date_updated") == date_updated:
                # Use cached data
                pages_by_id[page_id] = {
                    "id": page_id,
                    "name": existing.get("name", "Untitled"),
                    "date_updated": date_updated,
                    "content": "",  # Will be marked as unchanged
                    "parent_page_id": page_data.get("parent_page_id"),
                    "order_index": page_data.get("order_index", 0),
                    "_unchanged": True,
                    "_file_path": existing.get("file_path", ""),
                }
                print(f"  ✓ {page_data.get('name', 'Untitled')} (unchanged)")
            else:
                # Use fetched data
                pages_by_id[page_id] = {
                    "id": page_id,
                    "name": page_data.get("name", "Untitled"),
                    "date_updated": date_updated,
                    "content": page_data.get("content", ""),
                    "parent_page_id": page_data.get("parent_page_id"),
                    "order_index": page_data.get("order_index", 0),
                }
                action = "updated" if existing else "new"
                print(f"  ✓ {page_data.get('name', 'Untitled')} ({action})")
            
            # Try to discover sibling pages by scanning nearby IDs
            # This is heuristic-based since ClickUp doesn't provide a discovery endpoint
            # that works reliably for large documents
            if len(processed) == 1:  # Only on first page, try to find siblings
                print("  Scanning for sibling pages...")
                sibling_ids = generate_sibling_candidates(page_id)
                found_siblings = 0
                for sibling_id in sibling_ids:
                    if sibling_id not in processed and sibling_id not in to_process:
                        try:
                            test_page = get_page(workspace_id, doc_id, sibling_id, token)
                            if test_page:
                                to_process.append(sibling_id)
                                found_siblings += 1
                        except urllib.error.HTTPError:
                            pass
                if found_siblings > 0:
                    print(f"    Found {found_siblings} potential siblings")
            
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  ⚠ Error fetching {page_id}: HTTP {e.code}")
    
    return list(pages_by_id.values())


def generate_sibling_candidates(page_id: str) -> list[str]:
    """
    Generate potential sibling page IDs based on patterns in ClickUp IDs.
    ClickUp IDs often follow sequences within a document.
    """
    candidates = []
    
    # Pattern: 29fzc-XXXXXX (number sequence)
    match = re.match(r"(29fzc-)(\d+)", page_id)
    if match:
        prefix = match.group(1)
        num = int(match.group(2))
        
        # Generate nearby IDs (siblings often cluster)
        # Wider range for better discovery
        offsets = [
            -1000, -500, -200, -100, -50, -20, -10, -5, -1,
            1, 5, 10, 20, 50, 100, 200, 500, 1000
        ]
        for offset in offsets:
            sibling_num = num + offset
            if sibling_num > 0:
                candidates.append(f"{prefix}{sibling_num}")
    
    return candidates


def discover_all_doc_pages(workspace_id: str, doc_id: str, known_pages: list[dict], 
                            token: str) -> list[str]:
    """
    Try to discover all pages in a document by scanning from multiple starting points.
    Returns a list of page IDs found.
    """
    found_ids = set()
    to_check = set()
    
    # Add IDs from registry
    for p in known_pages:
        pid = p.get("page_id")
        if pid:
            found_ids.add(pid)
            to_check.add(pid)
    
    # Also try to find pages by scanning ranges
    # Extract numeric parts to find ranges
    numeric_ids = []
    for pid in found_ids:
        match = re.match(r"29fzc-(\d+)", pid)
        if match:
            numeric_ids.append(int(match.group(1)))
    
    if numeric_ids:
        min_id = min(numeric_ids)
        max_id = max(numeric_ids)
        # Scan wider range around known pages
        for num in range(min_id - 2000, max_id + 2000, 100):
            if num > 0:
                to_check.add(f"29fzc-{num}")
    
    return list(to_check)


# -- Tree flattening ---------------------------------------------------------

def flatten_pages(pages: list[dict]) -> list[dict]:
    """Recursively flatten nested pages into a flat list, preserving parent_page_id."""
    flat = []
    for p in pages:
        sub = p.pop("pages", [])
        flat.append(p)
        if sub:
            # Ensure children have parent_page_id set
            for child in sub:
                child.setdefault("parent_page_id", p["id"])
            flat.extend(flatten_pages(sub))
    return flat


def flatten_page_listing(pages: list[dict]) -> list[dict]:
    """Flatten page_listing tree into a flat list with id, name, parent_page_id."""
    flat = []
    for p in pages:
        sub = p.get("pages", [])
        flat.append({
            "id": p["id"],
            "name": p.get("name", "Untitled"),
            "parent_page_id": p.get("parent_page_id"),
        })
        if sub:
            for child in sub:
                child.setdefault("parent_page_id", p["id"])
            flat.extend(flatten_page_listing(sub))
    return flat


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
        pid = p.get("parent_page_id")
        if pid and pid in by_id:
            children.setdefault(pid, []).append(p)
        else:
            roots.append(p)

    # Sort each group by order_index
    roots.sort(key=lambda p: p.get("order_index", 0))
    for k in children:
        children[k].sort(key=lambda p: p.get("order_index", 0))

    return roots, children


# -- File writing -------------------------------------------------------------

INVALID_CHARS = re.compile(r'[<>"/\\|?*]')


def sanitize_filename(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    # Collapse repeated dashes
    name = re.sub(r"-{2,}", "-", name)
    return name[:200]  # filesystem limit safety


def assign_paths(node: dict, children_map: dict, parent_dir: str):
    """
    Recursively assign _file_path to each node without writing files.
    Also creates necessary directories.
    """
    name = node.get("name", "Untitled")
    if not name.strip():
        return
    safe_name = sanitize_filename(name)
    node_id = node["id"]
    kids = children_map.get(node_id, [])

    if kids:
        fpath = os.path.join(parent_dir, safe_name, f"{safe_name}.md")
        # Create directory for children
        child_dir = os.path.join(parent_dir, safe_name)
        os.makedirs(child_dir, exist_ok=True)
    else:
        fpath = os.path.join(parent_dir, f"{safe_name}.md")

    node["_file_path"] = os.path.relpath(fpath, PROJECT_ROOT)

    for child in kids:
        child_dir = os.path.join(parent_dir, safe_name) if kids else parent_dir
        assign_paths(child, children_map, child_dir)


def write_page(page: dict, content_map: dict, link_map: dict[str, str], output_dir: str):
    """Write a single page file with link rewriting."""
    if page.get("_unchanged"):
        return False  # Skip unchanged pages
        
    file_path = page.get("_file_path", "")
    if not file_path:
        return False
    
    name = page.get("name", "Untitled")
    content = content_map.get(page["id"], "")
    content = rewrite_links(content, file_path, link_map)

    fpath = os.path.join(PROJECT_ROOT, file_path)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(f"# {name}\n\n{content}\n")
    
    page["_exported"] = True
    return True


def write_tree(node: dict, children_map: dict, content_map: dict,
               link_map: dict[str, str]) -> int:
    """
    Recursively write pages that need updating, with link rewriting.
    Returns count of written pages.
    """
    count = 0
    
    if write_page(node, content_map, link_map, ""):
        count += 1

    for child in children_map.get(node["id"], []):
        count += write_tree(child, children_map, content_map, link_map)

    return count


# -- Post-processing: Link updates -------------------------------------------

def update_all_links(pages: list[dict], link_map: dict[str, str]):
    """
    Second pass: Update links in all exported files.
    This ensures cross-links are correct after all pages are written.
    """
    for page in pages:
        if not page.get("_exported"):
            continue
            
        file_path = page.get("_file_path")
        if not file_path:
            continue
        
        fpath = os.path.join(PROJECT_ROOT, file_path)
        if not os.path.exists(fpath):
            continue
        
        # Read current content
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Rewrite links
        new_content = rewrite_links(content, file_path, link_map)
        
        # Write back if changed
        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"  📝 Updated links in {os.path.basename(file_path)}")


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export a ClickUp document to src/clickup/<doc name>/ as Markdown files."
    )
    parser.add_argument("url", nargs="?", help="ClickUp document URL (e.g. https://app.clickup.com/2408428/v/dc/29fzc-69755)")
    parser.add_argument("--token", default=os.environ.get("CLICKUP_TOKEN", ""),
                        help="ClickUp API token (or set CLICKUP_TOKEN env var)")
    parser.add_argument("--flat", action="store_true",
                        help="Write all files flat in output_dir (no subdirectories)")
    parser.add_argument("--list", action="store_true",
                        help="List all previously exported documents and exit")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="With --list, show all individual pages per document")
    parser.add_argument("--force", action="store_true",
                        help="Force re-export all pages even if unchanged")
    args = parser.parse_args()

    if args.list:
        print_registry(verbose=args.verbose)
        return

    if not args.url:
        parser.error("url is required (unless using --list)")

    token = args.token
    if not token:
        print("ERROR: No API token. Set CLICKUP_TOKEN or use --token.", file=sys.stderr)
        sys.exit(1)

    # Parse URL -> workspace_id + doc_id (+ optional page_id)
    ws, doc, page_id = parse_clickup_url(args.url)

    # Fetch document name from API
    print(f"Fetching document info for {doc}...")
    try:
        doc_info = get_doc_info(ws, doc, token)
        doc_name = doc_info.get("name", doc)
    except urllib.error.HTTPError:
        print("  Could not fetch doc name, using doc ID as folder name.")
        doc_name = doc

    safe_doc_name = sanitize_filename(doc_name)
    out = os.path.join(OUTPUT_BASE, safe_doc_name)
    os.makedirs(out, exist_ok=True)
    print(f"Output folder: {os.path.relpath(out, PROJECT_ROOT)}")

    # Load existing registry for comparison
    existing_pages = get_existing_page_map(doc)
    if existing_pages and not args.force:
        print(f"  Found {len(existing_pages)} pages in registry")
    elif args.force:
        print("  Force mode: re-exporting all pages")

    # Determine starting point
    if page_id:
        print(f"Starting from specific page: {page_id}")
        start_page_id = page_id
    else:
        # Try to find a starting page from registry or default
        if existing_pages:
            start_page_id = list(existing_pages.keys())[0]
            print(f"Using first known page: {start_page_id}")
        else:
            print("ERROR: No page ID provided and no existing registry. "
                  "Please provide a URL with a specific page ID.", file=sys.stderr)
            sys.exit(1)

    # Step 1: Try to list all pages first (works for smaller docs)
    # If that fails, use page_listing + individual fetches (works for large docs)
    # Last resort: heuristic incremental discovery
    pages = []
    try:
        print(f"Trying to list all pages...", flush=True)
        raw_pages = list_pages(ws, doc, token)
        if raw_pages:
            pages = flatten_pages(raw_pages)
            for p in pages:
                p["content"] = p.get("content", "")
            print(f"  Listed {len(pages)} pages via API", flush=True)
    except urllib.error.HTTPError as e:
        if e.code in (500, 429):
            print(f"  API list failed (HTTP {e.code}), trying page_listing endpoint...", flush=True)
        else:
            raise

    # If list failed or returned empty, use page_listing + individual page fetches
    if not pages:
        try:
            raw_listing = list_page_listing(ws, doc, token)
            if raw_listing:
                flat_listing = flatten_page_listing(raw_listing)
                print(f"  Discovered {len(flat_listing)} pages via page_listing")
                print(f"  Fetching page content individually...")
                pages = fetch_pages_with_content(
                    ws, doc, flat_listing, token, existing_pages, args.force
                )
        except urllib.error.HTTPError as e:
            print(f"  page_listing also failed (HTTP {e.code}), falling back to incremental discovery...")

    # Last resort: heuristic incremental discovery
    if not pages:
        pages = discover_pages_incrementally(
            ws, doc, start_page_id, token, existing_pages, args.force
        )
    
    if not pages:
        print("No pages found. Exiting.")
        return
    
    print(f"\nTotal pages discovered: {len(pages)}")

    # Step 2: Build tree structure
    roots, children_map = build_tree(pages)
    
    # Step 3: Assign file paths
    for root in roots:
        assign_paths(root, children_map, out)

    # Step 4: Build link map with current export paths
    link_map = build_link_map()
    for p in pages:
        pid = p.get("id")
        fp = p.get("_file_path")
        if pid and fp:
            link_map[f"clickup:{pid}"] = fp

    # Step 5: Write all content files (first pass)
    print("\nWriting files...")
    content_map = {p["id"]: p.get("content", "") for p in pages}
    
    count = 0
    for root in roots:
        count += write_tree(root, children_map, content_map, link_map)
    
    print(f"  {count} files written")

    # Step 6: Update all links (second pass)
    print("\nUpdating cross-links...")
    update_all_links(pages, link_map)

    # Calculate stats
    stats = {"total": len(pages), "new": 0, "updated": 0, "unchanged": 0}
    for p in pages:
        if p.get("_exported"):
            if existing_pages.get(p["id"]):
                stats["updated"] += 1
            else:
                stats["new"] += 1
        elif existing_pages.get(p["id"]):
            stats["unchanged"] += 1

    # Update registry
    upsert_registry(
        url=args.url,
        workspace_id=ws,
        doc_id=doc,
        doc_name=doc_name,
        output_path=os.path.relpath(out, PROJECT_ROOT),
        page_count=count,
        pages=pages,
        stats=stats,
    )

    print(f"\nDone! {stats['new']} new, {stats['updated']} updated, {stats['unchanged']} unchanged")
    print(f"Output: {os.path.relpath(out, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
