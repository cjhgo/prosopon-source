#!/usr/bin/env python3
"""aesvibe postbuild: OSS-friendly links + privacy defaults.

Quartz emits `foo.html` but links to `/foo`; OSS static hosting has no
nginx `$uri.html` fallback. This script rewrites internal <a href> values
to explicit `.html` / `/index.html`, injects `noindex,nofollow`, writes
robots.txt, and removes build artifacts that should not be public.

Usage: python3 scripts/postbuild.py <public-dir>
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

A_TAG = re.compile(r'(<a\b[^>]*?\bhref=)(["\'])(.*?)\2', re.I | re.S)
HEAD = re.compile(r"(<head\b[^>]*>)", re.I)
SKIP_PREFIX = ("http://", "https://", "//", "mailto:", "tel:", "javascript:", "data:", "#")
KNOWN_EXT = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".xml", ".txt",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif",
    ".mp4", ".webm", ".mov", ".m4v", ".pdf",
    ".woff", ".woff2", ".ttf", ".otf", ".ico",
}
REMOVE = (
    "static/assets-manifest.json",
    "sitemap.xml",
    "index.xml",
    "llms.txt",
    "llms-full.txt",
)
REMOVE_DIRS = (
    "static/telescopic",  # prosopon 定制遗留；aesvibe 不用
    "static/giscus",      # 评论插件已关
)


def fix_href(value: str) -> str:
    if not value or value.startswith(SKIP_PREFIX):
        return value
    m = re.match(r"([^?#]*)([?#].*)?$", value)
    base, tail = m.group(1), m.group(2) or ""
    if not base or base == "/":
        return value
    if base in (".", ".."):
        return f"{base}/index.html{tail}"
    if base.endswith("/"):
        return f"{base}index.html{tail}"
    last = base.rsplit("/", 1)[-1]
    suffix = Path(last).suffix.lower()
    if suffix and suffix in KNOWN_EXT:
        return value
    return f"{base}.html{tail}"


def process_html(path: Path) -> tuple[int, bool]:
    text = path.read_text(encoding="utf-8")
    changed = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal changed
        pre, quote, value = m.group(1), m.group(2), m.group(3)
        new = fix_href(value)
        if new != value:
            changed += 1
        return f"{pre}{quote}{new}{quote}"

    text = A_TAG.sub(repl, text)

    if 'name="robots"' not in text.lower():
        text, n = HEAD.subn(
            r'\1\n<meta name="robots" content="noindex,nofollow">',
            text,
            count=1,
        )
        if n:
            changed += 1

    path.write_text(text, encoding="utf-8")
    return changed, changed > 0


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: postbuild.py <public-dir>")
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")

    html_files = sorted(root.rglob("*.html"))
    total_links = 0
    touched = 0
    for p in html_files:
        n, did = process_html(p)
        total_links += n
        touched += 1 if did else 0

    (root / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    removed = []
    for rel in REMOVE:
        p = root / rel
        if p.is_file():
            p.unlink()
            removed.append(rel)
    for rel in REMOVE_DIRS:
        p = root / rel
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(rel + "/")

    print(
        f"postbuild: {len(html_files)} html, {touched} touched, "
        f"{total_links} link/meta changes"
    )
    if removed:
        print("  removed: " + ", ".join(removed))


if __name__ == "__main__":
    main()
