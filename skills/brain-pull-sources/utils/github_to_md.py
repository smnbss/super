#!/usr/bin/env python3
from __future__ import annotations
"""
GitHub Repository -> Markdown exporter with incremental sync.

Usage:
    python github_to_md.py <github_repo_url> [--token TOKEN]

Examples:
    # Export a public repo
    python github_to_md.py https://github.com/org/repo

    # Export with authentication (for private repos or higher rate limits)
    python github_to_md.py https://github.com/org/repo --token ghp_xxxx

    # Force re-export all files
    python github_to_md.py https://github.com/org/repo --force

Output is saved to: src/github/<owner>/<repo>/

Environment:
    GITHUB_TOKEN -- Personal access token (or use --token)
    
Note: Without a token, public repos work but rate limits apply (60 requests/hour).
    With a token: 5,000 requests/hour.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from rewrite_links import build_link_map, rewrite_links


# -- Project root (use git to find repo root, not relative path) --------------

import subprocess as _sp
PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()


# -- Load .env.local from project root -----------------------------------------

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
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "github")
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


def get_existing_file_map(repo_full_name: str) -> dict[str, dict]:
    """Get a map of file_path -> file info from existing registry."""
    entries = load_registry()
    for entry in entries:
        if entry["repo_full_name"] == repo_full_name:
            return {f["path"]: f for f in entry.get("files", [])}
    return {}


def upsert_registry(url: str, repo_full_name: str, owner: str, repo: str,
                    output_path: str, file_count: int, files: list[dict],
                    stats: dict):
    """Add or update a registry entry for the given repo."""
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()

    files_manifest = []
    for f in files:
        files_manifest.append({
            "path": f.get("path"),
            "name": f.get("name", "untitled"),
            "sha": f.get("sha"),
            "size": f.get("size", 0),
            "html_url": f.get("html_url", ""),
            "last_exported": now if f.get("_exported") else f.get("_last_exported"),
        })

    existing = next((e for e in entries if e["repo_full_name"] == repo_full_name), None)
    if existing:
        existing["url"] = url
        existing["owner"] = owner
        existing["repo"] = repo
        existing["output_path"] = output_path
        existing["file_count"] = file_count
        existing["last_exported"] = now
        existing["export_count"] = existing.get("export_count", 0) + 1
        existing["files"] = files_manifest
        existing["stats"] = stats
    else:
        entries.append({
            "url": url,
            "repo_full_name": repo_full_name,
            "owner": owner,
            "repo": repo,
            "output_path": output_path,
            "file_count": file_count,
            "first_exported": now,
            "last_exported": now,
            "export_count": 1,
            "files": files_manifest,
            "stats": stats,
        })

    save_registry(entries)


def print_registry(verbose: bool = False):
    """Print a formatted table of all previously exported repos."""
    entries = load_registry()
    if not entries:
        print("No repositories exported yet.")
        return

    print(f"{'Repository':<40} {'Files':>5}  {'Exports':>7}  {'Last Exported':<20}  URL")
    print("-" * 120)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        stats = e.get("stats", {})
        file_info = f"{stats.get('updated', 0)}/{stats.get('total', e['file_count'])} updated" if stats else str(e['file_count'])
        repo_name = f"{e['owner']}/{e['repo']}"[:40]
        print(f"{repo_name:<40} {file_info:>12}  {e.get('export_count', 1):>7}  {last:<20}  {e['url']}")


# -- URL parsing --------------------------------------------------------------

REPO_URL_PATTERNS = [
    re.compile(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$"),
    re.compile(r"https?://github\.com/([^/]+)/([^/]+?)/.*"),
]


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner and repo from a GitHub URL."""
    for pattern in REPO_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1), m.group(2)
    print(f"ERROR: Could not parse GitHub URL: {url}", file=sys.stderr)
    print("Expected format: https://github.com/<owner>/<repo>", file=sys.stderr)
    sys.exit(1)


# -- API helpers --------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"


def api_get(url: str, token: str | None = None) -> dict | list:
    """Make authenticated GET request to GitHub API."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "brain-github-to-md",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("ERROR: Authentication failed. Please provide a valid GitHub token.", file=sys.stderr)
            print("Get a token from: https://github.com/settings/tokens", file=sys.stderr)
        elif e.code == 404:
            print("ERROR: Repository not found or not accessible.", file=sys.stderr)
        elif e.code == 403:
            print("ERROR: Rate limit exceeded or access forbidden.", file=sys.stderr)
            print("Try using a personal access token with --token or GITHUB_TOKEN env var.", file=sys.stderr)
        raise


def download_file(url: str, token: str | None = None) -> bytes:
    """Download raw file content from GitHub."""
    headers = {"User-Agent": "brain-github-to-md"}
    if token:
        headers["Authorization"] = f"token {token}"
    
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return resp.read()


# -- GitHub API ---------------------------------------------------------------

INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    return name[:200]


def sanitize_path_component(name: str) -> str:
    """Sanitize a path component for filesystem safety."""
    return sanitize_filename(name)


def get_repo_info(owner: str, repo: str, token: str | None = None) -> dict:
    """Fetch repository metadata."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    return api_get(url, token)


