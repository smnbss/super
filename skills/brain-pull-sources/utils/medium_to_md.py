#!/usr/bin/env python3
from __future__ import annotations
"""
Medium RSS Feed -> Markdown exporter with incremental sync.

Usage:
    python medium_to_md.py <rss_feed_url>

Examples:
    python medium_to_md.py https://medium.com/feed/@smnbss

Output is saved to: src/medium/<username>/

Each post becomes a markdown file named <YYYY-MM-DD>-<slug>.md with YAML frontmatter.
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


# -- Project root (use git to find repo root, not relative path) --------------

import subprocess as _sp
PROJECT_ROOT = _sp.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()


# -- Load .env.local ----------------------------------------------------------

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
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "src", "medium")
REGISTRY_PATH = os.path.join(OUTPUT_BASE, ".registry.json")


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


def get_existing_post_map(feed_url: str) -> dict[str, dict]:
    entries = load_registry()
    for entry in entries:
        if entry["feed_url"] == feed_url:
            return {p["guid"]: p for p in entry.get("posts", [])}
    return {}


def upsert_registry(feed_url: str, username: str, output_path: str, posts: list[dict], stats: dict):
    entries = load_registry()
    now = datetime.now(timezone.utc).isoformat()

    posts_manifest = []
    for p in posts:
        posts_manifest.append({
            "guid": p["guid"],
            "title": p["title"],
            "pub_date": p["pub_date"],
            "file_path": p.get("_file_path", ""),
            "last_exported": now if p.get("_exported") else p.get("_last_exported", ""),
        })

    existing = next((e for e in entries if e["feed_url"] == feed_url), None)
    if existing:
        existing["username"] = username
        existing["output_path"] = output_path
        existing["last_exported"] = now
        existing["export_count"] = existing.get("export_count", 0) + 1
        existing["posts"] = posts_manifest
        existing["stats"] = stats
    else:
        entries.append({
            "feed_url": feed_url,
            "username": username,
            "output_path": output_path,
            "first_exported": now,
            "last_exported": now,
            "export_count": 1,
            "posts": posts_manifest,
            "stats": stats,
        })

    save_registry(entries)


def print_registry():
    entries = load_registry()
    if not entries:
        print("No feeds exported yet.")
        return
    print(f"{'Username':<30} {'Posts':>5}  {'Exports':>7}  {'Last Exported':<20}  Feed URL")
    print("-" * 110)
    for e in sorted(entries, key=lambda x: x.get("last_exported", ""), reverse=True):
        last = e.get("last_exported", "")[:19].replace("T", " ")
        stats = e.get("stats", {})
        post_info = f"{stats.get('new', 0)+stats.get('updated', 0)}/{stats.get('total', 0)} updated" if stats else str(len(e.get("posts", [])))
        print(f"{e['username']:<30} {post_info:>12}  {e.get('export_count', 1):>7}  {last:<20}  {e['feed_url']}")


# -- URL / feed parsing -------------------------------------------------------

def parse_username(feed_url: str) -> str:
    """Extract username from a Medium feed URL."""
    m = re.search(r'medium\.com/feed/@([^/?#]+)', feed_url)
    if m:
        return m.group(1)
    m = re.search(r'medium\.com/feed/([^/?#]+)', feed_url)
    if m:
        return m.group(1)
    # fallback: use last path component
    return feed_url.rstrip("/").split("/")[-1].lstrip("@") or "unknown"


def fetch_feed(feed_url: str) -> bytes:
    req = urllib.request.Request(feed_url, headers={"User-Agent": "medium-to-md/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


# -- RSS parsing --------------------------------------------------------------

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
}


def parse_pub_date(date_str: str) -> str:
    """Parse RSS pubDate into ISO date string YYYY-MM-DD."""
    if not date_str:
        return ""
    # RFC 2822: Thu, 12 Jan 2023 10:00:00 +0000
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # fallback: grab first 10 chars if looks like ISO
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str.strip()):
        return date_str.strip()[:10]
    return ""


def slugify(title: str) -> str:
    """Convert title to a filename-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Parse RSS XML and return list of post dicts."""
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        channel = root

    posts = []
    for item in channel.findall("item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        guid = item.findtext("guid", link).strip()
        pub_date_raw = item.findtext("pubDate", "").strip()
        pub_date = parse_pub_date(pub_date_raw)

        # Full content preferred over description
        content_el = item.find("content:encoded", NS)
        if content_el is not None and content_el.text:
            body_html = content_el.text.strip()
        else:
            body_html = item.findtext("description", "").strip()

        # Tags / categories
        tags = [c.text.strip() for c in item.findall("category") if c.text]

        # Author
        author = item.findtext("dc:creator", "", NS).strip()

        posts.append({
            "title": title,
            "link": link,
            "guid": guid,
            "pub_date": pub_date,
            "pub_date_raw": pub_date_raw,
            "body_html": body_html,
            "tags": tags,
            "author": author,
        })

    return posts


# -- HTML -> Markdown ---------------------------------------------------------

class _MDConverter(HTMLParser):
    """Minimal HTML-to-Markdown converter using stdlib HTMLParser."""

    BLOCK_TAGS = {"p", "div", "section", "article", "figure", "figcaption"}
    SKIP_TAGS = {"style", "script", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result: list[str] = []
        self._stack: list[str] = []
        self._skip_depth = 0
        self._list_stack: list[str] = []   # "ul" or "ol"
        self._ol_counters: list[int] = []
        self._pre = False
        self._code_inline = False
        self._href: str | None = None
        self._link_text: list[str] = []
        self._collecting_link = False

    def _current_tags(self) -> set[str]:
        return set(self._stack)

    def _emit(self, text: str):
        if self._skip_depth > 0:
            return
        if self._collecting_link:
            self._link_text.append(text)
        else:
            self.result.append(text)

    def handle_starttag(self, tag: str, attrs: list):
        tag = tag.lower()
        attrs_dict = dict(attrs)

        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        self._stack.append(tag)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self._emit("\n\n" + "#" * level + " ")
        elif tag == "p":
            self._emit("\n\n")
        elif tag in ("br",):
            self._emit("  \n")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            if "pre" in self._current_tags():
                pass  # handled by pre
            else:
                self._code_inline = True
                self._emit("`")
        elif tag == "pre":
            self._pre = True
            lang = ""
            # try to detect language from class
            cls = attrs_dict.get("class", "")
            m = re.search(r"language-(\w+)", cls)
            if m:
                lang = m.group(1)
            self._emit(f"\n\n```{lang}\n")
        elif tag == "blockquote":
            self._emit("\n\n> ")
        elif tag == "ul":
            self._list_stack.append("ul")
            self._emit("\n")
        elif tag == "ol":
            self._list_stack.append("ol")
            self._ol_counters.append(0)
            self._emit("\n")
        elif tag == "li":
            if self._list_stack:
                kind = self._list_stack[-1]
                if kind == "ul":
                    self._emit("\n- ")
                else:
                    self._ol_counters[-1] += 1
                    self._emit(f"\n{self._ol_counters[-1]}. ")
            else:
                self._emit("\n- ")
        elif tag == "hr":
            self._emit("\n\n---\n")
        elif tag == "a":
            self._href = attrs_dict.get("href", "")
            self._collecting_link = True
            self._link_text = []
        elif tag == "img":
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "image")
            self._emit(f"\n\n![{alt}]({src})\n")
        elif tag in self.BLOCK_TAGS:
            self._emit("\n\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()

        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._skip_depth > 0:
            return

        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

        if tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code" and self._code_inline:
            self._emit("`")
            self._code_inline = False
        elif tag == "pre":
            self._pre = False
            self._emit("\n```\n")
        elif tag == "a":
            text = "".join(self._link_text).strip()
            self._collecting_link = False
            self._link_text = []
            href = self._href or ""
            self._href = None
            if href:
                self.result.append(f"[{text}]({href})")
            else:
                self.result.append(text)
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            if tag == "ol" and self._ol_counters:
                self._ol_counters.pop()
            self._emit("\n")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._emit("\n")
        elif tag in self.BLOCK_TAGS:
            self._emit("\n")

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        if self._pre:
            self._emit(data)
        else:
            # Collapse whitespace in normal flow
            text = re.sub(r"\s+", " ", data)
            self._emit(text)

    def get_markdown(self) -> str:
        md = "".join(self.result)
        # Clean up excessive blank lines
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md.strip()


def html_to_markdown(html_str: str) -> str:
    converter = _MDConverter()
    converter.feed(html_str)
    return converter.get_markdown()


# -- Post -> file -------------------------------------------------------------

INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str) -> str:
    name = INVALID_CHARS.sub("-", name)
    name = name.strip(". ")
    name = re.sub(r"-{2,}", "-", name)
    return name[:200]


def post_to_markdown(post: dict) -> str:
    """Render a post dict to a markdown string with YAML frontmatter."""
    title = post["title"].replace('"', '\\"')
    tags_yaml = ""
    if post["tags"]:
        tags_yaml = "\ntags:\n" + "\n".join(f"  - {t}" for t in post["tags"])

    author_yaml = f'\nauthor: "{post["author"]}"' if post["author"] else ""

    frontmatter = f"""---
