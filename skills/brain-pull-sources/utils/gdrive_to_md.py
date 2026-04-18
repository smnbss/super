#!/usr/bin/env python3
"""
Google Drive Folder -> Markdown exporter using gws CLI.

Uses the `gws` (googleworkspace-cli) for all Google Drive API calls.
Auth is handled by gws — no token management required.

Usage:
    python gdrive_to_md.py <google_drive_folder_url>
    python gdrive_to_md.py <url> --force
    python gdrive_to_md.py --list

Output is saved to:  src/gdrive/<full path>/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from markitdown import MarkItDown
from rewrite_links import build_link_map, rewrite_links


def _check_markitdown_extras() -> None:
    """markitdown 0.1.x split converters into [all] extras — a bare install
    imports cleanly but every docx/pdf/xlsx/pptx conversion fails at runtime
    with MissingDependencyException. Surface that loudly at startup."""
    missing = []
    for mod, fmt in (("mammoth", "docx"), ("pdfminer", "pdf"),
                     ("openpyxl", "xlsx"), ("pptx", "pptx")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(fmt)
    if missing:
        print(
            f"WARNING: markitdown is missing converters for: {', '.join(missing)}. "
            f"Office files will be saved as-is (no .md sibling). "
            f"Fix: uv tool install --force 'markitdown[all]'",
            file=sys.stderr,
        )


# -- Project root -------------------------------------------------------------

PROJECT_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "gdrive")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")


# -- gws helpers --------------------------------------------------------------

def _rel(path: str) -> str:
    """Return path relative to PROJECT_ROOT (required by gws for -o paths)."""
    return os.path.relpath(path, PROJECT_ROOT)


def gws_json(*args, **params) -> dict:
    """Run a gws drive command and return parsed JSON from stdout."""
    clean = {k: v for k, v in params.items() if v is not None}
    cmd = ["gws", "drive"] + list(args) + ["--params", json.dumps(clean)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"gws {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def gws_file(*args, output_path: str, **params) -> bool:
    """Run a gws drive command that writes output to a file.
    output_path must be absolute; gws receives it as relative to PROJECT_ROOT.
    """
    clean = {k: v for k, v in params.items() if v is not None}
    cmd = ["gws", "drive"] + list(args) + ["--params", json.dumps(clean), "-o", _rel(output_path)]
    result = subprocess.run(cmd, capture_output=True, cwd=PROJECT_ROOT)
    return result.returncode == 0


def gws_list_all(folder_id: str) -> list[dict]:
    """List all files in a folder, auto-paginating via --page-all."""
    cmd = [
        "gws", "drive", "files", "list",
        "--params", json.dumps({
            "q": f'"{folder_id}" in parents and trashed=false',
            "fields": "nextPageToken,files(id,name,mimeType,parents,driveId,modifiedTime,size)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
            "pageSize": 100,
        }),
        "--page-all", "--page-limit", "50",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"gws files list failed: {result.stderr.strip()}")

    files = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            page = json.loads(line)
            files.extend(page.get("files", []))
    return files


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


def get_existing_file_map(folder_id: str) -> dict[str, dict]:
    for entry in load_registry():
        if entry["folder_id"] == folder_id:
            return {f["file_id"]: f for f in entry.get("files", [])}
    return {}


def upsert_registry(url: str, folder_id: str, folder_name: str,
                    output_path: str, file_count: int, files: list[dict],
                    stats: dict):
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()

    files_manifest = [
        {
            "file_id": f.get("id"),
            "name": f.get("name", "Untitled"),
            "mime_type": f.get("mimeType", "unknown"),
            "parent_id": f.get("parent_id"),
            "modified_time": f.get("modifiedTime"),
            "file_path": f.get("_file_path", ""),
            "last_exported": now if f.get("_exported") else f.get("_last_exported"),
        }
        for f in files
    ]

    existing = next((e for e in entries if e["folder_id"] == folder_id), None)
    if existing:
        existing.update({
            "url": url,
            "folder_name": folder_name,
            "output_path": output_path,
            "file_count": file_count,
            "last_exported": now,
            "export_count": existing.get("export_count", 0) + 1,
            "files": files_manifest,
            "stats": stats,
        })
    else:
        entries.append({
            "url": url,
            "folder_id": folder_id,
            "folder_name": folder_name,
            "output_path": output_path,
            "file_count": file_count,
            "first_exported": now,
            "last_exported": now,
            "export_count": 1,
            "files": files_manifest,
            "stats": stats,
        })

    save_registry(entries)


def print_registry():
    entries = load_registry()
    if not entries:
        print("No folders exported yet.")
        return
    print(f"{'Folder Name':<50} {'Files':>5}  {'Exports':>7}  {'Last Exported':<20}  URL")
    print("-" * 130)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        stats = e.get("stats", {})
        file_info = (
            f"{stats.get('updated', 0)}/{stats.get('total', e['file_count'])} updated"
            if stats else str(e["file_count"])
        )
        print(f"{e['folder_name'][:50]:<50} {file_info:>12}  {e.get('export_count', 1):>7}  {last:<20}  {e['url']}")


# -- URL parsing --------------------------------------------------------------

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
    print(f"ERROR: Could not parse Google Drive URL: {url}", file=sys.stderr)
    sys.exit(1)


# -- Drive API ----------------------------------------------------------------

INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    return name[:200]


def get_folder_info(folder_id: str) -> dict:
    return gws_json(
        "files", "get",
        fileId=folder_id,
        fields="id,name,mimeType,parents,driveId",
        supportsAllDrives=True,
    )


def get_drive_name(drive_id: str) -> str:
    try:
        return gws_json("drives", "get", driveId=drive_id, fields="name").get("name", drive_id)
    except Exception:
        return drive_id


def get_full_path(folder_id: str) -> tuple[list[str], str]:
    """Build the full path from root to this folder. Returns (path_parts, drive_name)."""
    path_parts: list[str] = []
    drive_id: str | None = None
    drive_name: str | None = None
    current_id = folder_id
    visited: set[str] = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        try:
            info = get_folder_info(current_id)
            parents = info.get("parents", [])
            current_drive_id = info.get("driveId")

            if current_drive_id and not drive_id:
                drive_id = current_drive_id
                drive_name = get_drive_name(drive_id)

            path_parts.insert(0, info.get("name", current_id))

            if not parents or parents[0] == drive_id:
                break
            current_id = parents[0]
        except Exception as e:
            print(f"  Warning: Could not get info for {current_id}: {e}", file=sys.stderr)
            break

    return path_parts, drive_name or "My Drive"


def get_all_files_recursive(folder_id: str, parent_id: str | None = None,
                             path_prefix: str = "") -> list[dict]:
    """Recursively list all files in folder and subfolders."""
    all_files: list[dict] = []
    try:
        items = gws_list_all(folder_id)
    except Exception as e:
        print(f"  Warning: Could not list folder {folder_id}: {e}", file=sys.stderr)
        return []

    for item in items:
        item["parent_id"] = parent_id
        item["folder_id"] = folder_id
        item["path_prefix"] = path_prefix

        if item.get("mimeType") == "application/vnd.google-apps.folder":
            new_prefix = os.path.join(path_prefix, sanitize_filename(item["name"])) if path_prefix else sanitize_filename(item["name"])
            all_files.extend(get_all_files_recursive(item["id"], folder_id, new_prefix))
        else:
            all_files.append(item)

    return all_files


# -- File processing ----------------------------------------------------------

MAX_FILE_SIZE_MB = 50

# Google Workspace types: export as Office format, then convert to .md via markitdown
EXPORT_MIME_TYPES: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}

_markitdown = MarkItDown()
CONVERT_TIMEOUT_SECS = 120  # max seconds for markitdown conversion

# Inline script run via subprocess for timeout-safe conversion
_CONVERT_SCRIPT = """\
import sys, json
from markitdown import MarkItDown
try:
    r = MarkItDown().convert(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(r.text_content)
except Exception as e:
    print(json.dumps({"error": str(e)}), file=sys.stderr)
    sys.exit(1)
"""


def _convert_with_timeout(path: str, timeout: int = CONVERT_TIMEOUT_SECS):
    """Run markitdown in a subprocess with a hard timeout (kills C-extension hangs)."""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [sys.executable, "-c", _CONVERT_SCRIPT, path, tmp_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "markitdown conversion failed")
        with open(tmp_path, encoding="utf-8") as f:
            text = f.read()

        class _Result:
            text_content = text
        return _Result()
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"markitdown timed out after {timeout}s on {os.path.basename(path)}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# Other Google Workspace types to skip silently
SKIP_MIME_TYPES = {
    "application/vnd.google-apps.drawing",
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.script",
    "application/vnd.google-apps.shortcut",
}

EXT_MAP = {
    "text/plain": ".txt",
    "text/html": ".html",
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def process_file(file_info: dict, output_dir: str,
                 existing_files: dict[str, dict], force: bool = False) -> tuple[bool, str]:
    file_id = file_info["id"]
    name = file_info.get("name", "Untitled")
    mime_type = file_info.get("mimeType", "")
    path_prefix = file_info.get("path_prefix", "")
    modified_time = file_info.get("modifiedTime")
    size = int(file_info.get("size", 0)) if file_info.get("size") else 0

    # Strip extension from stem to avoid doubling (e.g. "file.xlsx" + ".xlsx")
    name_stem, _ = os.path.splitext(name)
    safe_name = sanitize_filename(name_stem)
    target_dir = os.path.join(output_dir, path_prefix) if path_prefix else output_dir
    os.makedirs(target_dir, exist_ok=True)

    # Incremental sync
    existing = existing_files.get(file_id)
    if not force and existing and existing.get("modified_time") == modified_time:
        file_info["_file_path"] = existing.get("file_path", "")
        file_info["_last_exported"] = existing.get("last_exported")
        return False, "unchanged"

    # Google Workspace docs → export as Office format, then convert to .md
    if mime_type in EXPORT_MIME_TYPES:
        export_mime, ext = EXPORT_MIME_TYPES[mime_type]
        office_path = os.path.join(target_dir, f"{safe_name}{ext}")
        md_path = os.path.join(target_dir, f"{safe_name}.md")
        if gws_file("files", "export", output_path=office_path,
                    fileId=file_id, mimeType=export_mime):
            try:
                result = _convert_with_timeout(office_path)
                with open(md_path, "w", encoding="utf-8") as fh:
                    fh.write(result.text_content)
                os.remove(office_path)
                file_info["_file_path"] = md_path
                file_info["_exported"] = True
                return True, "exported"
            except Exception as e:
                # markitdown failed — keep the Office file as fallback
                print(f"  WARN: markitdown failed for {os.path.basename(office_path)}: "
                      f"{str(e).splitlines()[0][:160]}", file=sys.stderr)
                file_info["_file_path"] = office_path
                file_info["_exported"] = True
                return True, f"exported_no_md({ext})"
        return False, "export_failed"

    # Skip other Google Workspace types
    if mime_type in SKIP_MIME_TYPES:
        return False, f"skipped_{mime_type.split('.')[-1]}"

    # Skip video
    if mime_type.startswith("video/"):
        return False, "skipped_video"

    # Size limit (already in file_info from list call)
    if size > MAX_FILE_SIZE_MB * 1024 * 1024:
        return False, f"skipped_too_large_{size // (1024 * 1024)}MB"

    # Binary download via files.get?alt=media
    # Use the already-split ext from name_stem/_  above; fall back to EXT_MAP
    _, raw_ext = os.path.splitext(name)
    ext = raw_ext or EXT_MAP.get(mime_type, "")
    output_path = os.path.join(target_dir, f"{safe_name}{ext}")
    if gws_file("files", "get", output_path=output_path,
                fileId=file_id, alt="media", supportsAllDrives=True):
        # Try converting to markdown via markitdown
        if ext.lower() in {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".html"}:
            md_path = os.path.join(target_dir, f"{safe_name}.md")
            try:
                result = _convert_with_timeout(output_path)
                with open(md_path, "w", encoding="utf-8") as fh:
                    fh.write(result.text_content)
                os.remove(output_path)
                file_info["_file_path"] = md_path
                file_info["_exported"] = True
                return True, "downloaded"
            except Exception as e:
                print(f"  WARN: markitdown failed for {os.path.basename(output_path)}: "
                      f"{str(e).splitlines()[0][:160]}", file=sys.stderr)
        file_info["_file_path"] = output_path
        file_info["_exported"] = True
        return True, "downloaded"
    return False, "download_failed"


# -- Main ---------------------------------------------------------------------

def main():
    _check_markitdown_extras()
    parser = argparse.ArgumentParser(
        description="Export a Google Drive folder to src/gdrive/ as Markdown files (uses gws for auth)."
    )
    parser.add_argument("url", nargs="?", help="Google Drive folder URL")
    parser.add_argument("--list", action="store_true",
                        help="List all previously exported folders and exit")
    parser.add_argument("--force", action="store_true",
                        help="Force re-export all files even if unchanged")
    args = parser.parse_args()

    if args.list:
        print_registry()
        return

    if not args.url:
        parser.error("url is required (unless using --list)")

    folder_id = parse_gdrive_url(args.url)

    print(f"Fetching folder info for {folder_id}...")
    try:
        folder_info = get_folder_info(folder_id)
        folder_name = folder_info.get("name", folder_id)
        if folder_info.get("mimeType") != "application/vnd.google-apps.folder":
            print(f"ERROR: Not a folder (mimeType: {folder_info.get('mimeType')})", file=sys.stderr)
            sys.exit(1)

        path_parts, drive_name = get_full_path(folder_id)
        # If the folder is the root of a shared drive, skip its name to avoid
        # an extra "Drive" level (e.g. "Org ExCo/Drive" → "Org ExCo")
        is_drive_root = (
            folder_info.get("driveId")
            and (folder_id == folder_info.get("driveId")
                 or not folder_info.get("parents")
                 or folder_info.get("parents", [None])[0] == folder_info.get("driveId"))
        )
        if is_drive_root:
            full_path_parts = [drive_name]
        elif drive_name and drive_name != "My Drive":
            full_path_parts = [drive_name] + path_parts
        else:
            full_path_parts = path_parts
        out = os.path.join(OUTPUT_BASE, *[sanitize_filename(p) for p in full_path_parts])

        print(f"Drive: {drive_name}")
        print(f"Path: {'/'.join(path_parts)}")
    except Exception as e:
        print(f"  Could not fetch folder info: {e}", file=sys.stderr)
        print("  Using folder ID as name.")
        folder_name = folder_id
        out = os.path.join(OUTPUT_BASE, sanitize_filename(folder_id))

    os.makedirs(out, exist_ok=True)
    print(f"Output folder: {os.path.relpath(out, PROJECT_ROOT)}")

    existing_files = get_existing_file_map(folder_id)
    if existing_files and not args.force:
        print(f"  Found {len(existing_files)} files in registry (comparing for changes)...")
    elif args.force:
        print("  Force mode: re-exporting all files")

    print("Listing files recursively...")
    all_files = get_all_files_recursive(folder_id)
    print(f"  Found {len(all_files)} files.")

    if not all_files:
        print("No files found. Exiting.")
        return

    new_count = sum(1 for f in all_files if f["id"] not in existing_files)
    updated_count = sum(
        1 for f in all_files
        if f["id"] in existing_files
        and existing_files[f["id"]].get("modified_time") != f.get("modifiedTime")
    )
    if not args.force:
        print(f"  New: {new_count}, Updated: {updated_count}, Unchanged: {len(all_files) - new_count - updated_count}")

    print("Downloading and converting files...")
    stats = {"total": len(all_files), "new": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    success_count = 0

    for i, file_info in enumerate(all_files):
        name = file_info.get("name", "Untitled")
        mime_type = file_info.get("mimeType", "")
        short_mime = mime_type.split(".")[-1] if "." in mime_type else mime_type[:20]

        success, msg = process_file(file_info, out, existing_files, args.force)
        if success:
            success_count += 1
            status = "✓"
            stats["new" if not existing_files.get(file_info["id"]) else "updated"] += 1
        else:
            status = f"✗ ({msg})"
            stats["unchanged" if msg == "unchanged" else "skipped"] += 1

        print(f"  [{i+1}/{len(all_files)}] {status} {name[:45]:<45} ({short_mime})", flush=True)

    # Rewrite links in exported markdown files
    link_map = build_link_map()
    for f in all_files:
        fid, fp = f.get("id"), f.get("_file_path")
        if fid and fp:
            link_map[f"gdrive:{fid}"] = os.path.relpath(fp, PROJECT_ROOT) if os.path.isabs(fp) else fp

    rewritten = 0
    for f in all_files:
        fp = f.get("_file_path")
        if not fp or not f.get("_exported") or not fp.endswith(".md"):
            continue
        abs_path = fp if os.path.isabs(fp) else os.path.join(PROJECT_ROOT, fp)
        try:
            with open(abs_path, encoding="utf-8") as fh:
                content = fh.read()
            new_content = rewrite_links(content, os.path.relpath(abs_path, PROJECT_ROOT), link_map)
            if new_content != content:
                with open(abs_path, "w", encoding="utf-8") as fh:
                    fh.write(new_content)
                rewritten += 1
        except Exception:
            pass
    if rewritten:
        print(f"  Rewrote links in {rewritten} markdown file(s).")

    upsert_registry(
        url=args.url,
        folder_id=folder_id,
        folder_name=folder_name,
        output_path=os.path.relpath(out, PROJECT_ROOT),
        file_count=success_count,
        files=all_files,
        stats=stats,
    )

    print(f"\nDone! {stats['new']} new, {stats['updated']} updated, {stats['unchanged']} unchanged, {stats['skipped']} skipped")
    print(f"Output: {os.path.relpath(out, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
