#!/usr/bin/env python3
"""Upload a .pptx to Google Drive, converting to Google Slides.

Reads the destination folder from `$RELEASES_DECKS_FOLDER` (the user's
brain `.env.local` convention). When unset the file lands in Drive root,
which is rarely what you want — so the script warns and asks you to confirm
with `--allow-root`.

Update vs create: if a Slides file with the same name already exists in
the target folder, the script *updates* it in place (preserving the file
id and Slides URL — handy for iterating without breaking links). Use
`--new` to force create-a-new-file behaviour.

Usage:
    python upload_to_drive.py \
        --pptx outputs/releases-decks/<slug>-plenaria-deck.pptx \
        --name "Jan-Apr 2026 Tech Plenaria (auto-draft)"

Prints the resulting Slides URL on success.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
SLIDES_MIME = "application/vnd.google-apps.presentation"


def load_dotenv(path: Path) -> dict[str, str]:
    """Tiny .env loader — no dependency on python-dotenv.

    Skips comments and blank lines. Splits on the first `=` only. Strips
    surrounding quotes. URLs in values are tolerated even with `#` (we
    only treat the first `=` as a separator, and don't strip inline
    comments — the brain's .env.local has bare values, no inline
    comments).
    """
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or \
           (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        out[k.strip()] = v
    return out


def normalize_folder_id(value: str) -> str:
    """Accept either a bare folder id or a full Drive URL.

    Drive URLs look like:
      https://drive.google.com/drive/folders/<ID>          (canonical)
      https://drive.google.com/drive/u/0/folders/<ID>      (user-scoped)
      https://drive.google.com/drive/folders/<ID>?...      (with query)
    """
    v = value.strip().rstrip("/")
    if "/folders/" in v:
        v = v.split("/folders/", 1)[1]
    # Drop query string and fragment
    for sep in ("?", "#"):
        if sep in v:
            v = v.split(sep, 1)[0]
    return v


def gws(args: list[str]) -> dict:
    """Call gws and parse JSON output. Raises on non-zero exit."""
    result = subprocess.run(["gws", *args], capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"gws failed: {' '.join(args[:3])}…")
    # gws prefixes with "Using keyring backend: keyring\n"; find the JSON
    out = result.stdout
    brace = out.find("{")
    if brace < 0:
        raise SystemExit(f"gws produced no JSON:\n{out}")
    return json.loads(out[brace:])


def find_existing(name: str, folder_id: str | None) -> str | None:
    """Return file id if a Slides file with this name already lives in the
    folder (or root if folder is None). Used to decide create vs update.

    Shared-drive aware: passes supportsAllDrives + includeItemsFromAllDrives
    so we can both find files in shared drives and update them in place.
    """
    q_parts = [
        f"name = '{name}'",
        f"mimeType = '{SLIDES_MIME}'",
        "trashed = false",
    ]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    else:
        q_parts.append("'root' in parents")
    q = " and ".join(q_parts)
    res = gws([
        "drive", "files", "list",
        "--params", json.dumps({
            "q": q,
            "fields": "files(id,name)",
            "pageSize": 5,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }),
    ])
    files = res.get("files", [])
    return files[0]["id"] if files else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pptx", required=True, type=Path,
                    help="path to the .pptx to upload")
    ap.add_argument("--name", required=True,
                    help="Slides file name (also used to detect existing decks)")
    ap.add_argument("--env", type=Path, default=Path(".env.local"),
                    help="path to .env file with RELEASES_DECKS_FOLDER")
    ap.add_argument("--folder",
                    help="Drive folder id (overrides env var)")
    ap.add_argument("--new", action="store_true",
                    help="always create a new file even if one with this name exists")
    ap.add_argument("--allow-root", action="store_true",
                    help="upload to Drive root if no folder is configured")
    args = ap.parse_args()

    if not args.pptx.is_file():
        raise SystemExit(f"pptx not found: {args.pptx}")

    env = load_dotenv(args.env)
    raw_folder = args.folder or env.get("RELEASES_DECKS_FOLDER") \
                 or os.environ.get("RELEASES_DECKS_FOLDER") or ""
    folder_id = normalize_folder_id(raw_folder) or None

    if not folder_id and not args.allow_root:
        raise SystemExit(
            "RELEASES_DECKS_FOLDER is not set in .env.local (or via --folder).\n"
            "Either set it to a Drive folder id, pass --folder, "
            "or rerun with --allow-root to upload to Drive root."
        )

    # Decide create vs update
    file_id = None
    if not args.new:
        file_id = find_existing(args.name, folder_id)

    if file_id:
        # Update in place — keeps the same Slides URL
        gws([
            "drive", "files", "update",
            "--params", json.dumps({
                "fileId": file_id,
                "supportsAllDrives": True,
            }),
            "--upload", str(args.pptx),
            "--upload-content-type", PPTX_MIME,
        ])
        url = f"https://docs.google.com/presentation/d/{file_id}/edit"
        print(f"updated existing deck → {url}")
    else:
        body = {"name": args.name, "mimeType": SLIDES_MIME}
        if folder_id:
            body["parents"] = [folder_id]
        res = gws([
            "drive", "files", "create",
            "--params", json.dumps({"supportsAllDrives": True}),
            "--json", json.dumps(body),
            "--upload", str(args.pptx),
            "--upload-content-type", PPTX_MIME,
        ])
        file_id = res["id"]
        url = f"https://docs.google.com/presentation/d/{file_id}/edit"
        target = f"folder {folder_id}" if folder_id else "Drive root"
        print(f"created new deck in {target} → {url}")


if __name__ == "__main__":
    main()
