#!/usr/bin/env python3
from __future__ import annotations
"""
WorkFlowy outline -> Markdown exporter with incremental, size-balanced sync.

WorkFlowy (workflowy.com) exposes a single bulk endpoint,
`GET /api/v1/nodes-export`, that returns the *entire* account as a flat list of
nodes in one request (rate-limited to ~1/min). We fetch it once, rebuild the
tree via `parent_id`, order siblings by `priority`, and render the outline to
Markdown under src/workflowly/.

Layout — size-threshold split:
    A node fans out into a FOLDER only when its subtree exceeds --max-nodes
    (default 200); otherwise its whole subtree is inlined into a single <name>.md
    as nested Markdown bullets. So a small branch (e.g. a 1:1 week) stays one
    file while a big one (a whole person's history) becomes a folder. Optionally
    --min-folder-depth N forces the top N levels to folders even when small (but
    only where a node has a non-leaf child, to avoid piles of one-line stubs);
    the default 0 leaves the split purely size-driven.

Incremental:
    src/workflowly/.registry.json records, per output file, the max `modifiedAt`
    across the nodes that render into it. A file is rewritten only when its
    subtree changed (or --force). Output files whose source nodes vanished from
    the export are pruned, and emptied directories are removed.

Usage:
    python workflowly_to_md.py [--max-nodes N] [--min-folder-depth N] [--force]
                               [--no-completed] [--token TOKEN] [--list] [--verbose]

Environment (first match wins):
    WORKFLOWY_API_KEY / WORKFLOWLY_API_KEY / workflowy   -- API bearer token
    WORKFLOWY_BASE_URL                                   -- default https://workflowy.com

Output: src/workflowly/
"""

import argparse
import html
import json
import os
import re
import subprocess as _sp
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone


# -- Project root (use git to find repo root, not relative path) --------------

PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip() or os.getcwd()


# -- Load .env from project root ----------------------------------------------

def load_dotenv():
    """Load key=value pairs from .env.local in the project root."""
    env_path = os.path.join(PROJECT_ROOT, ".env.local")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


load_dotenv()
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "workflowly")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")

DEFAULT_BASE_URL = os.environ.get("WORKFLOWY_BASE_URL", "https://workflowy.com").rstrip("/")
# A curl-style UA keeps us off any default-urllib UA blocklist (mirrors outline_to_md).
USER_AGENT = "curl/8.7.1"


def resolve_token(cli_token: str) -> str:
    """First non-empty of --token, then the accepted env var spellings."""
    return (
        cli_token
        or os.environ.get("WORKFLOWY_API_KEY")
        or os.environ.get("WORKFLOWLY_API_KEY")
        or os.environ.get("workflowy")
        or os.environ.get("WORKFLOWY")
        or ""
    )


# -- API ----------------------------------------------------------------------