title: "{title}"
date: {post["pub_date"]}
source: "{post["link"]}"{author_yaml}{tags_yaml}
---

"""
    body = html_to_markdown(post["body_html"])
    return frontmatter + body + "\n"


def output_filename(post: dict) -> str:
    date = post["pub_date"] or "0000-00-00"
    slug = slugify(post["title"]) or "untitled"
    return sanitize_filename(f"{date}-{slug}.md")


# -- Export -------------------------------------------------------------------

def export_feed(feed_url: str, force: bool = False) -> tuple[str, list[dict], dict]:
    username = parse_username(feed_url)
    print(f"Fetching feed for @{username}...")

    try:
        xml_bytes = fetch_feed(feed_url)
    except Exception as e:
        print(f"ERROR: Could not fetch feed: {e}", file=sys.stderr)
        sys.exit(1)

    posts = parse_feed(xml_bytes)
    if not posts:
        print("No posts found in feed.")
        return "", [], {"total": 0, "new": 0, "updated": 0, "unchanged": 0, "errors": 0}

    print(f"Found {len(posts)} post(s) in feed")

    output_dir = os.path.join(OUTPUT_BASE, sanitize_filename(username))
    os.makedirs(output_dir, exist_ok=True)

    registry_posts = {} if force else get_existing_post_map(feed_url)
    stats = {"total": len(posts), "new": 0, "updated": 0, "unchanged": 0, "errors": 0}

    for i, post in enumerate(posts, 1):
        guid = post["guid"]
        fname = output_filename(post)
        out_path = os.path.join(output_dir, fname)

        # Incremental: skip if already exported and title/date unchanged
        cached = registry_posts.get(guid)
        if not force and cached and cached.get("title") == post["title"] and os.path.isfile(out_path):
            print(f"  [{i}/{len(posts)}] ⏭️  Unchanged: {post['title'][:60]}")
            post["_exported"] = False
            post["_file_path"] = out_path
            post["_last_exported"] = cached.get("last_exported", "")
            stats["unchanged"] += 1
            continue

        action = "New" if guid not in registry_posts else "Updated"

        try:
            print(f"  [{i}/{len(posts)}] 📄 {action}: {post['title'][:60]}", end="")
            md = post_to_markdown(post)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md)
            post["_exported"] = True
            post["_file_path"] = out_path
            if action == "New":
                stats["new"] += 1
            else:
                stats["updated"] += 1
            print(f" ✓")
        except Exception as e:
            print(f" ✗ ERROR: {e}", file=sys.stderr)
            post["_exported"] = False
            post["_file_path"] = out_path
            stats["errors"] += 1

    return output_dir, posts, stats


# -- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Export Medium posts from an RSS feed to Markdown files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://medium.com/feed/@smnbss
  %(prog)s https://medium.com/feed/@smnbss --force
  %(prog)s --list
        """
    )
    parser.add_argument("url", nargs="?", help="Medium RSS feed URL (e.g., https://medium.com/feed/@username)")
    parser.add_argument("--force", action="store_true", help="Force re-export all posts")
    parser.add_argument("--list", dest="list_registry", action="store_true", help="List previously exported feeds")

    args = parser.parse_args()

    if args.list_registry:
        print_registry()
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    username = parse_username(args.url)
    print(f"Exporting Medium posts for @{username}")
    print(f"Output base: {OUTPUT_BASE}")
    print()

    output_path, posts, stats = export_feed(args.url, force=args.force)

    if not output_path:
        print("\nNo posts exported.")
        sys.exit(0)

    upsert_registry(
        feed_url=args.url,
        username=username,
        output_path=output_path,
        posts=posts,
        stats=stats,
    )

    print()
    print("=" * 50)
    print("Export complete!")
    print(f"  Username: @{username}")
    print(f"  Total posts: {stats['total']}")
    print(f"  New: {stats['new']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Unchanged: {stats['unchanged']}")
    if stats["errors"]:
        print(f"  Errors: {stats['errors']}")
    print(f"  Output: {output_path}")
    print()
    print(f"Registry saved to: {REGISTRY_PATH}")


if __name__ == "__main__":
    main()