def get_file_content(owner: str, repo: str, path: str, token: str | None = None) -> bytes:
    """Get raw file content from repository."""
    # Use raw.githubusercontent.com for file content
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
    return download_file(raw_url, token)


def should_include_file(path: str) -> bool:
    """
    Check if file should be included based on patterns:
    - README.md (any case, any directory)
    - *.md (all markdown files)
    - **/docs/**.md (markdown files in docs directories)
    """
    path_lower = path.lower()
    
    # Always include README.md (case insensitive)
    if os.path.basename(path_lower) == "readme.md":
        return True
    
    # Include all .md files
    if path_lower.endswith(".md"):
        return True
    
    # Include files in docs/ directories
    if "/docs/" in path_lower and path_lower.endswith(".md"):
        return True
    
    return False


def list_repo_files_recursive(owner: str, repo: str, token: str | None = None, 
                               path: str = "", visited: set | None = None) -> list[dict]:
    """
    Recursively list all files in a repository that match the patterns.
    Returns list of file metadata dicts.
    """
    if visited is None:
        visited = set()
    
    # Prevent infinite recursion
    cache_key = f"{owner}/{repo}:{path}"
    if cache_key in visited:
        return []
    visited.add(cache_key)
    
    files = []
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    
    try:
        items = api_get(url, token)
    except urllib.error.HTTPError as e:
        print(f"  Warning: Could not list contents of '{path}': {e}", file=sys.stderr)
        return files
    
    if not isinstance(items, list):
        return files
    
    for item in items:
        item_type = item.get("type")
        item_path = item.get("path", "")
        
        if item_type == "dir":
            # Recursively list directory
            files.extend(list_repo_files_recursive(owner, repo, token, item_path, visited))
        elif item_type == "file":
            # Check if file matches patterns
            if should_include_file(item_path):
                files.append({
                    "name": item.get("name"),
                    "path": item_path,
                    "sha": item.get("sha"),
                    "size": item.get("size", 0),
                    "html_url": item.get("html_url", ""),
                    "download_url": item.get("download_url", ""),
                    "type": "file",
                })
    
    return files


def get_file_last_modified(file_info: dict) -> str:
    """Use SHA as the modification identifier (GitHub doesn't provide modifiedTime in content API)."""
    return file_info.get("sha", "")


def should_update_file(file_path: str, server_sha: str, registry_files: dict) -> bool:
    """Check if file needs update based on SHA."""
    if file_path not in registry_files:
        return True
    cached_sha = registry_files[file_path].get("sha", "")
    return server_sha != cached_sha


# -- Export -------------------------------------------------------------------

