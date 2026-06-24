#!/usr/bin/env python3
from __future__ import annotations
"""
Outline collection -> Markdown exporter with incremental sync.

Outline (docs.weroad.com) exposes a clean REST API that returns Markdown
directly via `documents.export`, so — unlike the Confluence/ClickUp exporters —
there is no HTML-to-Markdown conversion step. We fetch the collection's nested
document tree, mirror it as a folder hierarchy under src/outline/, and write the
exported Markdown verbatim (keeping the leading H1 and absolute /doc/ links).

Usage:
    python outline_to_md.py <collection_url> [--token TOKEN] [--force] [--list]

Examples:
    # Export a collection by URL
    python outline_to_md.py https://docs.weroad.com/collection/weroad-6YhKbLKB40/overview

    # Accept a bare urlId or UUID
    python outline_to_md.py 6YhKbLKB40

    # Force re-export every document (ignore the incremental registry)
    python outline_to_md.py https://docs.weroad.com/collection/weroad-6YhKbLKB40/overview --force

    # List previously exported collections and exit
    python outline_to_md.py --list

Output is saved to:  src/outline/<collection name>/

Environment:
    OUTLINE_API_TOKEN  -- Outline personal API token (if --token not provided)
    OUTLINE_BASE_URL   -- Outline base URL (default https://docs.weroad.com)

Notes:
    docs.weroad.com sits behind Cloudflare, which returns HTTP 403 ("error code:
    1010") to the default `Python-urllib/*` user-agent. Every request therefore
    sets a curl-style User-Agent. API responses can contain raw control chars,
    so JSON is parsed with strict=False.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone


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
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "outline")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")

DEFAULT_BASE_URL = os.environ.get("OUTLINE_BASE_URL", "https://docs.weroad.com").rstrip("/")
# Cloudflare 403s the default urllib UA; any curl/browser UA passes.
USER_AGENT = "curl/8.7.1"


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


def get_existing_doc_map(collection_id: str) -> dict[str, dict]:
    """Get a map of doc_id -> doc info from the existing registry."""
    for entry in load_registry():
        if entry.get("collection_id") == collection_id:
            return {d["doc_id"]: d for d in entry.get("documents", [])}
    return {}


def upsert_registry(url: str, collection_id: str, collection_url_id: str,
                    collection_name: str, output_path: str, doc_count: int,
                    docs: list[dict], stats: dict | None = None):
    """Add or update the registry entry for the given collection."""
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()

    docs_manifest = []
    for d in docs:
        docs_manifest.append({
            "doc_id": d["id"],
            "title": d.get("title", "Untitled"),
            "parent_id": d.get("parent_id"),
            "file_path": d.get("_file_path", ""),
            "updated_at": d.get("updated_at"),
            "last_exported": now if d.get("_exported") else d.get("_last_exported"),
        })

    existing = next((e for e in entries if e.get("collection_id") == collection_id), None)
    if existing:
        existing.update({
            "url": url,
            "collection_url_id": collection_url_id,
            "collection_name": collection_name,
            "output_path": output_path,
            "doc_count": doc_count,
            "last_exported": now,
            "export_count": existing.get("export_count", 0) + 1,
            "documents": docs_manifest,
        })
        if stats:
            existing["stats"] = stats
    else:
        entries.append({
            "url": url,
            "collection_id": collection_id,
            "collection_url_id": collection_url_id,
            "collection_name": collection_name,
            "output_path": output_path,
            "doc_count": doc_count,
            "first_exported": now,
            "last_exported": now,
            "export_count": 1,
            "documents": docs_manifest,
            "stats": stats or {},
        })

    save_registry(entries)


def print_registry(verbose: bool = False):
    """Print a formatted table of all previously exported collections."""
    entries = load_registry()
    if not entries:
        print("No collections exported yet.")
        return

    print(f"{'Collection Name':<50} {'Docs':>12}  {'Exports':>7}  {'Last Exported':<20}  URL")
    print("-" * 130)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        stats = e.get("stats", {})
        doc_info = (f"{stats.get('updated', 0)}/{stats.get('total', e['doc_count'])} updated"
                    if stats else str(e["doc_count"]))
        print(f"{e['collection_name'][:50]:<50} {doc_info:>12}  {e.get('export_count', 1):>7}  "
              f"{last:<20}  {e['url']}")
        if verbose:
            for d in e.get("documents", []):
                indent = "  ├── " if d.get("parent_id") else "  "
                print(f"{indent}{d['title'][:60]:<64} {d.get('file_path', '')}")


# -- URL parsing --------------------------------------------------------------

# https://docs.weroad.com/collection/<slug>-<urlId>/overview
_COLLECTION_URL = re.compile(r"/collection/(?:.*-)?([A-Za-z0-9]{8,})(?:/|$)")
_BARE_ID = re.compile(r"^[A-Za-z0-9]{8,}$|^[0-9a-f-]{36}$")


def parse_collection_ref(ref: str) -> str:
    """Extract the collection urlId (or UUID) from a URL or bare identifier."""
    ref = ref.strip()
    if _BARE_ID.match(ref):
        return ref
    m = _COLLECTION_URL.search(ref)
    if m:
        return m.group(1)
    print(f"ERROR: Could not parse Outline collection reference: {ref}", file=sys.stderr)
    print("Expected a collection URL (…/collection/<slug>-<urlId>/overview) or a bare urlId.",
          file=sys.stderr)
    sys.exit(1)


# -- API helpers --------------------------------------------------------------

def api_post(token: str, endpoint: str, payload: dict) -> dict:
    """POST to an Outline API endpoint and return the parsed JSON body."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_BASE_URL}/api/{endpoint}",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,  # dodge Cloudflare 1010
        },
    )
    with urllib.request.urlopen(req) as resp:
        # Outline can emit raw control chars inside document text fields.
        return json.loads(resp.read().decode("utf-8"), strict=False)


