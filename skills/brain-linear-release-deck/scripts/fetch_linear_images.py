#!/usr/bin/env python3
"""Download Linear issue images for a deck spec.

For every content slide that names a `mol_id`, this script:
  1. opens the issue's exported markdown in src/linear/...
  2. extracts every `![alt](https://uploads.linear.app/...)` reference
  3. picks the *best* image — prefers an animated GIF when one is present,
     else falls back to the first attachment
  4. downloads it (authenticating with $LINEAR_TOKEN) into the assets dir
     using the MOL-id as the filename stem (extension auto-detected)

Why GIFs win: Linear comments often include both a screenshot *and* an
ezgif/Loom-export GIF demoing the flow. The GIF is almost always the more
useful slide visual because it shows the actual interaction, and Google
Slides preserves the animation when the deck is uploaded.

Usage:
    python fetch_linear_images.py \
        --spec outputs/releases-decks/<slug>-deck-spec.json \
        --assets-dir outputs/releases-decks/<slug>-assets

Reads $LINEAR_TOKEN from the environment (load .env.local first if needed).
Issue markdown is read from $BRAIN_ROOT/src/linear/weroad/<project>/issues/<MOL-id>.md;
$BRAIN_ROOT defaults to the current working directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# Linear's release-notes project export path
DEFAULT_ISSUES_DIR = Path(
    "src/linear/weroad/release-notes-1bc4d3fcb947-issues/issues"
)

# `![<alt>](https://uploads.linear.app/<...>)` — alt may be empty
IMG_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>https://uploads\.linear\.app/[^)\s]+)\)"
)


def collect_mol_ids(spec: dict) -> list[str]:
    ids: list[str] = []
    # Support both new "tracks" and legacy "bets" vocabulary.
    sections = spec.get("tracks") or spec.get("bets") or []
    for section in sections:
        for content in section.get("slides", []):
            mol = content.get("mol_id")
            if mol:
                ids.append(mol)
    # Top-level impact spotlights can also reference releases via release_id.
    for spot in spec.get("impact_spotlights", []) or []:
        rid = spot.get("release_id") or spot.get("mol_id")
        if rid:
            ids.append(rid)
    # Per-track impact spotlights inside slides have release_id, not mol_id.
    for section in sections:
        for slide in section.get("slides", []):
            if slide.get("type") == "impact_spotlight":
                rid = slide.get("release_id") or slide.get("mol_id")
                if rid and rid not in ids:
                    ids.append(rid)
    # Dedup preserving order.
    seen = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def parse_attachments(issue_md: str) -> list[tuple[str, str]]:
    """Return [(alt_text, url), ...] in document order."""
    return [(m.group("alt"), m.group("url")) for m in IMG_RE.finditer(issue_md)]


def pick_best(attachments: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Pick the GIF if any alt-text ends in .gif; else the first attachment.

    The alt text is Linear's stored filename, so the extension is reliable.
    When alt is empty (paste-from-clipboard), we fall back to URL position.
    """
    if not attachments:
        return None
    for alt, url in attachments:
        if alt.lower().endswith(".gif"):
            return alt, url
    return attachments[0]


def detect_extension(alt: str, content_type: str) -> str:
    if "." in alt:
        ext = alt.rsplit(".", 1)[-1].lower()
        if ext in ("gif", "png", "jpg", "jpeg", "webp"):
            return ext
    # Fall back to Content-Type
    ct_map = {
        "image/gif": "gif",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }
    return ct_map.get(content_type.split(";")[0].strip(), "png")


def download(url: str, token: str, dest: Path) -> str:
    """Download one image. Returns the resolved Content-Type."""
    req = urllib.request.Request(url, headers={"Authorization": token})
    with urllib.request.urlopen(req, timeout=60) as resp:
        ct = resp.headers.get("Content-Type", "application/octet-stream")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.read())
    return ct


def fetch_for_issue(mol_id: str, issues_dir: Path, assets_dir: Path,
                    token: str, *, force: bool = False) -> dict:
    """Resolve and download the best image for one issue."""
    issue_path = issues_dir / f"{mol_id}.md"
    if not issue_path.is_file():
        return {"mol_id": mol_id, "status": "issue_md_not_found",
                "looked_in": str(issue_path)}

    attachments = parse_attachments(issue_path.read_text())
    if not attachments:
        return {"mol_id": mol_id, "status": "no_attachments"}

    chosen = pick_best(attachments)
    alt, url = chosen

    # Skip download if a file with this stem already exists, unless --force
    existing = sorted(assets_dir.glob(f"{mol_id}.*")) if assets_dir.is_dir() else []
    if existing and not force:
        return {"mol_id": mol_id, "status": "cached",
                "path": str(existing[0]), "chose": alt or "(unnamed)"}

    # Tentative extension from alt; refined after HTTP response
    tentative_ext = detect_extension(alt, "")
    dest = assets_dir / f"{mol_id}.{tentative_ext}"

    try:
        ct = download(url, token, dest)
    except Exception as e:
        return {"mol_id": mol_id, "status": "download_failed", "error": str(e)}

    # If Content-Type disagrees, rename the file
    final_ext = detect_extension(alt, ct)
    if final_ext != tentative_ext:
        new_dest = assets_dir / f"{mol_id}.{final_ext}"
        dest.rename(new_dest)
        dest = new_dest

    return {"mol_id": mol_id, "status": "downloaded",
            "path": str(dest), "chose": alt or "(unnamed)",
            "content_type": ct,
            "n_attachments": len(attachments)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--assets-dir", required=True, type=Path)
    ap.add_argument("--issues-dir", type=Path, default=None,
                    help=f"defaults to {DEFAULT_ISSUES_DIR} under cwd")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if a file already exists")
    args = ap.parse_args()

    token = os.environ.get("LINEAR_TOKEN")
    if not token:
        print("LINEAR_TOKEN env var not set — load .env.local first.",
              file=sys.stderr)
        sys.exit(2)

    issues_dir = args.issues_dir or DEFAULT_ISSUES_DIR
    if not issues_dir.is_dir():
        print(f"issues dir not found: {issues_dir}", file=sys.stderr)
        sys.exit(2)

    spec = json.loads(args.spec.read_text())
    mol_ids = collect_mol_ids(spec)
    if not mol_ids:
        print("no mol_id fields found in spec — nothing to fetch")
        return

    args.assets_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for mol in mol_ids:
        r = fetch_for_issue(mol, issues_dir, args.assets_dir,
                            token, force=args.force)
        results.append(r)
        line = f"  {mol:8s} {r['status']:18s}"
        if r.get("path"):
            line += f" → {r['path']}"
        if r.get("chose") and r["status"] != "cached":
            line += f"  [{r['chose']}]"
        print(line)

    summary_path = args.assets_dir / "_fetch_log.json"
    summary_path.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
