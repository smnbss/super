#!/usr/bin/env python3
"""
Google Drive Folder -> Markdown INDEX file.

Unlike gdrive_to_md, this does NOT download or convert anything. It walks the
folder tree via the `gws` CLI and produces a single INDEX.md per source folder
listing every file with:
  - Title (as link to the Drive file)
  - Type
  - Modified date / owner / description (if set)

Output goes to src/gdrive_index/<drive name>/<sub/path>/INDEX.md, mirroring the
layout gdrive_to_md uses under src/gdrive.

Usage:
    gdrive_to_md_index <google_drive_folder_url>
    gdrive_to_md_index --list
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone

PROJECT_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "gdrive_index")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")

LIST_FIELDS = (
    "nextPageToken,files(id,name,mimeType,parents,webViewLink,description,"
    "modifiedTime,owners(displayName,emailAddress),shortcutDetails)"
)

MIME_LABEL = {
    "application/vnd.google-apps.folder": "Folder",
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.form": "Google Form",
    "application/vnd.google-apps.shortcut": "Shortcut",
    "application/vnd.google-apps.drawing": "Google Drawing",
    "application/vnd.google-apps.script": "Apps Script",
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "application/vnd.ms-excel": "Excel (legacy)",
    "application/vnd.ms-powerpoint": "PowerPoint (legacy)",
    "application/msword": "Word (legacy)",
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/gif": "GIF",
    "video/mp4": "MP4",
    "text/plain": "Text",
    "text/csv": "CSV",
}


def mime_label(m: str) -> str:
    return MIME_LABEL.get(m, m.rsplit("/", 1)[-1] if "/" in m else m)


# -- gws helpers -------------------------------------------------------------

def gws_json(*args, **params) -> dict:
    clean = {k: v for k, v in params.items() if v is not None}
    cmd = ["gws", "drive", *args, "--params", json.dumps(clean)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"gws {' '.join(args)} failed: {result.stderr.strip()}")
    out = result.stdout
    i = out.find("{")
    return json.loads(out[i:] if i >= 0 else out)


def list_children(parent_id: str) -> list[dict]:
    """List direct children of a folder or shared-drive root."""
    items: list[dict] = []
    page_token = None
    while True:
        params = {
            "q": f"'{parent_id}' in parents and trashed=false",
            "corpora": "allDrives",
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
            "pageSize": 1000,
            "fields": LIST_FIELDS,
        }
        if page_token:
            params["pageToken"] = page_token
        data = gws_json("files", "list", **params)
        items.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


def get_file_info(file_id: str) -> dict:
    return gws_json(
        "files", "get",
        fileId=file_id,
        fields="id,name,mimeType,parents,driveId,webViewLink",
        supportsAllDrives=True,
    )


def get_drive_name(drive_id: str) -> str:
    try:
        return gws_json("drives", "get", driveId=drive_id, fields="name").get("name", drive_id)
    except Exception:
        return drive_id


# -- Path reconstruction -----------------------------------------------------

def get_full_path(folder_id: str) -> tuple[list[str], str, dict]:
    """Return (path_parts up to and including folder_id, drive_name, folder_info)."""
    path_parts: list[str] = []
    drive_id: str | None = None
    drive_name: str | None = None
    root_info: dict | None = None
    current_id = folder_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        try:
            info = get_file_info(current_id)
        except Exception as e:
            print(f"  Warning: could not get info for {current_id}: {e}", file=sys.stderr)
            break
        if root_info is None:
            root_info = info
        if info.get("driveId") and not drive_id:
            drive_id = info["driveId"]
            drive_name = get_drive_name(drive_id)
        path_parts.insert(0, info.get("name", current_id))
        parents = info.get("parents") or []
        if not parents or parents[0] == drive_id:
            break
        current_id = parents[0]

    return path_parts, drive_name or "My Drive", root_info or {}


# -- URL parsing -------------------------------------------------------------

FOLDER_URL_PATTERNS = [
    re.compile(r"https?://drive\.google\.com/drive/folders/([\w-]+)"),
    re.compile(r"https?://drive\.google\.com/drive/u/\d+/folders/([\w-]+)"),
    re.compile(r"https?://drive\.google\.com/open\?id=([\w-]+)"),
]


def parse_gdrive_url(url: str) -> str:
    for pattern in FOLDER_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    # bare ID (no URL)
    if re.fullmatch(r"[\w-]{20,}", url):
        return url
    print(f"ERROR: Could not parse Google Drive URL: {url}", file=sys.stderr)
    sys.exit(1)


INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    return name[:200]


# -- BFS + grouping ----------------------------------------------------------

def bfs_all(root_id: str) -> list[dict]:
    """BFS all descendants of root_id. Root itself not included."""
    out: list[dict] = []
    queue = deque([root_id])
    visited = {root_id}
    while queue:
        cur = queue.popleft()
        try:
            children = list_children(cur)
        except Exception as e:
            print(f"  Warning: list_children({cur}) failed: {e}", file=sys.stderr)
            continue
        for c in children:
            out.append(c)
            if c["mimeType"] == "application/vnd.google-apps.folder" and c["id"] not in visited:
                visited.add(c["id"])
                queue.append(c["id"])
        print(f"  ... {cur}: +{len(children)} (total {len(out)})", file=sys.stderr)
    return out


def group_by_relative_path(files: list[dict], root_id: str):
    by_id = {f["id"]: f for f in files}
    folder_ids = {f["id"] for f in files if f["mimeType"] == "application/vnd.google-apps.folder"}

    def path_of(fid: str) -> list[str]:
        parts: list[str] = []
        seen = set()
        cur = by_id.get(fid)
        while cur and cur["id"] not in seen:
            seen.add(cur["id"])
            parents = cur.get("parents") or []
            if not parents:
                break
            pid = parents[0]
            if pid == root_id:
                break
            parent = by_id.get(pid)
            if parent is None or parent["id"] not in folder_ids:
                break
            parts.append(parent["name"])
            cur = parent
        return list(reversed(parts))

    grouped: dict[str, list[dict]] = {}
    for f in files:
        if f["mimeType"] == "application/vnd.google-apps.folder":
            continue
        p = path_of(f["id"])
        key = " / ".join(p) if p else "(root)"
        grouped.setdefault(key, []).append(f)

    all_paths: set[str] = {"(root)"}
    for fid in folder_ids:
        p = path_of(fid) + [by_id[fid]["name"]]
        all_paths.add(" / ".join(p))
    all_paths.update(grouped.keys())
    return grouped, sorted(all_paths)


def describe(f: dict) -> str:
    desc = (f.get("description") or "").strip()
    if desc:
        return " ".join(desc.split())
    bits = []
    modified = (f.get("modifiedTime") or "")[:10]
    if modified:
        bits.append(f"modified {modified}")
    owners = f.get("owners") or []
    if owners:
        bits.append(f"owner {owners[0].get('displayName')}")
    sd = f.get("shortcutDetails")
    if sd:
        target = MIME_LABEL.get(sd.get("targetMimeType", ""), sd.get("targetMimeType", "?"))
        bits.append(f"shortcut → {target}")
    bits.append("no drive description set")
    return "; ".join(bits)


def write_index(out_dir: str, root_id: str, root_info: dict,
                path_parts: list[str], drive_name: str,
                files: list[dict], grouped: dict, all_paths: list[str]):
    root_name = root_info.get("name", root_id)
    label = " / ".join(path_parts) if path_parts else root_name
    root_link = f"https://drive.google.com/drive/folders/{root_id}"
    total = sum(len(v) for v in grouped.values())
    folder_count = sum(1 for p in all_paths if p != "(root)")
    is_shared_drive = root_info.get("driveId") == root_id or root_info.get("mimeType") == "application/vnd.google-apps.folder" and not root_info.get("parents")

    lines: list[str] = []
    lines.append(f"# {label} — File Index")
    lines.append("")
    lines.append(f"- Root ID: `{root_id}`")
    lines.append(f"- Root link: {root_link}")
    lines.append(f"- Drive: {drive_name}")
    lines.append(f"- Files indexed: {total}")
    lines.append(f"- Folders: {folder_count}")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("Each entry: **[Title](link)** — Type; metadata. Paths are relative to the root above.")
    lines.append("")

    for path in all_paths:
        files_here = grouped.get(path, [])
        if not files_here and path != "(root)":
            lines.append(f"## {path}")
            lines.append("")
            lines.append("_(empty or folder-only)_")
            lines.append("")
            continue
        if not files_here:
            continue
        lines.append(f"## {path}")
        lines.append("")
        for f in sorted(files_here, key=lambda x: x["name"].lower()):
            title = f["name"].replace("|", "\\|").replace("\n", " ")
            link = f.get("webViewLink") or f"https://drive.google.com/open?id={f['id']}"
            kind = mime_label(f["mimeType"])
            desc = describe(f).replace("\n", " ")
            lines.append(f"- **[{title}]({link})** — {kind}; {desc}")
        lines.append("")

    os.makedirs(out_dir, exist_ok=True)
    index_path = os.path.join(out_dir, "INDEX.md")
    raw_path = os.path.join(out_dir, ".raw-listing.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    with open(raw_path, "w", encoding="utf-8") as fh:
        json.dump(files, fh, indent=2, ensure_ascii=False)
    return index_path, total, folder_count


# -- Registry ---------------------------------------------------------------

def load_registry() -> list[dict]:
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return []


def save_registry(entries: list[dict]):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)


def upsert_registry(url, folder_id, folder_name, output_path, file_count, folder_count):
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()
    rec = {
        "url": url,
        "folder_id": folder_id,
        "folder_name": folder_name,
        "output_path": output_path,
        "file_count": file_count,
        "folder_count": folder_count,
        "last_indexed": now,
    }
    existing = next((e for e in entries if e["folder_id"] == folder_id), None)
    if existing:
        rec["first_indexed"] = existing.get("first_indexed", now)
        rec["index_count"] = existing.get("index_count", 0) + 1
        existing.update(rec)
    else:
        rec["first_indexed"] = now
        rec["index_count"] = 1
        entries.append(rec)
    save_registry(entries)


def print_registry():
    entries = load_registry()
    if not entries:
        print("No folders indexed yet.")
        return
    print(f"{'Folder':<50} {'Files':>6}  {'Folders':>7}  {'Last Indexed':<20}  URL")
    print("-" * 130)
    for e in sorted(entries, key=lambda x: x.get("last_indexed", ""), reverse=True):
        last = e.get("last_indexed", "")[:19].replace("T", " ")
        print(
            f"{e['folder_name'][:50]:<50} "
            f"{e.get('file_count', 0):>6}  "
            f"{e.get('folder_count', 0):>7}  "
            f"{last:<20}  "
            f"{e.get('url', '')}"
        )


# -- Main -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build a markdown INDEX.md for a Google Drive folder (no file downloads)."
    )
    parser.add_argument("url", nargs="?", help="Google Drive folder URL (or bare ID)")
    parser.add_argument("--list", action="store_true", help="List previously indexed folders and exit")
    args = parser.parse_args()

    if args.list:
        print_registry()
        return
    if not args.url:
        parser.error("url is required (unless using --list)")

    folder_id = parse_gdrive_url(args.url)
    print(f"Fetching folder info for {folder_id}...", file=sys.stderr)
    path_parts, drive_name, root_info = get_full_path(folder_id)

    if root_info.get("mimeType") != "application/vnd.google-apps.folder":
        print(
            f"ERROR: target is not a folder (mimeType: {root_info.get('mimeType')})",
            file=sys.stderr,
        )
        sys.exit(1)

    # Output structure: <drive_name>/<folder_path>/INDEX.md. If the target IS
    # the shared drive root itself, just use the drive name as the output dir.
    is_drive_root = (
        root_info.get("driveId") and folder_id == root_info.get("driveId")
    )
    if is_drive_root:
        full_path_parts = [drive_name]
    elif drive_name and drive_name != "My Drive":
        full_path_parts = [drive_name] + path_parts
    else:
        full_path_parts = path_parts
    out_dir = os.path.join(OUTPUT_BASE, *[sanitize(p) for p in full_path_parts])

    print(f"Drive: {drive_name}", file=sys.stderr)
    print(f"Path: {'/'.join(path_parts)}", file=sys.stderr)
    print(f"Output: {os.path.relpath(out_dir, PROJECT_ROOT)}", file=sys.stderr)

    print("Walking folder tree...", file=sys.stderr)
    files = bfs_all(folder_id)
    grouped, all_paths = group_by_relative_path(files, folder_id)
    index_path, total, folder_count = write_index(
        out_dir, folder_id, root_info, path_parts, drive_name,
        files, grouped, all_paths,
    )
    upsert_registry(
        url=args.url,
        folder_id=folder_id,
        folder_name=root_info.get("name", folder_id),
        output_path=os.path.relpath(out_dir, PROJECT_ROOT),
        file_count=total,
        folder_count=folder_count,
    )
    print(f"\nDone. {total} files in {folder_count} folders.")
    print(f"Index: {os.path.relpath(index_path, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
