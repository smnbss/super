#!/usr/bin/env python3
"""
Google Drive folder -> Markdown + per-folder INDEX.md, incremental by default.

Unifies the two previous tools (gdrive_to_md, gdrive_to_md_index) into one.

Two modes, selected per-invocation:

  --mode full   Download & convert every non-skipped file to .md via markitdown,
                stamp YAML frontmatter carrying gdrive_id / gdrive_url so the
                brain's memory rebuild can cite the original Drive file. Also
                generates a per-folder INDEX.md linking to both the local .md
                and the original Drive file.

  --mode index  Skip all downloads. Write only per-folder INDEX.md with links
                to the original Drive files. Use for large / low-signal folders
                where an LLM-browsable catalog is enough.

Output (both modes): src/gdrive/<Drive Name>/<sub/path>/
  - INDEX.md in every folder
  - (full mode) converted .md files sitting next to their INDEX.md
  - .cache.json at the target root — folder tree + per-file state
  - .registry.json at src/gdrive/ — lists every indexed/exported target

Usage:
    drive_to_md <google_drive_folder_url>                   # default --mode full
    drive_to_md <url> --mode index                          # index only
    drive_to_md <url> --full-rebuild                        # ignore cache, re-pull tree
    drive_to_md <url> --force                               # re-download all files (full mode)
    drive_to_md --list                                      # show all exported roots
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import deque
from datetime import datetime, timezone
from urllib.parse import quote

from rewrite_links import build_link_map, rewrite_links

# markitdown is optional at import time — only strictly required in full mode
try:
    from markitdown import MarkItDown  # noqa: F401
    _HAS_MARKITDOWN = True
except ImportError:
    _HAS_MARKITDOWN = False


# -- Paths --------------------------------------------------------------------

PROJECT_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "gdrive")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")
CACHE_NAME = ".cache.json"
INDEX_NAME = "INDEX.md"


def _rel(path: str) -> str:
    return os.path.relpath(path, PROJECT_ROOT)


# -- markitdown sanity --------------------------------------------------------

def _check_markitdown_extras() -> None:
    """markitdown 0.1.x split converters into [all] extras — a bare install
    imports cleanly but every docx/pdf/xlsx/pptx conversion fails at runtime
    with MissingDependencyException. Surface that loudly at startup."""
    if not _HAS_MARKITDOWN:
        print(
            "WARNING: markitdown not installed. Full-mode file conversion will fail. "
            "Install via: uv tool install 'markitdown[all]'",
            file=sys.stderr,
        )
        return
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


# -- gws helpers --------------------------------------------------------------

FILE_FIELDS = (
    "id,name,mimeType,parents,webViewLink,description,modifiedTime,size,"
    "owners(displayName,emailAddress),shortcutDetails,driveId,trashed"
)
LIST_FIELDS = f"nextPageToken,files({FILE_FIELDS})"

FOLDER_MIME = "application/vnd.google-apps.folder"


def gws_json(*args, **params) -> dict:
    clean = {k: v for k, v in params.items() if v is not None}
    cmd = ["gws", "drive", *args, "--params", json.dumps(clean)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"gws {' '.join(args)} failed: {result.stderr.strip()}")
    # Tolerate gws' occasional leading prose line before the JSON payload.
    out = result.stdout
    i = out.find("{")
    return json.loads(out[i:] if i >= 0 else out)


def gws_file(*args, output_path: str, **params) -> bool:
    """Run a gws drive command that writes output to a file.
    output_path must be absolute; gws receives it as relative to PROJECT_ROOT."""
    clean = {k: v for k, v in params.items() if v is not None}
    cmd = ["gws", "drive", *args,
           "--params", json.dumps(clean), "-o", _rel(output_path)]
    result = subprocess.run(cmd, capture_output=True, cwd=PROJECT_ROOT)
    return result.returncode == 0


def list_children(parent_id: str) -> list[dict]:
    """Direct children of a folder / shared-drive root (all pages)."""
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


def query_changed(since_iso: str, drive_id: str | None) -> list[dict]:
    items: list[dict] = []
    page_token = None
    while True:
        params = {
            "q": f"modifiedTime > '{since_iso}' and trashed=false",
            "pageSize": 1000,
            "fields": LIST_FIELDS,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            params["driveId"] = drive_id
            params["corpora"] = "drive"
        else:
            params["corpora"] = "user"
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
        fileId=file_id, fields=FILE_FIELDS, supportsAllDrives=True,
    )


def get_drive_name(drive_id: str) -> str:
    try:
        return gws_json("drives", "get", driveId=drive_id, fields="name").get("name", drive_id)
    except Exception:
        return drive_id


# -- URL parsing / sanitize ---------------------------------------------------

FOLDER_URL_PATTERNS = [
    re.compile(r"https?://drive\.google\.com/drive/folders/([\w-]+)"),
    re.compile(r"https?://drive\.google\.com/drive/u/\d+/folders/([\w-]+)"),
    re.compile(r"https?://drive\.google\.com/open\?id=([\w-]+)"),
]


def parse_gdrive_url(url: str) -> str:
    for p in FOLDER_URL_PATTERNS:
        m = p.search(url)
        if m:
            return m.group(1)
    if re.fullmatch(r"[\w-]{20,}", url):
        return url
    print(f"ERROR: Could not parse Google Drive URL: {url}", file=sys.stderr)
    sys.exit(1)


INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    return name[:200] or "_"


# -- Path helpers -------------------------------------------------------------

def resolve_target(folder_id: str) -> tuple[list[str], str, dict, bool]:
    """Return (path_parts_to_target, drive_name, root_info, is_drive_root)."""
    root_info = get_file_info(folder_id)
    drive_id = root_info.get("driveId")
    drive_name = get_drive_name(drive_id) if drive_id else "My Drive"
    is_drive_root = bool(drive_id) and folder_id == drive_id

    path_parts: list[str] = []
    current_id = folder_id
    visited: set[str] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        try:
            info = get_file_info(current_id) if current_id != folder_id else root_info
        except Exception as e:
            print(f"  Warning: get_file_info({current_id}) failed: {e}", file=sys.stderr)
            break
        path_parts.insert(0, info.get("name", current_id))
        parents = info.get("parents") or []
        if not parents or parents[0] == drive_id:
            break
        current_id = parents[0]

    return path_parts, drive_name, root_info, is_drive_root


def compute_out_dir(drive_name: str, path_parts: list[str], is_drive_root: bool) -> str:
    if is_drive_root:
        full = [drive_name]
    elif drive_name and drive_name != "My Drive":
        full = [drive_name] + path_parts
    else:
        full = path_parts
    return os.path.join(OUTPUT_BASE, *[sanitize(p) for p in full])


# -- Cache + Registry ---------------------------------------------------------

def cache_path(out_dir: str) -> str:
    return os.path.join(out_dir, CACHE_NAME)


def load_cache(out_dir: str) -> dict | None:
    p = cache_path(out_dir)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def save_cache(out_dir: str, cache: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(cache_path(out_dir), "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, ensure_ascii=False)


def load_registry() -> list[dict]:
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return []


def save_registry(entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)


def upsert_registry(*, url: str, folder_id: str, folder_name: str, output_path: str,
                    mode: str, file_count: int, folder_count: int, stats: dict,
                    files: list[dict] | None = None) -> None:
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()
    existing = next((e for e in entries if e["folder_id"] == folder_id), None)
    rec = {
        "url": url,
        "folder_id": folder_id,
        "folder_name": folder_name,
        "output_path": output_path,
        "mode": mode,
        "file_count": file_count,
        "folder_count": folder_count,
        "last_synced": now,
        "stats": stats,
        # rewrite_links.py reads this — give it {file_id, file_path} for every
        # converted file so other sources can turn gdrive URLs into local links.
        "files": files or [],
    }
    if existing:
        rec["first_synced"] = existing.get("first_synced", existing.get("first_exported", existing.get("first_indexed", now)))
        rec["sync_count"] = existing.get("sync_count", existing.get("export_count", existing.get("index_count", 0))) + 1
        existing.clear()
        existing.update(rec)
    else:
        rec["first_synced"] = now
        rec["sync_count"] = 1
        entries.append(rec)
    save_registry(entries)


def print_registry() -> None:
    entries = load_registry()
    if not entries:
        print("No folders exported yet.")
        return
    print(f"{'Folder':<50} {'Mode':<6} {'Files':>6}  {'Folders':>7}  {'Last Synced':<20}  URL")
    print("-" * 140)
    for e in sorted(entries, key=lambda x: x.get("last_synced", ""), reverse=True):
        last = e.get("last_synced", "")[:19].replace("T", " ")
        print(
            f"{e['folder_name'][:50]:<50} "
            f"{e.get('mode', '?'):<6} "
            f"{e.get('file_count', 0):>6}  "
            f"{e.get('folder_count', 0):>7}  "
            f"{last:<20}  "
            f"{e.get('url', '')}"
        )


# -- Content conversion (full mode) -------------------------------------------

MAX_FILE_SIZE_MB = 50
CONVERT_TIMEOUT_SECS = 120

EXPORT_MIME_TYPES: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}

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


def _convert_with_timeout(path: str, timeout: int = CONVERT_TIMEOUT_SECS) -> str:
    """Run markitdown in a subprocess with a hard timeout (kills C-extension hangs).
    Returns the converted text."""
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
            return f.read()
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"markitdown timed out after {timeout}s on {os.path.basename(path)}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _yaml_escape(s: str) -> str:
    """Single-line YAML string — quote only if needed."""
    s = str(s).replace("\n", " ").strip()
    if not s:
        return '""'
    if any(c in s for c in ":#'\"[]{}&*!|>%@`,") or s[0] in "-? ":
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def stamp_frontmatter(md_text: str, meta: dict) -> str:
    """Prepend YAML frontmatter that carries the original Drive coordinates so
    the brain can cite the source URL instead of the local file."""
    lines = ["---"]
    for k in ("gdrive_id", "gdrive_url", "gdrive_name", "gdrive_mime",
             "gdrive_modified", "gdrive_path"):
        if k in meta and meta[k] is not None:
            lines.append(f"{k}: {_yaml_escape(meta[k])}")
    lines.append("---")
    lines.append("")
    # markitdown output is plain markdown, no existing frontmatter; prepend.
    return "\n".join(lines) + "\n" + md_text


def _build_meta(file_info: dict, drive_rel_path: str) -> dict:
    fid = file_info.get("id", "")
    return {
        "gdrive_id": fid,
        "gdrive_url": file_info.get("webViewLink") or f"https://drive.google.com/open?id={fid}",
        "gdrive_name": file_info.get("name", ""),
        "gdrive_mime": file_info.get("mimeType", ""),
        "gdrive_modified": file_info.get("modifiedTime", ""),
        "gdrive_path": drive_rel_path,
    }


def download_and_convert(file_info: dict, target_dir: str,
                         drive_rel_path: str) -> tuple[str | None, str]:
    """Download + convert a single file. Returns (local_md_path_or_None, status).
    status is one of: converted, kept_binary, skipped_{reason}, failed."""
    file_id = file_info["id"]
    name = file_info.get("name", "Untitled")
    mime_type = file_info.get("mimeType", "")
    size = int(file_info.get("size", 0)) if file_info.get("size") else 0

    name_stem, raw_ext = os.path.splitext(name)
    safe_name = sanitize(name_stem)
    os.makedirs(target_dir, exist_ok=True)

    # Google Workspace docs → export to Office format then convert to .md
    if mime_type in EXPORT_MIME_TYPES:
        export_mime, ext = EXPORT_MIME_TYPES[mime_type]
        office_path = os.path.join(target_dir, f"{safe_name}{ext}")
        md_path = os.path.join(target_dir, f"{safe_name}.md")
        if not gws_file("files", "export", output_path=office_path,
                       fileId=file_id, mimeType=export_mime):
            return None, "failed"
        try:
            text = _convert_with_timeout(office_path)
            meta = _build_meta(file_info, drive_rel_path)
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(stamp_frontmatter(text, meta))
            os.remove(office_path)
            return md_path, "converted"
        except Exception as e:
            # markitdown failed — keep the Office file as fallback, but we can
            # still record the mapping via a stub .md with frontmatter only.
            print(f"  WARN: markitdown failed for {os.path.basename(office_path)}: "
                  f"{str(e).splitlines()[0][:160]}", file=sys.stderr)
            meta = _build_meta(file_info, drive_rel_path)
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(stamp_frontmatter(
                    f"> markitdown could not convert this file. "
                    f"See [Open in Drive]({meta['gdrive_url']}).\n", meta))
            return md_path, "kept_binary"

    if mime_type in SKIP_MIME_TYPES:
        return None, f"skipped_{mime_type.rsplit('.', 1)[-1]}"

    if mime_type.startswith("video/"):
        return None, "skipped_video"

    if size > MAX_FILE_SIZE_MB * 1024 * 1024:
        return None, f"skipped_too_large_{size // (1024 * 1024)}MB"

    # Binary / plain files — download via alt=media
    ext = raw_ext or EXT_MAP.get(mime_type, "")
    output_path = os.path.join(target_dir, f"{safe_name}{ext}")
    if not gws_file("files", "get", output_path=output_path,
                   fileId=file_id, alt="media", supportsAllDrives=True):
        return None, "failed"

    # Try conversion for formats markitdown handles
    if ext.lower() in {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".html"}:
        md_path = os.path.join(target_dir, f"{safe_name}.md")
        try:
            text = _convert_with_timeout(output_path)
            meta = _build_meta(file_info, drive_rel_path)
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(stamp_frontmatter(text, meta))
            os.remove(output_path)
            return md_path, "converted"
        except Exception as e:
            print(f"  WARN: markitdown failed for {os.path.basename(output_path)}: "
                  f"{str(e).splitlines()[0][:160]}", file=sys.stderr)
            # keep binary, also write a stub .md so citation still works
            meta = _build_meta(file_info, drive_rel_path)
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(stamp_frontmatter(
                    f"> markitdown could not convert this file. "
                    f"See [Open in Drive]({meta['gdrive_url']}).\n", meta))
            return md_path, "kept_binary"

    return output_path, "kept_binary"


# -- INDEX.md rendering -------------------------------------------------------

MIME_LABEL = {
    FOLDER_MIME: "Folder",
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


def describe(f: dict) -> str:
    desc = (f.get("description") or "").strip()
    if desc:
        return " ".join(desc.split())
    bits = []
    mt = (f.get("modifiedTime") or "")[:10]
    if mt:
        bits.append(f"modified {mt}")
    owners = f.get("owners") or []
    if owners:
        bits.append(f"owner {owners[0].get('displayName')}")
    sd = f.get("shortcutDetails")
    if sd:
        target = MIME_LABEL.get(sd.get("targetMimeType", ""), sd.get("targetMimeType", "?"))
        bits.append(f"shortcut → {target}")
    if not bits:
        bits.append("no drive description set")
    return "; ".join(bits)


def rel_path_parts(cache: dict, folder_id: str) -> list[str]:
    parts: list[str] = []
    cur = folder_id
    folders = cache["folders"]
    seen: set[str] = set()
    while cur and cur in folders and cur not in seen:
        seen.add(cur)
        node = folders[cur]
        if node.get("parent_id") is None:
            break
        parts.insert(0, node["name"])
        cur = node.get("parent_id")
    return parts


def folder_on_disk(out_dir: str, cache: dict, folder_id: str) -> str:
    parts = rel_path_parts(cache, folder_id)
    if not parts:
        return out_dir
    return os.path.join(out_dir, *[sanitize(p) for p in parts])


def render_folder_index(out_dir: str, cache: dict, folder_id: str,
                        mode: str, local_md_map: dict[str, str]) -> str | None:
    """Render INDEX.md for a folder.
    `local_md_map` maps file_id -> local .md path (relative to the folder on disk)
    for files that were converted in full mode. Empty in index mode."""
    folders = cache["folders"]
    node = folders.get(folder_id)
    if node is None:
        return None

    children = node.get("children", [])
    subfolders = [c for c in children if c["mimeType"] == FOLDER_MIME]
    files = [c for c in children if c["mimeType"] != FOLDER_MIME]

    above_target = cache.get("root_path_display") or ""
    here_parts = rel_path_parts(cache, folder_id)
    if here_parts:
        chain = [above_target, cache.get("root_name", "")] + here_parts
    else:
        chain = [above_target]
    display_path = " / ".join(filter(None, chain)) or cache.get("drive_name", "")

    folder_disk = folder_on_disk(out_dir, cache, folder_id)
    os.makedirs(folder_disk, exist_ok=True)

    name = node["name"]
    drive_link = f"https://drive.google.com/drive/folders/{folder_id}"

    lines: list[str] = []
    lines.append(f"# {name}")
    lines.append("")
    lines.append(f"- Path: {display_path}")
    lines.append(f"- Drive link: {drive_link}")
    lines.append(f"- Mode: `{mode}`")
    if node.get("parent_id"):
        lines.append("- Parent: [../INDEX.md](../INDEX.md)")
    lines.append(f"- Direct files: {len(files)} · Direct subfolders: {len(subfolders)}")
    lines.append(f"- Last scanned: {node.get('last_scanned', cache.get('last_sync', ''))}")
    lines.append("")

    if subfolders:
        lines.append("## Subfolders")
        lines.append("")
        for sf in sorted(subfolders, key=lambda x: x["name"].lower()):
            sf_node = folders.get(sf["id"], {})
            sf_children = sf_node.get("children") or []
            sf_files = sum(1 for c in sf_children if c["mimeType"] != FOLDER_MIME)
            sf_subs = sum(1 for c in sf_children if c["mimeType"] == FOLDER_MIME)
            label = f"{sanitize(sf['name'])}/"
            link = f"{quote(sanitize(sf['name']))}/INDEX.md"
            parts = [f"{sf_files} file{'' if sf_files == 1 else 's'}"]
            if sf_subs:
                parts.append(f"{sf_subs} subfolder{'' if sf_subs == 1 else 's'}")
            mt = (sf.get("modifiedTime") or "")[:10]
            if mt:
                parts.append(f"modified {mt}")
            lines.append(f"- [{label}]({link}) — {', '.join(parts)}")
        lines.append("")

    if files:
        lines.append("## Files")
        lines.append("")
        for f in sorted(files, key=lambda x: x["name"].lower()):
            title = f["name"].replace("|", "\\|").replace("\n", " ")
            drive_url = f.get("webViewLink") or f"https://drive.google.com/open?id={f['id']}"
            kind = mime_label(f["mimeType"])
            desc = describe(f).replace("\n", " ")
            local = local_md_map.get(f["id"])
            if local:
                lines.append(f"- **[{title}]({quote(local)})** — {kind}; {desc} · [Open in Drive]({drive_url})")
            else:
                lines.append(f"- **[{title}]({drive_url})** — {kind}; {desc}")
        lines.append("")

    if not subfolders and not files:
        lines.append("_(empty folder)_")
        lines.append("")

    index_path = os.path.join(folder_disk, INDEX_NAME)
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return index_path


# -- Folder tree walk + cache -------------------------------------------------

def _minify_child(item: dict) -> dict:
    keys = (
        "id", "name", "mimeType", "webViewLink", "description",
        "modifiedTime", "owners", "shortcutDetails", "size",
    )
    return {k: item[k] for k in keys if k in item}


def update_folder_children(cache: dict, folder_id: str, children: list[dict], now_iso: str) -> None:
    folders = cache["folders"]
    node = folders.setdefault(folder_id, {})
    node["id"] = folder_id
    node["children"] = [_minify_child(c) for c in children]
    node["last_scanned"] = now_iso


def ensure_folder_node(cache: dict, folder_id: str, name: str, parent_id: str | None) -> dict:
    node = cache["folders"].setdefault(folder_id, {
        "id": folder_id, "name": name, "parent_id": parent_id,
        "children": [], "last_scanned": None,
    })
    node["name"] = name
    node["parent_id"] = parent_id
    return node


def full_sync_tree(root_id: str, cache: dict) -> set[str]:
    """Walk the whole subtree and repopulate cache['folders'].
    Returns the set of folder_ids that were (re-)listed."""
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache["folders"] = {}
    ensure_folder_node(cache, root_id, cache["root_name"], None)

    listed: set[str] = set()
    queue = deque([root_id])
    while queue:
        fid = queue.popleft()
        try:
            children = list_children(fid)
        except Exception as e:
            print(f"  Warning: list_children({fid}) failed: {e}", file=sys.stderr)
            continue
        update_folder_children(cache, fid, children, now_iso)
        listed.add(fid)
        print(f"  scanned {fid}: {len(children)} children", file=sys.stderr)
        for c in children:
            if c["mimeType"] == FOLDER_MIME:
                ensure_folder_node(cache, c["id"], c["name"], fid)
                queue.append(c["id"])
    cache["last_sync"] = now_iso
    return listed


def incremental_sync_tree(root_id: str, cache: dict, drive_id: str | None) -> set[str]:
    """Use the Drive 'modifiedTime > since' query to find changed items,
    re-list only affected folders. Returns the set of re-listed folder_ids."""
    since = cache.get("last_sync")
    if not since:
        return full_sync_tree(root_id, cache)

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        changed = query_changed(since, drive_id)
    except Exception as e:
        print(f"  Warning: changes query failed, falling back to full sync: {e}", file=sys.stderr)
        return full_sync_tree(root_id, cache)
    print(f"  {len(changed)} drive items changed since {since}", file=sys.stderr)

    known = set(cache["folders"].keys())

    # Discover new folders under our subtree (iterate to catch grandchildren).
    added = True
    while added:
        added = False
        for item in changed:
            if item["mimeType"] != FOLDER_MIME or item["id"] in known:
                continue
            parents = item.get("parents") or []
            if parents and parents[0] in known:
                ensure_folder_node(cache, item["id"], item["name"], parents[0])
                known.add(item["id"])
                added = True

    affected: set[str] = set()
    for item in changed:
        parents = item.get("parents") or []
        if parents and parents[0] in known:
            affected.add(parents[0])
        if item["mimeType"] == FOLDER_MIME and item["id"] in known:
            affected.add(item["id"])

    if not affected:
        cache["last_sync"] = now_iso
        return set()

    queue = deque(sorted(affected))
    re_listed: set[str] = set()
    while queue:
        fid = queue.popleft()
        if fid in re_listed or fid not in cache["folders"]:
            continue
        re_listed.add(fid)
        try:
            children = list_children(fid)
        except Exception as e:
            print(f"  Warning: list_children({fid}) failed: {e}", file=sys.stderr)
            continue
        old_child_ids = {c["id"] for c in cache["folders"][fid].get("children", [])}
        update_folder_children(cache, fid, children, now_iso)
        for c in children:
            if c["mimeType"] == FOLDER_MIME:
                if c["id"] not in cache["folders"]:
                    ensure_folder_node(cache, c["id"], c["name"], fid)
                    queue.append(c["id"])
                else:
                    node = cache["folders"][c["id"]]
                    if node.get("name") != c["name"] or node.get("parent_id") != fid:
                        node["name"] = c["name"]
                        node["parent_id"] = fid
                        re_listed.discard(c["id"])
                        queue.append(c["id"])
        # prune folders that vanished from this parent
        new_folder_child_ids = {c["id"] for c in children if c["mimeType"] == FOLDER_MIME}
        removed_subfolders = (old_child_ids - {c["id"] for c in children}) & set(cache["folders"].keys())
        for rid in removed_subfolders:
            node = cache["folders"].get(rid)
            if node and node.get("parent_id") == fid and rid not in new_folder_child_ids:
                drop = [rid]
                to_visit = deque([rid])
                while to_visit:
                    x = to_visit.popleft()
                    for c in cache["folders"].get(x, {}).get("children", []):
                        if c["mimeType"] == FOLDER_MIME and c["id"] in cache["folders"]:
                            drop.append(c["id"])
                            to_visit.append(c["id"])
                for did in drop:
                    cache["folders"].pop(did, None)

    cache["last_sync"] = now_iso
    return re_listed


# -- Content sync (full mode only) --------------------------------------------

def sync_content_for_folders(cache: dict, out_dir: str, folder_ids: set[str],
                             force: bool) -> tuple[dict[str, str], dict]:
    """For every file in the given folders, download+convert unless the file's
    modifiedTime matches what we have in cache['files'].
    Returns (file_id -> local_md_name_relative_to_folder, stats).
    """
    cache.setdefault("files", {})
    file_state: dict = cache["files"]

    stats = {"converted": 0, "kept_binary": 0, "skipped": 0, "failed": 0, "unchanged": 0}
    # file_id -> relative md filename (used by INDEX rendering)
    local_map: dict[str, str] = {}

    total = 0
    for fid in folder_ids:
        node = cache["folders"].get(fid, {})
        for c in node.get("children", []):
            if c["mimeType"] != FOLDER_MIME:
                total += 1

    idx = 0
    for fid in folder_ids:
        node = cache["folders"].get(fid)
        if not node:
            continue
        folder_disk = folder_on_disk(out_dir, cache, fid)
        drive_rel_path = "/".join(rel_path_parts(cache, fid))

        for c in node.get("children", []):
            if c["mimeType"] == FOLDER_MIME:
                continue
            idx += 1
            file_id = c["id"]
            name = c.get("name", "Untitled")
            mtime = c.get("modifiedTime")
            prev = file_state.get(file_id, {})
            name_stem, _ = os.path.splitext(name)
            safe_stem = sanitize(name_stem)

            status_short = c["mimeType"].rsplit(".", 1)[-1]
            unchanged = (
                not force
                and prev.get("modifiedTime") == mtime
                and prev.get("local_path")
                and os.path.exists(os.path.join(PROJECT_ROOT, prev["local_path"]))
            )
            if unchanged:
                stats["unchanged"] += 1
                local_rel = os.path.basename(prev["local_path"])
                # sanity: ensure it still sits in folder_disk
                abs_prev = os.path.join(PROJECT_ROOT, prev["local_path"])
                if os.path.dirname(abs_prev) == folder_disk and abs_prev.endswith(".md"):
                    local_map[file_id] = local_rel
                print(f"  [{idx}/{total}] = {name[:45]:<45} ({status_short})", flush=True)
                continue

            local_path, status = download_and_convert(
                c, folder_disk, os.path.join(drive_rel_path, name),
            )
            if status == "converted":
                stats["converted"] += 1
            elif status == "kept_binary":
                stats["kept_binary"] += 1
            elif status.startswith("skipped"):
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

            if local_path and local_path.endswith(".md"):
                rel = os.path.relpath(local_path, PROJECT_ROOT)
                local_map[file_id] = os.path.basename(local_path)
                file_state[file_id] = {
                    "modifiedTime": mtime,
                    "mimeType": c["mimeType"],
                    "name": name,
                    "local_path": rel,
                    "folder_id": fid,
                }
            elif local_path:
                # binary fallback — record so we don't retry every run
                rel = os.path.relpath(local_path, PROJECT_ROOT)
                file_state[file_id] = {
                    "modifiedTime": mtime,
                    "mimeType": c["mimeType"],
                    "name": name,
                    "local_path": rel,
                    "folder_id": fid,
                }
            mark = "✓" if status == "converted" else ("·" if status == "kept_binary" else "✗")
            print(f"  [{idx}/{total}] {mark} {name[:45]:<45} ({status_short}) [{status}]", flush=True)

    # For folders we didn't touch this run, rehydrate local_map from file_state
    for file_id, state in file_state.items():
        lp = state.get("local_path", "")
        if not lp.endswith(".md") or file_id in local_map:
            continue
        expected_dir = folder_on_disk(out_dir, cache, state.get("folder_id", ""))
        abs_path = os.path.join(PROJECT_ROOT, lp)
        if os.path.dirname(abs_path) == expected_dir and os.path.exists(abs_path):
            local_map[file_id] = os.path.basename(abs_path)

    return local_map, stats


def prune_content_state(cache: dict) -> None:
    """Drop files from cache['files'] whose folders no longer exist, and delete
    their local files."""
    folders = cache.get("folders", {})
    files = cache.get("files", {})
    drop = []
    for fid, state in files.items():
        if state.get("folder_id") not in folders:
            drop.append(fid)
    for fid in drop:
        lp = files[fid].get("local_path")
        if lp:
            abs_path = os.path.join(PROJECT_ROOT, lp)
            try:
                os.remove(abs_path)
            except OSError:
                pass
        files.pop(fid, None)


def cleanup_stale(out_dir: str, cache: dict) -> int:
    """Remove INDEX.md files (and empty dirs) whose folders no longer exist."""
    valid = {os.path.join(folder_on_disk(out_dir, cache, fid), INDEX_NAME)
             for fid in cache["folders"]}

    removed = 0
    for dirpath, _dirs, filenames in os.walk(out_dir):
        if INDEX_NAME in filenames:
            p = os.path.join(dirpath, INDEX_NAME)
            if p not in valid:
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass

    for dirpath, _dirs, _files in sorted(
        os.walk(out_dir), key=lambda t: t[0].count(os.sep), reverse=True
    ):
        if dirpath == out_dir:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass
    return removed


# -- Stats --------------------------------------------------------------------

def count_totals(cache: dict) -> tuple[int, int]:
    folders = len(cache["folders"])
    files = sum(
        1 for node in cache["folders"].values()
        for c in node.get("children", [])
        if c["mimeType"] != FOLDER_MIME
    )
    return files, folders


# -- Main ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a Google Drive folder to src/gdrive/ as Markdown + per-folder INDEX.md."
    )
    parser.add_argument("url", nargs="?", help="Google Drive folder URL (or bare ID)")
    parser.add_argument("--mode", choices=["full", "index"], default="full",
                        help="full = download+convert files (default); index = INDEX.md only")
    parser.add_argument("--full-rebuild", action="store_true",
                        help="Ignore cache, re-walk the whole folder tree")
    parser.add_argument("--force", action="store_true",
                        help="Full mode: re-download every file regardless of modifiedTime")
    parser.add_argument("--list", action="store_true",
                        help="List previously exported roots and exit")
    args = parser.parse_args()

    if args.list:
        print_registry()
        return
    if not args.url:
        parser.error("url is required (unless --list)")

    if args.mode == "full":
        _check_markitdown_extras()

    folder_id = parse_gdrive_url(args.url)
    print(f"Target: {folder_id}", file=sys.stderr)

    path_parts, drive_name, root_info, is_drive_root = resolve_target(folder_id)
    if root_info.get("mimeType") != FOLDER_MIME:
        print(f"ERROR: target is not a folder (mimeType: {root_info.get('mimeType')})",
              file=sys.stderr)
        sys.exit(1)

    if is_drive_root:
        root_name = drive_name
        path_parts = []
    else:
        root_name = path_parts[-1] if path_parts else drive_name

    out_dir = compute_out_dir(drive_name, path_parts, is_drive_root)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Drive: {drive_name}", file=sys.stderr)
    print(f"Path : {'/'.join(path_parts)}", file=sys.stderr)
    print(f"Out  : {_rel(out_dir)}", file=sys.stderr)
    print(f"Mode : {args.mode}", file=sys.stderr)

    cache = load_cache(out_dir)
    do_full_tree = (
        args.full_rebuild or not cache or "folders" not in cache
        or folder_id not in cache.get("folders", {})
    )
    if do_full_tree:
        cache = {
            "root_id": folder_id,
            "root_name": root_name,
            "drive_id": root_info.get("driveId"),
            "drive_name": drive_name,
            "is_drive_root": is_drive_root,
            "root_path_display": ("" if is_drive_root
                                 else " / ".join([drive_name] + path_parts[:-1])),
            "url": args.url,
            "mode": args.mode,
            "folders": {},
            "files": {},
            "last_sync": None,
        }

    cache["url"] = args.url
    cache["drive_name"] = drive_name
    cache["root_name"] = root_name
    cache["drive_id"] = root_info.get("driveId")
    cache["is_drive_root"] = is_drive_root
    cache["root_path_display"] = ("" if is_drive_root
                                 else " / ".join([drive_name] + path_parts[:-1]))
    cache["mode"] = args.mode

    # Phase 1: sync the folder tree
    if do_full_tree:
        touched = full_sync_tree(folder_id, cache)
        tree_mode = "full"
    else:
        touched = incremental_sync_tree(folder_id, cache, cache.get("drive_id"))
        tree_mode = "incremental"

    # Phase 2: content sync (full mode only) — only for touched folders,
    # unless --force, in which case sync every folder.
    local_maps_by_folder: dict[str, dict[str, str]] = {}
    content_stats: dict = {}
    if args.mode == "full":
        sync_folders = set(cache["folders"].keys()) if args.force else set(touched)
        # In content mode we also want to cover any folder that doesn't yet
        # have a recorded last_content_sync — easiest signal is: any folder
        # whose children include a file we've never seen in cache['files'].
        file_state = cache.get("files", {})
        for fid, node in cache["folders"].items():
            if fid in sync_folders:
                continue
            for c in node.get("children", []):
                if c["mimeType"] != FOLDER_MIME and c["id"] not in file_state:
                    sync_folders.add(fid)
                    break

        local_map, content_stats = sync_content_for_folders(
            cache, out_dir, sync_folders, force=args.force,
        )

        # Group the flat id->basename map by folder for INDEX rendering.
        for fid, state in cache.get("files", {}).items():
            folder = state.get("folder_id")
            local = state.get("local_path", "")
            if not folder or not local.endswith(".md"):
                continue
            local_maps_by_folder.setdefault(folder, {})[fid] = os.path.basename(local)

    # Phase 3: render INDEX.md for every folder (cheap, keeps tree consistent
    # with the latest cache — handles renames/moves naturally).
    for fid in list(cache["folders"].keys()):
        local_map = local_maps_by_folder.get(fid, {})
        render_folder_index(out_dir, cache, fid, args.mode, local_map)

    # Phase 4: prune state for folders that vanished, then stale files on disk
    prune_content_state(cache)
    removed = cleanup_stale(out_dir, cache)

    # Phase 5: rewrite cross-references in converted markdown
    if args.mode == "full":
        link_map = build_link_map()
        for fid, state in cache.get("files", {}).items():
            lp = state.get("local_path")
            if lp:
                link_map[f"gdrive:{fid}"] = lp
        rewritten = 0
        for state in cache.get("files", {}).values():
            lp = state.get("local_path")
            if not lp or not lp.endswith(".md"):
                continue
            abs_path = os.path.join(PROJECT_ROOT, lp)
            if not os.path.isfile(abs_path):
                continue
            try:
                with open(abs_path, encoding="utf-8") as fh:
                    content = fh.read()
                new_content = rewrite_links(content, lp, link_map)
                if new_content != content:
                    with open(abs_path, "w", encoding="utf-8") as fh:
                        fh.write(new_content)
                    rewritten += 1
            except Exception:
                pass
        if rewritten:
            print(f"  Rewrote links in {rewritten} markdown file(s).")

    save_cache(out_dir, cache)
    file_count, folder_count = count_totals(cache)

    stats = {"tree_mode": tree_mode}
    if content_stats:
        stats.update(content_stats)

    files_for_registry = [
        {"file_id": fid, "file_path": state["local_path"]}
        for fid, state in cache.get("files", {}).items()
        if state.get("local_path")
    ]

    upsert_registry(
        url=args.url,
        folder_id=folder_id,
        folder_name=root_name,
        output_path=_rel(out_dir),
        mode=args.mode,
        file_count=file_count,
        folder_count=folder_count,
        stats=stats,
        files=files_for_registry,
    )

    summary = f"\nDone ({args.mode}/{tree_mode}). {file_count} files across {folder_count} folders."
    if content_stats:
        summary += (
            f" content: {content_stats.get('converted', 0)} converted, "
            f"{content_stats.get('unchanged', 0)} unchanged, "
            f"{content_stats.get('kept_binary', 0)} kept binary, "
            f"{content_stats.get('skipped', 0)} skipped, "
            f"{content_stats.get('failed', 0)} failed."
        )
    summary += f" Removed {removed} stale."
    print(summary)
    print(f"Root index: {_rel(os.path.join(out_dir, INDEX_NAME))}")


if __name__ == "__main__":
    main()