def get_collection_info(token: str, ref: str) -> dict:
    """Fetch collection metadata (accepts urlId or UUID)."""
    resp = api_post(token, "collections.info", {"id": ref})
    return resp.get("data", {})


def get_document_tree(token: str, collection_id: str) -> list[dict]:
    """Fetch the nested document nav tree for a collection."""
    resp = api_post(token, "collections.documents", {"id": collection_id})
    return resp.get("data", [])


def list_documents(token: str, collection_id: str) -> dict[str, str]:
    """Return a map of doc_id -> updatedAt for every document in the collection.

    Paginated via documents.list; used to drive incremental sync.
    """
    updated_map: dict[str, str] = {}
    offset = 0
    limit = 100
    while True:
        resp = api_post(token, "documents.list", {
            "collectionId": collection_id,
            "limit": limit,
            "offset": offset,
        })
        batch = resp.get("data", [])
        for d in batch:
            updated_map[d["id"]] = d.get("updatedAt") or d.get("updated_at")
        if len(batch) < limit:
            break
        offset += limit
    return updated_map


def export_document(token: str, doc_id: str) -> str:
    """Fetch a single document as Markdown (already converted by Outline)."""
    resp = api_post(token, "documents.export", {"id": doc_id})
    return resp.get("data", "") or ""


# -- Tree flattening ----------------------------------------------------------

def flatten_tree(nodes: list[dict], parent_id: str | None,
                 updated_map: dict[str, str], out: list[dict]):
    """Walk the nested nav tree into a flat ordered list with parent links."""
    for node in nodes:
        doc = {
            "id": node["id"],
            "title": node.get("title") or "Untitled",
            "parent_id": parent_id,
            "updated_at": updated_map.get(node["id"]),
            "children_ids": [c["id"] for c in node.get("children", [])],
        }
        out.append(doc)
        flatten_tree(node.get("children", []), node["id"], updated_map, out)


# -- File writing -------------------------------------------------------------

INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-") or "Untitled"
    return name[:200]  # filesystem limit safety