def api_get(token: str, endpoint: str, retries: int = 3) -> dict:
    """GET a WorkFlowy API endpoint, retrying on 429 (export is ~1 req/min)."""
    url = f"{DEFAULT_BASE_URL}/api/v1/{endpoint}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"), strict=False)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 65  # rate limit is per-minute
                print(f"  Rate limited (429). Waiting {wait}s before retry "
                      f"{attempt + 2}/{retries}...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_nodes(token: str) -> list[dict]:
    """Fetch every node in the account via the bulk export endpoint."""
    data = api_get(token, "nodes-export")
    if isinstance(data, list):
        return data
    return data.get("nodes") or data.get("data") or []


# -- Tree ---------------------------------------------------------------------

def build_tree(nodes: list[dict]):
    """Return (by_id, children, roots, size) with siblings ordered by priority."""
    by_id = {n["id"]: n for n in nodes}
    children: dict[str, list[dict]] = defaultdict(list)
    roots: list[dict] = []
    for n in nodes:
        pid = n.get("parent_id")
        if pid and pid in by_id:
            children[pid].append(n)
        else:
            roots.append(n)
    for kid_list in children.values():
        kid_list.sort(key=lambda x: x.get("priority", 0))
    roots.sort(key=lambda x: x.get("priority", 0))

    size: dict[str, int] = {}

    def subtree_size(nid: str) -> int:
        if nid in size:
            return size[nid]
        total = 1
        for c in children.get(nid, []):
            total += subtree_size(c["id"])
        size[nid] = total
        return total

    for r in roots:
        subtree_size(r["id"])
    return by_id, children, roots, size


# -- Text cleaning ------------------------------------------------------------

_A_TAG = re.compile(r'<a\b[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def html_to_md(s: str | None) -> str:
    """Convert WorkFlowy inline HTML to Markdown, stripping unknown tags."""
    if not s:
        return ""
    s = _A_TAG.sub(r"[\2](\1)", s)
    s = re.sub(r"</?(?:b|strong)>", "**", s, flags=re.I)
    s = re.sub(r"</?(?:i|em)>", "_", s, flags=re.I)
    s = re.sub(r"</?(?:s|strike|del)>", "~~", s, flags=re.I)
    s = re.sub(r"</?code>", "`", s, flags=re.I)
    s = _TAG.sub("", s)          # drop spans (incl. color tags) and any leftover markup
    s = html.unescape(s)
    return s.strip()


def plain_text(s: str | None) -> str:
    """Strip all HTML/markup to plain text (used for file/folder names)."""
    if not s:
        return ""
    return html.unescape(_TAG.sub("", s)).strip()


INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return (name or "untitled")[:120]


# -- Node helpers -------------------------------------------------------------

def is_completed(node: dict) -> bool:
    return bool(node.get("completed") or node.get("completedAt"))


def compute_produces(children: dict, roots: list[dict], include_completed: bool) -> dict[str, bool]:
    """Map node id -> whether it renders anything (a name, a note, or a producing
    descendant). Nodes that produce nothing are pure noise and get skipped, which
    also prunes deep all-empty subtrees, not just bare leaves."""
    prod: dict[str, bool] = {}

    def visit(node: dict) -> bool:
        nid = node["id"]
        if not include_completed and is_completed(node):
            prod[nid] = False
            return False
        kids_produce = any([visit(c) for c in children.get(nid, [])])  # list: visit ALL kids
        has = bool(plain_text(node.get("name")) or (node.get("note") or "").strip() or kids_produce)
        prod[nid] = has
        return has

    for r in roots:
        visit(r)
    return prod


def node_marker(node: dict) -> str:
    """Markdown list marker prefix: completed -> [x], todo -> [ ], else ''."""
    if is_completed(node):
        return "[x] "
    if (node.get("data") or {}).get("layoutMode") == "todo":
        return "[ ] "
    return ""


# -- Rendering ----------------------------------------------------------------

class Renderer:
    def __init__(self, children: dict, prod: dict[str, bool]):
        self.children = children
        self.prod = prod

    def _skip(self, node: dict) -> bool:
        return not self.prod.get(node["id"], False)

    @staticmethod
    def _note_lines(node: dict) -> list[str]:
        """Cleaned note as a list of lines (notes also carry inline HTML)."""
        note = (node.get("note") or "").strip()
        if not note:
            return []
        return [html_to_md(ln) for ln in note.splitlines()]

    def render_bullet(self, node: dict, depth: int, out: list[str]):
        if self._skip(node):
            return
        indent = "  " * depth
        text = html_to_md(node.get("name")) or " "
        layout = (node.get("data") or {}).get("layoutMode")
        if layout == "code-block":
            out.append(f"{indent}- ```")
            for ln in text.splitlines() or [""]:
                out.append(f"{indent}  {ln}")
            out.append(f"{indent}  ```")
        else:
            prefix = "> " if layout == "quote-block" else ""
            out.append(f"{indent}- {node_marker(node)}{prefix}{text}")
        for ln in self._note_lines(node):
            out.append(f"{indent}  {ln}")
        for c in self.children.get(node["id"], []):
            self.render_bullet(c, depth + 1, out)

    def render_file(self, node: dict) -> str:
        """A file = node's own name as H1 + its whole subtree as nested bullets."""
        out: list[str] = []
        title = html_to_md(node.get("name")) or "untitled"
        out.append(f"# {title}")
        note_lines = self._note_lines(node)
        if note_lines:
            out.append("")
            out.extend(note_lines)
        out.append("")
        for c in self.children.get(node["id"], []):
            self.render_bullet(c, 0, out)
        return "\n".join(out).rstrip() + "\n"

    def render_index(self, node: dict) -> str:
        """_index.md for a folder node that carries its own note."""
        out = [f"# {html_to_md(node.get('name')) or 'untitled'}", ""]
        out.extend(self._note_lines(node))
        return "\n".join(out).rstrip() + "\n"


# -- Subtree modified timestamp -----------------------------------------------

def subtree_max_modified(node: dict, children: dict) -> int:
    """Latest modifiedAt across a node and everything that renders inside it."""
    best = node.get("modifiedAt") or 0
    for c in children.get(node["id"], []):
        best = max(best, subtree_max_modified(c, children))
    return best


# -- Planning the output tree -------------------------------------------------

def _claim_name(base: str, dir_used: set[str], node_id: str, ext: str = "") -> str:
    """Reserve a collision-free entry name within a directory (id suffix on clash)."""
    name = f"{base}{ext}"
    if name.lower() in dir_used:
        name = f"{base}-{node_id[:8]}{ext}"
    dir_used.add(name.lower())
    return name


def plan_outputs(roots, children, size, prod, max_nodes, min_folder_depth):
    """Walk the tree and decide every output file.

    Returns a list of plan entries:
        {kind: file|index, node_id, name, rel_path, max_modified}
    in stable (depth-first, priority) order. `rel_path` is relative to
    PROJECT_ROOT. Sibling name collisions get an id suffix.

    A node with children becomes a FOLDER when its subtree exceeds `max_nodes`,
    OR it is shallower than `min_folder_depth` AND has at least one non-leaf
    child (so forcing a folder yields real sub-structure, not a pile of
    one-line stub files). Otherwise its whole subtree is inlined into one file —
    so a small shallow node like a week with only leaf items stays a single file.
    """
    plan: list[dict] = []

    def has_nonleaf_child(node: dict) -> bool:
        """True if any rendered child of `node` itself has a rendered child."""
        for c in children.get(node["id"], []):
            if prod.get(c["id"]) and any(prod.get(g["id"]) for g in children.get(c["id"], [])):
                return True
        return False

    def is_folder(node: dict, depth: int) -> bool:
        if not children.get(node["id"]):
            return False
        if size[node["id"]] > max_nodes:
            return True
        return depth < min_folder_depth and has_nonleaf_child(node)

    def add(kind: str, node: dict, rel_path: str, max_modified: int):
        plan.append({
            "kind": kind,
            "node_id": node["id"],
            "name": plain_text(node.get("name")),
            "rel_path": rel_path,
            "max_modified": max_modified,
        })

    def emit(node: dict, cur_dir: str, used: dict[str, set], depth: int):
        if not prod.get(node["id"], False):
            return
        base = sanitize_filename(plain_text(node.get("name")))
        dir_used = used.setdefault(cur_dir, set())

        if is_folder(node, depth):
            node_dir = os.path.join(cur_dir, _claim_name(base, dir_used, node["id"]))
            if (node.get("note") or "").strip():
                rel = os.path.relpath(os.path.join(node_dir, "_index.md"), PROJECT_ROOT)
                add("index", node, rel, node.get("modifiedAt") or 0)
            for c in children.get(node["id"], []):
                emit(c, node_dir, used, depth + 1)
        else:
            rel = os.path.relpath(
                os.path.join(cur_dir, _claim_name(base, dir_used, node["id"], ".md")),
                PROJECT_ROOT,
            )
            add("file", node, rel, subtree_max_modified(node, children))

    used: dict[str, set] = {}
    for r in roots:
        emit(r, OUTPUT_BASE, used, 0)
    return plan


# -- Registry -----------------------------------------------------------------

def load_registry() -> dict:
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(reg: dict):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2, ensure_ascii=False)


def print_registry(verbose: bool = False):
    reg = load_registry()
    files = reg.get("files", {})
    if not files:
        print("No WorkFlowy export yet.")
        return
    print(f"Last export:  {reg.get('last_export', '?')}")
    print(f"Exports:      {reg.get('export_count', 1)}")
    print(f"Nodes:        {reg.get('node_count', '?')}")
    print(f"Output files: {len(files)}")
    stats = reg.get("stats", {})
    if stats:
        print(f"Last run:     {stats.get('new', 0)} new, {stats.get('updated', 0)} updated, "
              f"{stats.get('unchanged', 0)} unchanged, {stats.get('pruned', 0)} pruned")
    if verbose:
        print("-" * 80)
        for path in sorted(files):
            print(f"  {path}")


# -- Pruning ------------------------------------------------------------------

def prune_stale(expected_abs: set[str]):
    """Delete any .md under OUTPUT_BASE not in the expected set, then drop empty dirs."""
    pruned = 0
    if not os.path.isdir(OUTPUT_BASE):
        return 0
    for dirpath, _dirnames, filenames in os.walk(OUTPUT_BASE):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            ap = os.path.join(dirpath, fn)
            if ap not in expected_abs:
                os.remove(ap)
                pruned += 1
    # Remove now-empty directories (deepest first).
    for dirpath, _dirnames, _filenames in sorted(os.walk(OUTPUT_BASE), reverse=True):
        if dirpath == OUTPUT_BASE:
            continue
        if not os.listdir(dirpath):
            os.rmdir(dirpath)
    return pruned


# -- Writing ------------------------------------------------------------------

def select_to_write(plan: list[dict], prev: dict, force: bool) -> list[dict]:
    """Plan entries that are new, changed, or missing on disk (all, if --force)."""
    out = []
    for p in plan:
        rec = prev.get(p["rel_path"])
        if (force or rec is None
                or rec.get("max_modified") != p["max_modified"]
                or not os.path.isfile(os.path.join(PROJECT_ROOT, p["rel_path"]))):
            out.append(p)
    return out


def write_outputs(to_write: list[dict], by_id: dict, renderer: "Renderer", prev: dict) -> dict:
    """Render and write each selected entry; return {'new', 'updated'} counts."""
    counts = {"new": 0, "updated": 0}
    total = len(to_write)
    for i, p in enumerate(to_write):
        print(f"  [{i + 1}/{total}] {p['name'][:60]}...", end="\r")
        node = by_id[p["node_id"]]
        content = renderer.render_index(node) if p["kind"] == "index" else renderer.render_file(node)
        abs_path = os.path.join(PROJECT_ROOT, p["rel_path"])
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        counts["updated" if p["rel_path"] in prev else "new"] += 1
    if total:
        print(f"  [{total}/{total}] Done.{' ' * 40}")
    return counts


# -- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export the entire WorkFlowy account to src/workflowly/ as Markdown."
    )
    parser.add_argument("--max-nodes", type=int, default=200,
                        help="Subtree size above which a node fans out into a folder (default 200).")
    parser.add_argument("--min-folder-depth", type=int, default=0,
                        help="Top levels forced to folders even when small (default 0 = pure "
                             "size threshold; a shallow node still needs a non-leaf child to be forced).")
    parser.add_argument("--token", default="",
                        help="WorkFlowy API token (else WORKFLOWY_API_KEY / workflowy env).")
    parser.add_argument("--force", action="store_true",
                        help="Rewrite every file even if unchanged.")
    parser.add_argument("--no-completed", action="store_true",
                        help="Skip completed (checked-off) nodes and their subtrees.")
    parser.add_argument("--list", action="store_true",
                        help="Print the export registry and exit.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="With --list, print every output file path.")
    args = parser.parse_args()

    if args.list:
        print_registry(verbose=args.verbose)
        return

    token = resolve_token(args.token)
    if not token:
        print("ERROR: WorkFlowy API token required. Set WORKFLOWY_API_KEY (or "
              "WORKFLOWLY_API_KEY / workflowy) in .env.local, or use --token.", file=sys.stderr)
        sys.exit(1)

    include_completed = not args.no_completed

    print("Fetching WorkFlowy export (this endpoint is rate-limited ~1/min)...")
    try:
        nodes = fetch_nodes(token)
    except urllib.error.HTTPError as e:
        print(f"ERROR: export failed: HTTP {e.code} {e.read().decode('utf-8')[:300]}", file=sys.stderr)
        sys.exit(1)
    if not nodes:
        print("No nodes returned. Exiting.")
        return
    print(f"  {len(nodes)} nodes.")

    by_id, children, roots, size = build_tree(nodes)
    prod = compute_produces(children, roots, include_completed)
    plan = plan_outputs(roots, children, size, prod, args.max_nodes, args.min_folder_depth)
    print(f"  Planning {len(plan)} output files "
          f"(max-nodes={args.max_nodes}, min-folder-depth={args.min_folder_depth}).")

    registry = load_registry()
    prev = registry.get("files", {})
    renderer = Renderer(children, prod)

    to_write = select_to_write(plan, prev, args.force)
    print(f"  {len(to_write)} to write, {len(plan) - len(to_write)} unchanged.")
    counts = write_outputs(to_write, by_id, renderer, prev)

    expected_abs = {os.path.join(PROJECT_ROOT, p["rel_path"]) for p in plan}
    stats = {
        "new": counts["new"],
        "updated": counts["updated"],
        "unchanged": len(plan) - len(to_write),
        "pruned": prune_stale(expected_abs),
    }

    save_registry({
        "source": "workflowy",
        "base_url": DEFAULT_BASE_URL,
        "last_export": datetime.now(timezone.utc).isoformat(),
        "export_count": registry.get("export_count", 0) + 1,
        "node_count": len(nodes),
        "max_nodes": args.max_nodes,
        "min_folder_depth": args.min_folder_depth,
        "include_completed": include_completed,
        "stats": stats,
        "files": {p["rel_path"]: {"node_id": p["node_id"], "max_modified": p["max_modified"]}
                  for p in plan},
    })

    print(f"\nDone! {stats['new']} new, {stats['updated']} updated, "
          f"{stats['unchanged']} unchanged, {stats['pruned']} pruned "
          f"in {os.path.relpath(OUTPUT_BASE, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