def export_repo(owner: str, repo: str, token: str | None = None, force: bool = False) -> tuple[str, list[dict], dict]:
    """
    Export all matching files from a GitHub repository.
    Returns (output_path, files, stats).
    """
    print(f"Fetching repository info for {owner}/{repo}...")
    repo_info = get_repo_info(owner, repo, token)
    repo_full_name = repo_info.get("full_name", f"{owner}/{repo}")
    default_branch = repo_info.get("default_branch", "main")
    
    print(f"Scanning for markdown files in {repo_full_name}...")
    files = list_repo_files_recursive(owner, repo, token)
    
    if not files:
        print("No matching markdown files found.")
        return "", [], {"total": 0, "new": 0, "updated": 0, "unchanged": 0, "errors": 0}
    
    print(f"Found {len(files)} markdown file(s)")
    
    # Prepare output directory
    output_dir = os.path.join(OUTPUT_BASE, sanitize_path_component(owner), sanitize_path_component(repo))
    os.makedirs(output_dir, exist_ok=True)
    
    # Load existing registry for incremental sync
    registry_files = {} if force else get_existing_file_map(repo_full_name)
    
    # Track stats
    stats = {"total": len(files), "new": 0, "updated": 0, "unchanged": 0, "errors": 0}
    
    # Export files
    for i, file_info in enumerate(files, 1):
        file_path = file_info["path"]
        file_name = file_info["name"]
        file_sha = get_file_last_modified(file_info)
        
        # Determine output path maintaining structure
        relative_dir = os.path.dirname(file_path)
        if relative_dir:
            file_output_dir = os.path.join(output_dir, relative_dir)
        else:
            file_output_dir = output_dir
        
        output_file_path = os.path.join(file_output_dir, sanitize_filename(file_name))
        
        # Check if update needed
        if not force and not should_update_file(file_path, file_sha, registry_files):
            print(f"  [{i}/{len(files)}] ⏭️  Unchanged: {file_path}")
            file_info["_exported"] = False
            file_info["_file_path"] = output_file_path
            file_info["_last_exported"] = registry_files[file_path].get("last_exported", "")
            stats["unchanged"] += 1
            continue
        
        action = "New" if file_path not in registry_files else "Updated"
        
        try:
            print(f"  [{i}/{len(files)}] 📄 Downloading: {file_path}", end="")
            
            # Download file content
            content = get_file_content(owner, repo, file_path, token)
            
            # Create directory and save
            os.makedirs(file_output_dir, exist_ok=True)
            with open(output_file_path, "wb") as f:
                f.write(content)
            
            file_info["_exported"] = True
            file_info["_file_path"] = output_file_path
            file_info["_last_exported"] = datetime.now(timezone.utc).isoformat()
            
            if action == "New":
                stats["new"] += 1
            else:
                stats["updated"] += 1
            
            print(f" ✓ ({len(content)} bytes)")
            
        except Exception as e:
            print(f" ✗ ERROR: {e}", file=sys.stderr)
            file_info["_exported"] = False
            file_info["_file_path"] = output_file_path
            stats["errors"] += 1
    
    # Rewrite links in exported markdown files
    link_map = build_link_map()
    for fi in files:
        html_url = fi.get("html_url", "")
        fp = fi.get("_file_path")
        if html_url and fp:
            fp_rel = os.path.relpath(fp, PROJECT_ROOT) if os.path.isabs(fp) else fp
            link_map[f"github:{html_url}"] = fp_rel

    rewritten = 0
    for fi in files:
        fp = fi.get("_file_path")
        if not fp or not fi.get("_exported"):
            continue
        if not fp.endswith(".md"):
            continue
        abs_path = fp if os.path.isabs(fp) else os.path.join(PROJECT_ROOT, fp)
        rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
        try:
            with open(abs_path, "r", encoding="utf-8") as fh:
                content_str = fh.read()
            new_content = rewrite_links(content_str, rel_path, link_map)
            if new_content != content_str:
                with open(abs_path, "w", encoding="utf-8") as fh:
                    fh.write(new_content)
                rewritten += 1
        except Exception:
            pass
    if rewritten:
        print(f"  Rewrote links in {rewritten} markdown file(s).")

    return output_dir, files, stats


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export markdown files from a GitHub repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://github.com/org/repo
  %(prog)s https://github.com/org/repo --token ghp_xxxx
  %(prog)s --list
        """
    )
    parser.add_argument("url", nargs="?", help="GitHub repository URL (e.g., https://github.com/owner/repo)")
    parser.add_argument("--token", dest="token", help="GitHub personal access token (or set GITHUB_TOKEN env var)")
    parser.add_argument("--force", dest="force", action="store_true", help="Force re-export all files (skip incremental check)")
    parser.add_argument("--list", dest="list_registry", action="store_true", help="List previously exported repositories")
    parser.add_argument("--verbose", dest="verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    if args.list_registry:
        print_registry(verbose=args.verbose)
        return
    
    if not args.url:
        parser.print_help()
        sys.exit(1)
    
    # Get token from args or environment
    token = args.token or os.environ.get("GITHUB_TOKEN")
    
    if not token:
        print("⚠️  No GitHub token provided. Using unauthenticated requests (60 req/hour limit).")
        print("   For private repos or higher limits, set GITHUB_TOKEN in .env or use --token")
        print()
    
    # Parse URL
    owner, repo = parse_github_url(args.url)
    
    print(f"Exporting from GitHub: {owner}/{repo}")
    print(f"Output base: {OUTPUT_BASE}")
    print()
    
    # Export
    try:
        output_path, files, stats = export_repo(owner, repo, token, force=args.force)
        
        if not output_path:
            print("\nNo files exported.")
            sys.exit(0)
        
        # Update registry
        upsert_registry(
            url=args.url,
            repo_full_name=f"{owner}/{repo}",
            owner=owner,
            repo=repo,
            output_path=output_path,
            file_count=len(files),
            files=files,
            stats=stats
        )
        
        # Summary
        print()
        print("=" * 50)
        print("Export complete!")
        print(f"  Repository: {owner}/{repo}")
        print(f"  Total files: {stats['total']}")
        print(f"  New: {stats['new']}")
        print(f"  Updated: {stats['updated']}")
        print(f"  Unchanged: {stats['unchanged']}")
        if stats['errors'] > 0:
            print(f"  Errors: {stats['errors']}")
        print(f"  Output: {output_path}")
        print()
        print(f"Registry saved to: {REGISTRY_PATH}")
        
    except Exception as e:
        print(f"\nExport failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