def assign_paths(docs: list[dict], out_dir: str):
    """Assign a relative `_file_path` to each doc, mirroring the tree as folders.

    A doc with children becomes a folder containing its own `<name>.md`; a leaf
    is a single `<name>.md` in its parent's folder. Sibling filename collisions
    are disambiguated with a short id suffix.
    """
    by_id = {d["id"]: d for d in docs}
    used: set[str] = set()  # lower-cased absolute paths already claimed

    def dir_for(doc: dict) -> str:
        # Directory that holds this doc's file (and any children).
        pid = doc.get("parent_id")
        if pid and pid in by_id:
            parent_dir = dir_for(by_id[pid])
        else:
            parent_dir = out_dir
        safe = sanitize_filename(doc["title"])
        return os.path.join(parent_dir, safe) if doc.get("children_ids") else parent_dir

    for doc in docs:
        safe = sanitize_filename(doc["title"])
        node_dir = dir_for(doc)
        fpath = os.path.join(node_dir, f"{safe}.md")
        if fpath.lower() in used:
            fpath = os.path.join(node_dir, f"{safe}-{doc['id'][:8]}.md")
        used.add(fpath.lower())
        doc["_file_path"] = os.path.relpath(fpath, PROJECT_ROOT)


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export an Outline collection to src/outline/<collection name>/ as Markdown."
    )
    parser.add_argument("url", nargs="?",
                        help="Collection URL or urlId (e.g. https://docs.weroad.com/collection/weroad-6YhKbLKB40/overview)")
    parser.add_argument("--token", default=os.environ.get("OUTLINE_API_TOKEN", ""),
                        help="Outline API token (or set OUTLINE_API_TOKEN env var)")
    parser.add_argument("--list", action="store_true",
                        help="List previously exported collections and exit")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="With --list, show every document per collection")
    parser.add_argument("--force", action="store_true",
                        help="Force re-export of every document even if unchanged")
    args = parser.parse_args()

    if args.list:
        print_registry(verbose=args.verbose)
        return

    if not args.url:
        parser.error("url is required (unless using --list)")

    token = args.token
    if not token:
        print("ERROR: Outline API token required. Set OUTLINE_API_TOKEN or use --token.",
              file=sys.stderr)
        sys.exit(1)

    ref = parse_collection_ref(args.url)

    # Resolve collection metadata
    print(f"Fetching collection info for {ref}...")
    try:
        info = get_collection_info(token, ref)
    except urllib.error.HTTPError as e:
        print(f"ERROR: Could not fetch collection: {e}", file=sys.stderr)
        sys.exit(1)
    collection_id = info.get("id")
    collection_url_id = info.get("urlId", ref)
    collection_name = info.get("name") or ref
    if not collection_id:
        print(f"ERROR: No collection found for {ref}", file=sys.stderr)
        sys.exit(1)

    safe_name = sanitize_filename(collection_name)
    out_dir = os.path.join(OUTPUT_BASE, safe_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Collection: \"{collection_name}\"  ->  {os.path.relpath(out_dir, PROJECT_ROOT)}")

    existing = get_existing_doc_map(collection_id)
    if existing and not args.force:
        print(f"  Found {len(existing)} documents in registry (comparing for changes)...")
    elif args.force:
        print("  Force mode: re-exporting all documents")

    # Fetch tree + updatedAt map
    print("Listing documents...")
    try:
        tree = get_document_tree(token, collection_id)
        updated_map = list_documents(token, collection_id)
    except urllib.error.HTTPError as e:
        print(f"ERROR: Could not list documents: {e}", file=sys.stderr)
        sys.exit(1)

    docs: list[dict] = []
    flatten_tree(tree, None, updated_map, docs)
    print(f"  Found {len(docs)} documents.")
    if not docs:
        print("No documents found. Exiting.")
        return

    # Decide what needs updating
    for d in docs:
        prev = existing.get(d["id"])
        d["_needs_update"] = (
            args.force
            or prev is None
            or prev.get("updated_at") != d.get("updated_at")
            or d.get("updated_at") is None  # can't prove unchanged -> refetch
        )
        if not d["_needs_update"] and prev:
            d["_file_path"] = prev.get("file_path", "")
            d["_last_exported"] = prev.get("last_exported")

    new_count = sum(1 for d in docs if d["_needs_update"] and d["id"] not in existing)
    upd_count = sum(1 for d in docs if d["_needs_update"] and d["id"] in existing)
    unchanged = len(docs) - new_count - upd_count
    if not args.force:
        print(f"  New: {new_count}, Updated: {upd_count}, Unchanged: {unchanged}")

    # Assign file paths for the whole tree (so unchanged docs keep stable paths too)
    assign_paths(docs, out_dir)

    # Fetch + write changed docs (content written verbatim — already Markdown)
    print("Exporting document content...")
    stats = {"total": len(docs), "new": 0, "updated": 0, "unchanged": unchanged}
    to_write = [d for d in docs if d["_needs_update"]]
    for i, d in enumerate(to_write):
        print(f"  [{i+1}/{len(to_write)}] {d['title'][:60]}...", end="\r")
        try:
            content = export_document(token, d["id"])
        except Exception as e:
            print(f"\n  Warning: could not export {d['title']}: {e}")
            continue
        fpath = os.path.join(PROJECT_ROOT, d["_file_path"])
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n")
        d["_exported"] = True
        if d["id"] in existing:
            stats["updated"] += 1
        else:
            stats["new"] += 1
    if to_write:
        print(f"  [{len(to_write)}/{len(to_write)}] Done!          ")
    else:
        print("  Nothing to export — all documents up to date.")

    upsert_registry(
        url=args.url,
        collection_id=collection_id,
        collection_url_id=collection_url_id,
        collection_name=collection_name,
        output_path=os.path.relpath(out_dir, PROJECT_ROOT),
        doc_count=len(docs),
        docs=docs,
        stats=stats,
    )

    print(f"\nDone! {stats['new']} new, {stats['updated']} updated, {stats['unchanged']} unchanged "
          f"in {os.path.relpath(out_dir, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
