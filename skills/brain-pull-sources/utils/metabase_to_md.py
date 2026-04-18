#!/usr/bin/env python3
from __future__ import annotations
"""
Metabase -> Markdown index exporter with incremental sync.

Exports all collections, dashboards, cards (questions), databases, tables,
and metrics from a Metabase instance into a structured markdown index.

Usage:
    python metabase_to_md.py https://metabase.example.io/
    python metabase_to_md.py --force   # re-export everything
    python metabase_to_md.py --list    # show registry

Output is saved to:
    src/metabase/<instance>/

Environment:
    METABASE_API_KEY      -- Metabase API key (preferred)
    METABASE_USER_EMAIL   -- Metabase email (fallback)
    METABASE_PASSWORD     -- Metabase password (fallback)
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
from urllib.parse import urlparse


# -- Project root (use git to find repo root) ---------------------------------

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

OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "metabase")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")

INVALID_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')


# -- Registry -----------------------------------------------------------------

def load_registry() -> dict:
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(data: dict):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def print_registry():
    data = load_registry()
    if not data:
        print("No Metabase instances exported yet.")
        return
    for instance, info in data.items():
        print(f"\nInstance: {instance}")
        print(f"  URL: {info.get('url', '—')}")
        print(f"  Last exported: {info.get('last_exported', '—')[:19].replace('T', ' ')}")
        print(f"  Export count: {info.get('export_count', 0)}")
        stats = info.get("stats", {})
        for model, count in stats.items():
            print(f"  {model}: {count}")


# -- URL parsing --------------------------------------------------------------

def parse_metabase_url(url: str) -> tuple[str, str]:
    """Return (base_url, instance_name) from a Metabase URL.
    Instance name uses the domain's second part (org name), e.g.:
    metabase.example.io -> 'example', analytics.acme.com -> 'acme'."""
    parsed = urlparse(url.rstrip("/"))
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    parts = parsed.netloc.split(".")
    instance_name = parts[1] if len(parts) >= 3 else parts[0]
    return base_url, instance_name


# -- Metabase API client ------------------------------------------------------

class MetabaseClient:
    def __init__(self, base_url: str, api_key: str = "", email: str = "", password: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session_token = ""
        self.api_key = api_key

        if api_key:
            print("  Auth: using API key")
        elif email and password:
            print("  Auth: using email/password session")
            self._login(email, password)
        else:
            print("ERROR: No auth configured. Set METABASE_API_KEY or METABASE_USER_EMAIL + METABASE_PASSWORD.",
                  file=sys.stderr)
            sys.exit(1)

    def _login(self, email: str, password: str):
        body = json.dumps({"username": email, "password": password}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/session",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            self.session_token = data.get("id", "")
            if not self.session_token:
                print("ERROR: Login failed — no session token returned.", file=sys.stderr)
                sys.exit(1)

    def _headers(self) -> dict:
        headers = {"User-Agent": "brain-sync/1.0", "Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        else:
            headers["X-Metabase-Session"] = self.session_token
        return headers

    def get(self, endpoint: str, params: dict = None, retries: int = 3) -> any:
        url = f"{self.base_url}/api/{endpoint.lstrip('/')}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if query:
                url += f"?{query}"

        req = urllib.request.Request(url, headers=self._headers(), method="GET")

        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                    wait = 5 * (attempt + 1) if e.code == 429 else 3 * (attempt + 1)
                    print(f"  HTTP {e.code}, retrying in {wait}s…", flush=True)
                    time.sleep(wait)
                else:
                    raise
            except (urllib.error.URLError, ConnectionResetError, OSError) as e:
                if attempt < retries - 1:
                    wait = 3 * (attempt + 1)
                    print(f"  Connection error ({e}), retrying in {wait}s…", flush=True)
                    time.sleep(wait)
                else:
                    raise


# -- Fetchers -----------------------------------------------------------------

def fetch_databases(client: MetabaseClient) -> list[dict]:
    data = client.get("database")
    return data.get("data", data) if isinstance(data, dict) else data


def fetch_tables(client: MetabaseClient) -> list[dict]:
    return client.get("table")


def fetch_collections(client: MetabaseClient) -> list[dict]:
    return client.get("collection")


def fetch_dashboards(client: MetabaseClient) -> list[dict]:
    """Fetch all dashboards via search API (includes collection info)."""
    results = []
    page = 0
    while True:
        data = client.get("search", {"models": "dashboard", "limit": "100", "offset": str(page * 100)})
        items = data.get("data", []) if isinstance(data, dict) else data
        if not items:
            break
        results.extend(items)
        total = data.get("total", len(results)) if isinstance(data, dict) else len(results)
        if len(results) >= total:
            break
        page += 1
    return results


def fetch_cards(client: MetabaseClient) -> list[dict]:
    """Fetch all cards/questions via direct /api/card (no search cap)."""
    data = client.get("card")
    return data if isinstance(data, list) else []


def fetch_metrics(client: MetabaseClient) -> list[dict]:
    """Fetch metrics (legacy endpoint, may return empty on newer Metabase)."""
    try:
        data = client.get("legacy-metric")
        return data if isinstance(data, list) else []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Try older endpoint
            try:
                data = client.get("metric")
                return data if isinstance(data, list) else []
            except urllib.error.HTTPError:
                return []
        return []


# -- Collection tree builder --------------------------------------------------

def build_collection_tree(collections: list[dict]) -> dict[int, dict]:
    """Build a lookup from collection id -> collection with path."""
    by_id = {}
    for c in collections:
        cid = c.get("id")
        if cid is not None:
            by_id[cid] = c
    return by_id


def resolve_collection_path(collection_id: Optional[int], tree: dict[int, dict]) -> str:
    """Resolve full path like 'Example / TO / Travels and Tours Portfolio'."""
    if collection_id is None or collection_id not in tree:
        return "Root"
    parts = []
    c = tree[collection_id]
    # Use location string to build path (format: "/98/145/")
    location = c.get("location", "")
    if location and location != "/":
        parent_ids = [int(x) for x in location.strip("/").split("/") if x]
        for pid in parent_ids:
            if pid in tree:
                parts.append(tree[pid].get("name", f"#{pid}"))
    parts.append(c.get("name", f"#{collection_id}"))
    return " / ".join(parts)


# -- Markdown rendering -------------------------------------------------------

def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    return name[:150]


def render_databases(databases: list[dict], base_url: str) -> str:
    lines = ["# Databases", ""]
    lines.append(f"| ID | Name | Engine | Tables |")
    lines.append("|-----|------|--------|--------|")
    for db in sorted(databases, key=lambda d: d.get("name", "")):
        dbid = db.get("id", "")
        name = db.get("name", "—")
        engine = db.get("engine", "—")
        tables = db.get("tables", [])
        n_tables = len(tables) if isinstance(tables, list) else "—"
        lines.append(f"| {dbid} | [{name}]({base_url}/database/{dbid}) | {engine} | {n_tables} |")
    lines.append("")
    return "\n".join(lines)


def render_tables(tables: list[dict], base_url: str) -> str:
    lines = ["# Tables", ""]

    # Group by database
    by_db: dict[str, list[dict]] = {}
    for t in tables:
        db_name = t.get("db", {}).get("name", "Unknown") if isinstance(t.get("db"), dict) else f"DB #{t.get('db_id', '?')}"
        by_db.setdefault(db_name, []).append(t)

    for db_name in sorted(by_db.keys()):
        db_tables = by_db[db_name]
        lines.append(f"## {db_name}")
        lines.append("")
        lines.append("| ID | Schema | Name | Rows | Description |")
        lines.append("|-----|--------|------|------|-------------|")
        for t in sorted(db_tables, key=lambda x: (x.get("schema", ""), x.get("name", ""))):
            tid = t.get("id", "")
            schema = t.get("schema", "—")
            name = t.get("name", "—")
            display_name = t.get("display_name", name)
            rows = t.get("rows", "—")
            desc = (t.get("description") or "").replace("\n", " ").replace("|", "\\|")[:100]
            lines.append(f"| {tid} | {schema} | {display_name} | {rows} | {desc} |")
        lines.append("")

    return "\n".join(lines)


def render_collections(collections: list[dict], base_url: str) -> str:
    lines = ["# Collections", ""]

    tree = build_collection_tree(collections)

    # Build hierarchy: group by parent path
    root_collections = []
    child_map: dict[str, list[dict]] = {}

    for c in collections:
        if c.get("archived") or c.get("is_personal"):
            continue
        location = c.get("location", "/")
        if location == "/":
            root_collections.append(c)
        else:
            child_map.setdefault(location, []).append(c)

    def render_tree(coll: dict, depth: int = 0):
        cid = coll.get("id", "")
        name = coll.get("name", "—")
        indent = "  " * depth
        lines.append(f"{indent}- [{name}]({base_url}/collection/{cid})")
        # Find children: location = "/<parent_path>/<cid>/"
        child_loc = coll.get("location", "/").rstrip("/") + f"/{cid}/"
        if child_loc == f"//{cid}/":
            child_loc = f"/{cid}/"
        children = child_map.get(child_loc, [])
        for child in sorted(children, key=lambda x: x.get("name", "")):
            render_tree(child, depth + 1)

    for rc in sorted(root_collections, key=lambda x: x.get("name", "")):
        render_tree(rc)

    lines.append("")
    return "\n".join(lines)


def render_dashboards(dashboards: list[dict], collections: list[dict], base_url: str) -> str:
    lines = ["# Dashboards", ""]

    tree = build_collection_tree(collections)

    # Group by collection path
    by_collection: dict[str, list[dict]] = {}
    for d in dashboards:
        cid = d.get("collection_id")
        path = resolve_collection_path(cid, tree)
        by_collection.setdefault(path, []).append(d)

    for path in sorted(by_collection.keys()):
        items = by_collection[path]
        lines.append(f"## {path}")
        lines.append("")
        lines.append("| ID | Name | Cards | Updated |")
        lines.append("|-----|------|-------|---------|")
        for d in sorted(items, key=lambda x: x.get("name", "")):
            did = d.get("id", "")
            name = (d.get("name") or "Untitled").replace("|", "\\|")
            updated = (d.get("updated_at") or "")[:10]
            # card count not always in search results
            lines.append(f"| {did} | [{name}]({base_url}/dashboard/{did}) | — | {updated} |")
        lines.append("")

    return "\n".join(lines)


def render_cards(cards: list[dict], collections: list[dict], base_url: str) -> str:
    lines = ["# Cards (Questions)", ""]

    tree = build_collection_tree(collections)

    # Group by collection path
    by_collection: dict[str, list[dict]] = {}
    for c in cards:
        cid = c.get("collection_id")
        path = resolve_collection_path(cid, tree)
        by_collection.setdefault(path, []).append(c)

    for path in sorted(by_collection.keys()):
        items = by_collection[path]
        lines.append(f"## {path}")
        lines.append("")
        lines.append("| ID | Name | Type | Database | Updated |")
        lines.append("|-----|------|------|----------|---------|")
        for c in sorted(items, key=lambda x: x.get("name", "")):
            cid = c.get("id", "")
            name = (c.get("name") or "Untitled").replace("|", "\\|")
            qtype = c.get("display", c.get("type", "—"))
            db = c.get("database_name", "—")
            updated = (c.get("updated_at") or "")[:10]
            lines.append(f"| {cid} | [{name}]({base_url}/question/{cid}) | {qtype} | {db} | {updated} |")
        lines.append("")

    return "\n".join(lines)


def render_metrics(metrics: list[dict], base_url: str) -> str:
    if not metrics:
        return "# Metrics\n\nNo metrics defined.\n"

    lines = ["# Metrics", ""]
    lines.append("| ID | Name | Description | Table | Updated |")
    lines.append("|-----|------|-------------|-------|---------|")
    for m in sorted(metrics, key=lambda x: x.get("name", "")):
        mid = m.get("id", "")
        name = (m.get("name") or "—").replace("|", "\\|")
        desc = (m.get("description") or "").replace("\n", " ").replace("|", "\\|")[:80]
        table = m.get("table", {}).get("display_name", "—") if isinstance(m.get("table"), dict) else "—"
        updated = (m.get("updated_at") or "")[:10]
        lines.append(f"| {mid} | {name} | {desc} | {table} | {updated} |")
    lines.append("")
    return "\n".join(lines)


def render_index(stats: dict, instance_name: str, base_url: str) -> str:
    """Render the top-level index file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Metabase Index — {instance_name}",
        "",
        f"**Source:** [{base_url}]({base_url})",
        f"**Last indexed:** {now}",
        "",
        "## Contents",
        "",
        f"- [Databases](databases.md) — {stats.get('databases', 0)} databases",
        f"- [Tables](tables.md) — {stats.get('tables', 0)} tables",
        f"- [Collections](collections.md) — {stats.get('collections', 0)} collections",
        f"- [Dashboards](dashboards.md) — {stats.get('dashboards', 0)} dashboards",
        f"- [Cards](cards.md) — {stats.get('cards', 0)} cards (questions)",
        f"- [Metrics](metrics.md) — {stats.get('metrics', 0)} metrics",
        "",
    ]
    return "\n".join(lines)


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export Metabase index to src/metabase/<instance>/ as Markdown."
    )
    parser.add_argument("url", nargs="?",
                        help="Metabase URL — e.g. https://metabase.example.io/")
    parser.add_argument("--list", action="store_true",
                        help="List all previously exported instances and exit")
    parser.add_argument("--force", action="store_true",
                        help="Re-export even if recently synced")
    args = parser.parse_args()

    if args.list:
        print_registry()
        return

    if not args.url:
        parser.error("url is required (unless using --list)")

    base_url, instance_name = parse_metabase_url(args.url)

    # Auth
    api_key = os.environ.get("METABASE_API_KEY", "")
    email = os.environ.get("METABASE_USER_EMAIL", "")
    password = os.environ.get("METABASE_PASSWORD", "")

    print(f"Connecting to Metabase at {base_url}...")
    client = MetabaseClient(base_url, api_key=api_key, email=email, password=password)

    out_dir = os.path.join(OUTPUT_BASE, instance_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Output folder: {os.path.relpath(out_dir, PROJECT_ROOT)}")

    # Fetch all data
    print("Fetching databases...", flush=True)
    databases = fetch_databases(client)
    print(f"  {len(databases)} databases")

    print("Fetching tables...", flush=True)
    tables = fetch_tables(client)
    print(f"  {len(tables)} tables")

    print("Fetching collections...", flush=True)
    collections = fetch_collections(client)
    print(f"  {len(collections)} collections")

    print("Fetching dashboards...", flush=True)
    dashboards = fetch_dashboards(client)
    print(f"  {len(dashboards)} dashboards")

    print("Fetching cards...", flush=True)
    cards = fetch_cards(client)
    print(f"  {len(cards)} cards")

    print("Fetching metrics...", flush=True)
    metrics = fetch_metrics(client)
    print(f"  {len(metrics)} metrics")

    # Render and write
    files = {
        "databases.md": render_databases(databases, base_url),
        "tables.md": render_tables(tables, base_url),
        "collections.md": render_collections(collections, base_url),
        "dashboards.md": render_dashboards(dashboards, collections, base_url),
        "cards.md": render_cards(cards, collections, base_url),
        "metrics.md": render_metrics(metrics, base_url),
    }

    stats = {
        "databases": len(databases),
        "tables": len(tables),
        "collections": len(collections),
        "dashboards": len(dashboards),
        "cards": len(cards),
        "metrics": len(metrics),
    }

    files["index.md"] = render_index(stats, instance_name, base_url)

    for filename, content in files.items():
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Wrote {filename}")

    # Update registry
    now = datetime.now(timezone.utc).isoformat()
    registry = load_registry()
    existing = registry.get(instance_name, {})
    registry[instance_name] = {
        "url": base_url,
        "instance_name": instance_name,
        "output_path": os.path.relpath(out_dir, PROJECT_ROOT),
        "first_exported": existing.get("first_exported", now),
        "last_exported": now,
        "export_count": existing.get("export_count", 0) + 1,
        "stats": stats,
    }
    save_registry(registry)

    total = sum(stats.values())
    print(f"\nDone! Indexed {total} items across {len(stats)} categories.")
    print(f"Output: {os.path.relpath(out_dir, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
