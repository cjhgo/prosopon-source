#!/usr/bin/env python3
"""note_cover — per-note cover helper (the `genfront.sh` of covers).

The note is the item. This tool does not maintain a dataset:

    find  <note.md>          read frontmatter, show 5 cover candidates
    apply <note.md> --pick 2 download the chosen cover, write cover/cover_source
                             into that note's frontmatter (body untouched)

Examples:
    python3 scripts/covers/note_cover.py find content/mouseion/film/花样年华.md
    python3 scripts/covers/note_cover.py apply content/mouseion/film/花样年华.md --pick 2

Ad-hoc (no note yet):
    python3 scripts/covers/note_cover.py find --type film --title 花样年华 --creator 王家卫 --year 2000

Covers are stored note-anchored:
    content/mouseion/<medium>/image/<note-stem>/cover.webp
frontmatter:
    cover: mouseion/<medium>/image/<note-stem>/cover.webp
    cover_source: neodb:<id>
    cover_status: manual
"""

from __future__ import annotations

import argparse
import datetime
import html
import http.server
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import imageops
import sources
from match import rank_candidates
from store import RateLimiter

HERE = os.path.dirname(os.path.abspath(__file__))
CAND_DIR = os.path.join(HERE, "out", "candidates")
RATE = {"neodb": 1.0, "itunes": 1.0, "openlibrary": 1.2, "wikipedia": 1.0, "tmdb": 0.5}
MEDIUM_BY_DIR = {"books": "book", "book": "book", "film": "film", "films": "film", "music": "music"}
CATEGORY_TAG = {"book": "书", "film": "电影", "music": "音乐"}
REQUIRED = ("title",)


# ---------------- frontmatter ----------------
def default_proxy() -> str:
    """FETCH_PROXY if set, else local 7890 when it is listening, else direct."""
    env = os.environ.get("FETCH_PROXY", "")
    if env:
        return env
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        sock.connect(("127.0.0.1", 7890))
        return "http://127.0.0.1:7890"
    except OSError:
        return ""
    finally:
        sock.close()


def ensure_frontmatter(path: str) -> dict:
    """Create 书影音-specific frontmatter if missing; add medium if absent.

    This deliberately does NOT call genfront.sh: genfront is for general notes.
    """
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---"):
        body = text
        typ = infer_type(path, {})
        title = ""
        m = re.match(r"^#\s+(.+?)\s*$", body, re.M)
        if m:
            title = m.group(1).strip()
            body = body[m.end():].lstrip("\n")
        if not title:
            title = os.path.splitext(os.path.basename(path))[0].replace("-", " ").replace("_", " ")
        fm_text = (
            "---\n"
            f"title: {yaml_value(title)}\n"
            f"medium: {typ}\n"
            f"added: {datetime.date.today().isoformat()}\n"
            f"tags: [\"{CATEGORY_TAG[typ]}\"]\n"
            "raw_tags: []\n"
            "---\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm_text + body)
        return {"title": title, "medium": typ}
    fm, _, _ = split_frontmatter(text)
    updates = {}
    if not fm.get("medium"):
        typ = infer_type(path, fm)
        updates["medium"] = typ
        fm["medium"] = typ
    typ = fm.get("medium") or infer_type(path, fm)
    if not fm.get("tags"):
        updates["tags"] = [CATEGORY_TAG[typ]]
        fm["tags"] = updates["tags"]
    if "raw_tags" not in fm:
        updates["raw_tags"] = []
        fm["raw_tags"] = []
    if updates:
        write_frontmatter(path, updates)
    return fm


def split_frontmatter(text: str) -> tuple[dict, str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        raise ValueError("no YAML frontmatter; run scripts/genfront.sh first")
    fm_text, body = m.group(1), text[m.end():]
    fm: dict = {}
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fm[key] = value
    return fm, body, fm_text


def yaml_value(value) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(json.dumps(str(x), ensure_ascii=False) for x in value) + "]"
    value = str(value)
    if value == "" or re.search(r"[:#\[\]{},&*!|>'\"%@`]|^\s|\s$", value):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_frontmatter(path: str, updates: dict, body: str | None = None) -> None:
    text = open(path, encoding="utf-8").read()
    fm, body_old, fm_text = split_frontmatter(text)
    lines = fm_text.splitlines()
    seen = set()
    for i, line in enumerate(lines):
        if ":" not in line:
            continue
        key = line.partition(":")[0].strip()
        if key in updates:
            lines[i] = f"{key}: {yaml_value(updates[key])}"
            seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}: {yaml_value(value)}")
    new = "---\n" + "\n".join(lines) + "\n---\n" + (body_old if body is None else body)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)


def infer_type(note: str, fm: dict) -> str:
    if fm.get("medium") in ("book", "film", "music"):
        return fm["medium"]
    if fm.get("type") in ("book", "film", "music"):
        return fm["type"]
    for part in os.path.normpath(note).split(os.sep):
        if part in MEDIUM_BY_DIR:
            return MEDIUM_BY_DIR[part]
    raise ValueError("cannot infer medium: put the note under mouseion/books|film|music or set medium:")


def content_root_for(note: str) -> str:
    p = os.path.abspath(note)
    parts = p.split(os.sep)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "content":
            return os.sep.join(parts[: i + 1])
    # fallback: two levels above the note (content/medium/note.md)
    return os.path.dirname(os.path.dirname(p))


# ---------------- search ----------------
def flat_candidates(item: dict, proxy: str, tmdb_key: str, limit: int = 6) -> list[dict]:
    limiter = RateLimiter(RATE)
    all_rows: list[dict] = []
    for source in sources.source_chain(item, tmdb_key):
        queries = [None]
        if source == "neodb":
            q1 = item.get("title", "")
            q2 = " ".join(x for x in (q1, item.get("creator", "")) if x).strip()
            queries = [q1] if q1 == q2 else [q1, q2]
        for query in queries:
            limiter.wait(source)
            try:
                rows = sources.search(source, item, query=query, proxy=proxy, tmdb_key=tmdb_key)
            except Exception:
                rows = []
            if rows:
                all_rows.extend(rows)
                break
        if len(all_rows) >= limit:
            break
    return rank_candidates(item, all_rows)[:limit]


def slug_for(typ: str, name: str) -> str:
    return f"{typ}-" + re.sub(r"[\\/:*?\"<>|\s]+", "-", name).strip("-")


def candidate_sheet(slug: str, item: dict, rows: list[dict]) -> str:
    cards = []
    for i, r in enumerate(rows, 1):
        img = r.get("cover") or ""
        cards.append(
            f'<figure><span class="idx">{i}</span>'
            f'<img src="{html.escape(img)}" loading="lazy" alt="">'
            f'<figcaption><b>{html.escape(r.get("title", ""))}</b>'
            f'<span>{html.escape(str(r.get("year", "")))} · {html.escape(r.get("creator", ""))}</span>'
            f'<em>{r.get("confidence")} · {html.escape(r.get("source", ""))}</em>'
            f'</figcaption></figure>'
        )
    doc = f"""<!doctype html><meta charset="utf-8"><title>candidates · {html.escape(item.get('title',''))}</title>
<style>
body{{margin:0;padding:26px;background:#f3efe5;color:#1e2a2b;font-family:Inter,system-ui,sans-serif}}
h1{{font-family:Georgia,serif;font-weight:500;letter-spacing:.08em;margin:0 0 4px}}
p{{color:#777;font-size:12px;margin:0 0 18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:18px}}
figure{{position:relative;margin:0;background:#faf5ea;padding:8px;box-shadow:0 12px 24px -16px #0008}}
.idx{{position:absolute;left:8px;top:8px;z-index:2;background:#1e2a2b;color:#f3efe5;font:11px monospace;padding:3px 7px}}
img{{width:100%;height:250px;object-fit:contain;display:block;background:#e8e0d0}}
figcaption{{display:flex;flex-direction:column;gap:2px;padding-top:6px;font-size:10px}}
figcaption span{{color:#777;font-size:9px}} figcaption em{{color:#999;font-size:8px;font-style:normal}}
code{{background:#e8e0d0;padding:2px 5px}}
</style>
<h1>{html.escape(item.get('title',''))}</h1>
<p>pick: <code>note_cover.py apply {html.escape(item.get('_note','<note.md>'))} --pick N</code></p>
<div class="grid">{''.join(cards)}</div>"""
    os.makedirs(CAND_DIR, exist_ok=True)
    path = os.path.join(CAND_DIR, f"{slug}.html")
    open(path, "w", encoding="utf-8").write(doc)
    return path


def cmd_find(args) -> int:
    if args.note:
        fm = ensure_frontmatter(args.note)
        item = {
            "type": infer_type(args.note, fm),
            "title": fm.get("title", ""),
            "creator": fm.get("creator", ""),
            "year": fm.get("year", ""),
            "wiki": fm.get("wiki", ""),
            "alt": fm.get("alt", ""),
            "country": fm.get("country", ""),
            "_note": args.note,
        }
        slug = slug_for(item["type"], os.path.splitext(os.path.basename(args.note))[0])
    else:
        if not args.title:
            print("find: need <note.md> or --title", file=sys.stderr)
            return 2
        item = {
            "type": args.type or "book",
            "title": args.title,
            "creator": args.creator or "",
            "year": args.year or "",
            "wiki": args.wiki or "",
            "_note": "<note.md>",
        }
        slug = slug_for(item["type"], args.title)
    if not item["title"]:
        print("title is empty in frontmatter", file=sys.stderr)
        return 2

    rows = flat_candidates(item, args.proxy, args.tmdb_key, args.limit)
    if not rows:
        print("no candidates")
        return 1
    os.makedirs(CAND_DIR, exist_ok=True)
    json_path = os.path.join(CAND_DIR, f"{slug}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"item": item, "candidates": rows}, f, ensure_ascii=False, indent=1)
    sheet = candidate_sheet(slug, item, rows)
    print(f"{item['title']}  ({item['type']})")
    for i, r in enumerate(rows, 1):
        print(f"  [{i}] {r.get('confidence'):<5} {r.get('source'):12} {r.get('title','')[:40]}  {r.get('year','')}")
    print(f"\ncandidates: {json_path}")
    print(f"sheet:      {sheet}")
    print(f"apply:      python3 {os.path.relpath(__file__)} apply {args.note or '<note.md>'} --pick N")
    return 0


def _image_ext(path: str) -> str:
    head = open(path, "rb").read(12)
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"RIFF"):
        return ".webp"
    if head.startswith(b"GIF8"):
        return ".gif"
    return ".bin"


def apply_candidate(note: str, cand: dict, proxy: str = "", force: bool = True, status: str = "manual") -> tuple[str, str]:
    """Download one candidate and write it into the note. Returns (rel_path, cover_path)."""
    fm, _, _ = split_frontmatter(open(note, encoding="utf-8").read())
    if fm.get("cover") and not force:
        raise RuntimeError(f"note already has cover: {fm['cover']}")
    typ = infer_type(note, fm)
    note_abs = os.path.abspath(note)
    root = content_root_for(note_abs)
    stem = os.path.splitext(os.path.basename(note_abs))[0]
    dest_dir = os.path.join(os.path.dirname(note_abs), "image", stem)
    os.makedirs(dest_dir, exist_ok=True)
    raw = os.path.join(dest_dir, "cover.raw")
    dest = os.path.join(dest_dir, "cover.webp")
    imageops.download(cand["cover"], raw, referer=cand.get("referer"), proxy=proxy)
    cover_path = imageops.to_webp(raw, dest, 700 if typ == "music" else 560)
    try:
        os.remove(raw)
    except OSError:
        pass
    rel = os.path.relpath(cover_path, root)
    write_frontmatter(
        note,
        {
            "cover": rel,
            "cover_source": f"{cand.get('source','')}:{cand.get('id','')}",
            "cover_status": status,
        },
    )
    # also put the image in the markdown body (note-relative path)
    _, body, _ = split_frontmatter(open(note, encoding="utf-8").read())
    body_rel = os.path.relpath(cover_path, os.path.dirname(note_abs))
    write_frontmatter(note, {}, upsert_cover_image(body, body_rel))
    return rel, cover_path


def cmd_apply(args) -> int:
    note = args.note
    fm = ensure_frontmatter(note)
    if fm.get("cover") and not args.force:
        print(f"note already has cover: {fm['cover']} (use --force to replace)", file=sys.stderr)
        return 2
    typ = infer_type(note, fm)
    slug = slug_for(typ, os.path.splitext(os.path.basename(note))[0])
    json_path = os.path.join(CAND_DIR, f"{slug}.json")
    if not os.path.exists(json_path):
        print(f"no candidates for {slug}; run: note_cover.py find {note}", file=sys.stderr)
        return 2
    data = json.load(open(json_path, encoding="utf-8"))
    rows = data.get("candidates") or []
    idx = args.pick
    if idx < 1 or idx > len(rows):
        print(f"--pick must be 1..{len(rows)}", file=sys.stderr)
        return 2
    cand = rows[idx - 1]
    if not cand.get("cover"):
        print("chosen candidate has no cover url", file=sys.stderr)
        return 2
    try:
        rel, _ = apply_candidate(note, cand, args.proxy, force=True)
        print(f"cover written: {rel}")
        print(f"source: {cand.get('source')}:{cand.get('id')}  ({cand.get('title')})")
        return 0
    except Exception as exc:
        print(f"download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _localized(rows, lang: str = "zh-cn") -> str:
    for row in rows or []:
        if row.get("lang") == lang:
            text = str(row.get("text", "")).strip()
            if text:
                return text
    for row in rows or []:
        if str(row.get("lang", "")).startswith("zh"):
            text = str(row.get("text", "")).strip()
            if text:
                return text
    return ""


def _clean_tags(raw, typ: str) -> list[str]:
    skip = {
        "电影", "movie", "film", "music", "book", "图书", "音乐", "cn", "hk", "us", "cc",
        "中国", "中国大陆", "中国香港", "香港", "台湾", "中国台湾", "日本", "美国", "法国",
        "德国", "意大利", "英国", "韩国", "内地", "地区 大陆", "大陆", "男声", "女声",
    }
    out = []
    for tag in raw or []:
        t = str(tag).strip()
        if not t or re.fullmatch(r"\d{4}s?", t) or t.lower() in skip:
            continue
        if t not in out:
            out.append(t)
    return out[:8]


def _external_links(detail: dict) -> dict:
    links = {}
    for row in detail.get("external_resources") or []:
        url = str(row.get("url", ""))
        if "douban.com" in url:
            links["douban"] = url
        elif "imdb.com" in url:
            links["imdb"] = url
        elif "themoviedb.org" in url:
            links["tmdb"] = url
        elif "openlibrary.org" in url:
            links["openlibrary"] = url
    return links


def build_meta(cand: dict, typ: str, proxy: str = "") -> dict:
    detail = {}
    if cand.get("source") == "neodb":
        try:
            detail = sources.neodb_detail(cand, typ, proxy=proxy)
        except Exception:
            detail = {}
    credits = detail.get("credits") or []

    def names(role: str) -> list[str]:
        return [str(c.get("name")) for c in credits if c.get("role") == role and c.get("name")]

    description = _localized(detail.get("localized_description"), "zh-cn") or str(
        detail.get("description") or cand.get("raw") or ""
    ).strip()
    tags = _clean_tags(detail.get("tags"), typ)
    credit_slugs = set()
    for c in credits:
        slug = re.sub(r"[^a-z0-9]", "", str(c.get("name", "")).lower())
        if slug:
            credit_slugs.add(slug)
    tags = [
        t for t in tags
        if "_" not in t and re.sub(r"[^a-z0-9]", "", t.lower()) not in credit_slugs
    ]
    meta = {
        "description": description,
        "tags": tags,
        "neodb_rating": detail.get("rating") or cand.get("rating"),
        "source_url": cand.get("url", ""),
        "original_title": detail.get("orig_title") or "",
        "creator": "",
        "year": str(cand.get("year") or ""),
    }
    if typ == "film":
        directors = names("director")
        meta.update(
            {
                "director": directors[0] if directors else "",
                "cast": names("actor")[:6],
                "genres": detail.get("genre") or [],
                "release_date": detail.get("release_date") or "",
                "year": (detail.get("release_date") or "")[:4] or meta["year"],
                "creator": directors[0] if directors else cand.get("creator", ""),
            }
        )
        meta["country"] = next((t for t in tags if t in ("中国", "中国香港", "中国台湾", "美国", "日本", "法国", "德国", "意大利", "英国", "韩国")), "")
    elif typ == "book":
        authors = detail.get("author") or names("author")
        publishers = detail.get("publisher") or names("publisher")
        meta.update(
            {
                "author": authors[:3],
                "publisher": publishers[:2],
                "isbn": detail.get("isbn") or "",
                "pages": detail.get("pages") or "",
                "year": str(detail.get("pub_year") or "") or meta["year"],
                "creator": authors[0] if authors else cand.get("creator", ""),
            }
        )
    else:
        artists = detail.get("artist") or names("artist")
        labels = detail.get("company") or names("record_label")
        meta.update(
            {
                "artist": artists[:3],
                "label": labels[:2],
                "genres": detail.get("genre") or [],
                "release_date": detail.get("release_date") or "",
                "track_count": len(detail.get("track_list") or []),
                "year": (detail.get("release_date") or "")[:4] or meta["year"],
                "creator": artists[0] if artists else cand.get("creator", ""),
            }
        )
    meta.update(_external_links(detail))
    return meta


def _short(text: str, n: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:n].rstrip() + ("…" if len(text) > n else "")


COVER_BEGIN = "<!-- gencover:cover:begin -->"
COVER_END = "<!-- gencover:cover:end -->"


def upsert_cover_image(body: str, rel_path: str) -> str:
    """Put the cover at the top of the note body, idempotently.

    URL-encode spaces/parentheses/CJK: Markdown link destinations cannot contain
    unescaped spaces, and the local/OSS asset pipeline decodes them back.
    """
    rel_path = urllib.parse.quote(rel_path.replace(os.sep, "/"), safe="/")
    block = f"{COVER_BEGIN}\n![cover]({rel_path})\n{COVER_END}"
    if COVER_BEGIN in body and COVER_END in body:
        pre = body[: body.index(COVER_BEGIN)]
        post = body[body.index(COVER_END) + len(COVER_END):]
        return pre + block + post
    if f"![cover]({rel_path})" in body:
        return body
    body = body.lstrip("\n")
    return (block + "\n\n" + body) if body else block + "\n"


def render_background(typ: str, meta: dict) -> str:
    heading = {"film": "背景", "book": "内容简介", "music": "专辑简介"}.get(typ, "背景")
    lines = ["<!-- gencover:begin -->", f"## {heading}", ""]
    desc = str(meta.get("description") or "").strip()
    if desc:
        lines += [desc[:4000], ""]
    bullets = []
    if typ == "film":
        if meta.get("director"):
            bullets.append(f"- 导演：{meta['director']}")
        if meta.get("cast"):
            bullets.append("- 主演：" + "、".join(meta["cast"][:4]))
        if meta.get("release_date"):
            bullets.append(f"- 上映：{meta['release_date']}")
        if meta.get("genres"):
            bullets.append("- 类型：" + "、".join(meta["genres"]))
        if meta.get("country"):
            bullets.append(f"- 地区：{meta['country']}")
    elif typ == "book":
        if meta.get("author"):
            bullets.append("- 作者：" + "、".join(meta["author"]))
        if meta.get("publisher"):
            bullets.append("- 出版：" + "、".join(meta["publisher"]))
        if meta.get("year"):
            bullets.append(f"- 年份：{meta['year']}")
        if meta.get("isbn"):
            bullets.append(f"- ISBN：{meta['isbn']}")
        if meta.get("pages"):
            bullets.append(f"- 页数：{meta['pages']}")
    else:
        if meta.get("artist"):
            bullets.append("- 艺人：" + "、".join(meta["artist"]))
        if meta.get("label"):
            bullets.append("- 厂牌：" + "、".join(meta["label"]))
        if meta.get("release_date"):
            bullets.append(f"- 发行：{meta['release_date']}")
        if meta.get("genres"):
            bullets.append("- 类型：" + "、".join(meta["genres"]))
        if meta.get("track_count"):
            bullets.append(f"- 曲目：{meta['track_count']}")
    if meta.get("neodb_rating"):
        bullets.append(f"- 评分：{meta['neodb_rating']}（NeoDB）")
    links = []
    if meta.get("source_url"):
        links.append(f"[NeoDB]({meta['source_url']})")
    for key, label in (("douban", "Douban"), ("imdb", "IMDb"), ("tmdb", "TMDB"), ("openlibrary", "Open Library")):
        if meta.get(key):
            links.append(f"[{label}]({meta[key]})")
    if links:
        bullets.append("- 资料：" + " · ".join(dict.fromkeys(links)))
    lines += bullets + ["", "<!-- gencover:end -->"]
    return "\n".join(lines)


def upsert_background(body: str, block: str) -> str:
    begin, end = "<!-- gencover:begin -->", "<!-- gencover:end -->"
    if begin in body and end in body:
        pre = body[: body.index(begin)]
        post = body[body.index(end) + len(end):]
        return pre + block + post
    body = body.rstrip()
    return (body + "\n\n" if body else "") + block + "\n"


def enrich_note(note: str, cand: dict, proxy: str = "") -> dict:
    fm, body, _ = split_frontmatter(open(note, encoding="utf-8").read())
    typ = infer_type(note, fm)
    if fm.get("cover"):
        cover_abs = os.path.join(content_root_for(note), fm["cover"])
        body = upsert_cover_image(body, os.path.relpath(cover_abs, os.path.dirname(os.path.abspath(note))))
    meta = build_meta(cand, typ, proxy)
    updates = {}

    def add(key, value):
        if value in (None, "", [], {}):
            return
        existing = fm.get(key)
        if existing and existing not in ("[]", "{}", "''", '""'):
            return
        updates[key] = value

    add("medium", typ)
    add("creator", meta.get("creator"))
    add("year", meta.get("year"))
    add("description", _short(meta.get("description")))
    add("raw_tags", meta.get("tags"))
    add("tags", [CATEGORY_TAG[typ]])
    add("source", cand.get("source"))
    add("source_id", cand.get("id"))
    add("source_url", meta.get("source_url"))
    for key in (
        "original_title", "director", "cast", "genres", "release_date", "country",
        "author", "publisher", "isbn", "pages", "artist", "label", "track_count",
        "neodb_rating", "douban", "imdb", "tmdb", "openlibrary",
    ):
        add(key, meta.get(key))
    block = render_background(typ, meta)
    body_new = upsert_background(body, block)
    write_frontmatter(note, updates, body_new)
    return meta


def cmd_enrich(args) -> int:
    fm = ensure_frontmatter(args.note)
    typ = infer_type(args.note, fm)
    slug = slug_for(typ, os.path.splitext(os.path.basename(args.note))[0])
    data = json.load(open(os.path.join(CAND_DIR, f"{slug}.json"), encoding="utf-8"))
    rows = data.get("candidates") or []
    target = fm.get("cover_source", "")
    cand = next((r for r in rows if f"{r.get('source')}:{r.get('id')}" == target), rows[0] if rows else None)
    if not cand:
        print("no candidate to enrich from", file=sys.stderr)
        return 2
    meta = enrich_note(args.note, cand, args.proxy)
    print(f"enriched: {args.note}")
    print(f"  {len(meta.get('tags') or [])} tags, description {len(meta.get('description') or '')} chars")
    return 0


def _prepare_thumbs(rows: list[dict], slug: str, proxy: str) -> None:
    d = os.path.join(CAND_DIR, slug)
    os.makedirs(d, exist_ok=True)
    for i, r in enumerate(rows, 1):
        raw = os.path.join(d, f"thumb{i}.raw")
        try:
            imageops.download(r["cover"], raw, referer=r.get("referer"), proxy=proxy)
            dst = imageops.to_webp(raw, os.path.join(d, f"thumb{i}.webp"), 420)
            try:
                os.remove(raw)
            except OSError:
                pass
            r["_thumb"] = dst
        except Exception:
            r["_thumb"] = ""


def _serve_page(item: dict, note: str, rows: list[dict], current_cover: str) -> str:
    cards = []
    for i, r in enumerate(rows, 1):
        thumb = r.get("_thumb")
        if thumb and os.path.exists(thumb):
            img = f'<img src="/thumb/{i}" alt="">'
        elif r.get("cover"):
            img = f'<img src="{html.escape(r["cover"])}" alt="">'
        else:
            img = '<div class="ph">NO IMAGE</div>'
        source_url = r.get("url") or r.get("cover") or ""
        cards.append(
            f'<article class="cand"><span class="idx">{i}</span>'
            f'<a class="shot" href="/source/{i}" target="_blank">{img}</a>'
            f'<h2>{html.escape(r.get("title", ""))}</h2>'
            f'<p>{html.escape(str(r.get("year", "")))} · {html.escape(r.get("creator", ""))}</p>'
            f'<div class="meta"><span class="conf">{r.get("confidence")}</span>'
            f'<span class="src">{html.escape(r.get("source", ""))}</span></div>'
            f'<a class="source" href="/source/{i}" target="_blank">source ↗</a>'
            f'<form method="post" action="/apply"><input type="hidden" name="pick" value="{i}">'
            f'<button>Use this cover</button></form></article>'
        )
    current = ""
    if current_cover:
        current = (
            '<div class="current"><img src="/current" alt="current cover">'
            '<div><b>Current cover</b><span>' + html.escape(current_cover) + "</span>"
            "<em>Choosing another will replace it.</em></div></div>"
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Choose a cover · {html.escape(item.get('title',''))}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500&family=Inter:wght@400;500&display=swap');
:root{{--paper:#f3efe5;--ink:#1e2a2b;--muted:#74776c;--line:#d3caba;--celadon:#2f8296;--ochre:#b3763a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,system-ui,sans-serif}}
.wrap{{max-width:1120px;margin:0 auto;padding:36px 28px 60px}}
header{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}}
h1{{font-family:"Cormorant Garamond",Georgia,serif;font-weight:500;font-size:40px;letter-spacing:.1em;margin:0}}
.kicker{{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);margin-top:6px}}
.note{{font-size:9px;color:var(--muted);text-align:right;max-width:46%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.current{{display:flex;gap:14px;align-items:center;background:#ece5d6;border:1px solid var(--line);padding:10px;margin-bottom:18px}}
.current img{{height:84px;width:auto;display:block}}
.current div{{display:flex;flex-direction:column;gap:2px;font-size:11px}}
.current b{{font-family:"Cormorant Garamond",serif;font-size:16px;letter-spacing:.08em}} .current span{{color:var(--muted);font-size:9px}} .current em{{color:var(--ochre);font-size:9px;font-style:normal}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:18px}}
.cand{{position:relative;background:#faf5ea;border:1px solid var(--line);padding:8px;display:flex;flex-direction:column;gap:6px}}
.idx{{position:absolute;left:8px;top:8px;z-index:2;background:var(--ink);color:var(--paper);font:10px monospace;padding:3px 6px}}
.shot{{display:block;height:270px;background:#e7dfd0;overflow:hidden;text-align:center}}
.shot img{{height:100%;max-width:100%;object-fit:contain;display:block;margin:0 auto}}
.ph{{height:100%;display:grid;place-items:center;color:#999;font-size:10px}}
h2{{font-family:"Songti SC",serif;font-size:10px;font-weight:600;margin:2px 0 0;line-height:1.3;max-height:28px;overflow:hidden}}
.cand p{{margin:0;font-size:8px;color:var(--muted)}}
.meta{{display:flex;gap:8px;align-items:center;font-size:8px}}
.conf{{background:var(--ink);color:var(--paper);padding:2px 5px;font-family:monospace}}
.src{{color:var(--muted);letter-spacing:.08em;text-transform:uppercase}}
.source{{font-size:8px;color:var(--celadon);text-decoration:none;border-bottom:1px solid transparent;align-self:flex-start}}
.source:hover{{border-color:var(--celadon)}}
button{{margin-top:auto;width:100%;background:var(--ink);color:var(--paper);border:0;padding:8px;font-size:9px;letter-spacing:.14em;text-transform:uppercase;cursor:pointer}}
button:hover{{background:var(--celadon)}}
footer{{margin-top:24px;font-size:8px;letter-spacing:.14em;color:var(--muted);text-transform:uppercase}}
</style></head><body><div class="wrap">
<header><div><h1>Choose a cover</h1><div class="kicker">{html.escape(item.get('type',''))} · {html.escape(item.get('title',''))}</div></div><div class="note">{html.escape(note)}</div></header>
{current}
<div class="grid">{''.join(cards)}</div>
<footer>Candidates: NeoDB · TMDB · Open Library · iTunes</footer>
</div></body></html>"""


def make_handler(note: str, item: dict, rows: list[dict], proxy: str, enrich: bool = False, exit_after_apply: bool = False):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body, ctype: str = "text/html; charset=utf-8"):
            b = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _current_path(self):
            fm, _, _ = split_frontmatter(open(note, encoding="utf-8").read())
            cover = fm.get("cover", "")
            if not cover:
                return ""
            return os.path.join(content_root_for(note), cover)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                fm, _, _ = split_frontmatter(open(note, encoding="utf-8").read())
                self._send(200, _serve_page(item, note, rows, fm.get("cover", "")))
            elif path.startswith("/thumb/"):
                i = int(path.split("/")[-1])
                p = rows[i - 1].get("_thumb") if 0 < i <= len(rows) else ""
                if p and os.path.exists(p):
                    self._send(200, open(p, "rb").read(), mimetypes.guess_type(p)[0] or "image/jpeg")
                else:
                    self._send(404, "no thumb")
            elif path == "/current":
                p = self._current_path()
                if p and os.path.exists(p):
                    self._send(200, open(p, "rb").read(), mimetypes.guess_type(p)[0] or "image/jpeg")
                else:
                    self._send(404, "no cover")
            elif path.startswith("/source/"):
                i = int(path.split("/")[-1])
                url = (rows[i - 1].get("url") or rows[i - 1].get("cover") or "") if 0 < i <= len(rows) else ""
                if not url:
                    self._send(404, "no source")
                    return
                self.send_response(302)
                self.send_header("Location", url)
                self.end_headers()
            else:
                self._send(404, "not found")

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/apply":
                self._send(404, "not found")
                return
            length = int(self.headers.get("Content-Length", "0"))
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            try:
                pick = int(form.get("pick", ["0"])[0])
            except ValueError:
                self._send(400, "bad pick")
                return
            if pick < 1 or pick > len(rows):
                self._send(400, "bad pick")
                return
            cand = rows[pick - 1]
            try:
                rel, _ = apply_candidate(note, cand, proxy, force=True)
                enrich_line = ""
                if enrich:
                    try:
                        meta = enrich_note(note, cand, proxy)
                        enrich_line = (
                            f"<p class='ok'>frontmatter + 背景已补："
                            f"{len(meta.get('tags') or [])} tags，"
                            f"{len(meta.get('description') or '')} 字简介</p>"
                        )
                    except Exception as exc:
                        enrich_line = f"<p class='warn'>enrich 失败：{html.escape(type(exc).__name__ + ': ' + str(exc))}</p>"
                body = f"""<!doctype html><meta charset="utf-8"><title>Cover applied</title>
<style>body{{margin:0;background:#f3efe5;color:#1e2a2b;font-family:Inter,sans-serif;display:grid;place-items:center;min-height:100vh}}
.card{{text-align:center;max-width:420px;padding:28px}} img{{max-height:360px;max-width:100%;box-shadow:0 18px 40px -20px #0008}}
h1{{font-family:Georgia,serif;font-weight:500;font-size:28px;letter-spacing:.08em}} p{{font-size:11px;color:#777}} p.ok{{color:#2f8296}} p.warn{{color:#b3763a}} a{{display:inline-block;margin-top:18px;background:#1e2a2b;color:#f3efe5;padding:9px 16px;text-decoration:none;font-size:10px;letter-spacing:.14em;text-transform:uppercase}}</style>
<div class="card"><img src="/current?t={int(time.time())}" alt=""><h1>Cover applied</h1>
<p>{html.escape(rel)}<br>{html.escape(cand.get('source',''))}:{html.escape(str(cand.get('id','')))}</p>
{enrich_line}
<a href="/">Back to candidates</a></div>"""
                self._send(200, body)
                if exit_after_apply:
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            except Exception as exc:
                self._send(500, f"<pre>{html.escape(type(exc).__name__ + ': ' + str(exc))}</pre>")

    return Handler


def cmd_auto(args) -> int:
    """Non-interactive: take the top-ranked candidate, apply, enrich."""
    note = args.note
    fm = ensure_frontmatter(note)
    typ = infer_type(note, fm)
    item = {
        "type": typ,
        "title": fm.get("title", ""),
        "creator": fm.get("creator", ""),
        "year": fm.get("year", ""),
        "wiki": fm.get("wiki", ""),
        "alt": fm.get("alt", ""),
        "country": fm.get("country", ""),
        "_note": note,
    }
    if not item["title"]:
        print("auto: title is empty", file=sys.stderr)
        return 2
    rows = flat_candidates(item, args.proxy, args.tmdb_key, args.limit)
    if not rows:
        print("auto: no candidates", file=sys.stderr)
        return 1
    slug = slug_for(typ, os.path.splitext(os.path.basename(note))[0])
    os.makedirs(CAND_DIR, exist_ok=True)
    with open(os.path.join(CAND_DIR, f"{slug}.json"), "w", encoding="utf-8") as f:
        json.dump({"item": item, "candidates": rows}, f, ensure_ascii=False, indent=1)
    top = rows[0]
    if not top.get("cover"):
        print("auto: top candidate has no cover", file=sys.stderr)
        return 1
    print(
        f"auto: {item['title']} -> {top.get('title')} "
        f"({top.get('source')} {top.get('confidence')})"
    )
    if top.get("confidence", 0) < 0.75:
        print("warning: top confidence is low; run `serve` to pick manually", file=sys.stderr)
    if fm.get("cover") and not args.force:
        print("note already has cover; enriching only (use --force to replace)")
    else:
        try:
            rel, _ = apply_candidate(note, top, args.proxy, force=True, status="auto")
            print(f"cover: {rel}")
        except Exception as exc:
            print(f"auto: cover download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    try:
        meta = enrich_note(note, top, args.proxy)
        print(
            f"enriched: {len(meta.get('tags') or [])} tags, "
            f"{len(meta.get('description') or '')} chars description"
        )
    except Exception as exc:
        print(f"auto: enrich failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args) -> int:
    fm = ensure_frontmatter(args.note)
    item = {
        "type": infer_type(args.note, fm),
        "title": fm.get("title", ""),
        "creator": fm.get("creator", ""),
        "year": fm.get("year", ""),
        "wiki": fm.get("wiki", ""),
        "alt": fm.get("alt", ""),
        "country": fm.get("country", ""),
        "_note": args.note,
    }
    rows = flat_candidates(item, args.proxy, args.tmdb_key, args.limit)
    if not rows:
        print("no candidates", file=sys.stderr)
        return 1
    slug = slug_for(item["type"], os.path.splitext(os.path.basename(args.note))[0])
    os.makedirs(CAND_DIR, exist_ok=True)
    json_path = os.path.join(CAND_DIR, f"{slug}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"item": item, "candidates": rows}, f, ensure_ascii=False, indent=1)
    _prepare_thumbs(rows, slug, args.proxy)
    handler = make_handler(args.note, item, rows, args.proxy, enrich=args.enrich, exit_after_apply=args.exit_after_apply)
    port = args.port
    server = None
    for candidate in ([port] if port else [0, 8765, 8766, 8767, 8768]):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            break
        except OSError:
            continue
    if not server:
        print("could not bind a local port", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"cover picker: {url}")
    print(f"note:         {args.note}")
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("picker closed")
    return 0

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="per-note cover helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="show cover candidates for one note")
    f.add_argument("note", nargs="?", help="path to the note (frontmatter is the input)")
    f.add_argument("--type", choices=["book", "film", "music"])
    f.add_argument("--title")
    f.add_argument("--creator", default="")
    f.add_argument("--year", default="")
    f.add_argument("--wiki", default="")
    f.add_argument("--limit", type=int, default=5)
    f.add_argument("--proxy", default=default_proxy())
    f.add_argument("--tmdb-key", default=os.environ.get("TMDB_API_KEY", ""))
    f.set_defaults(func=cmd_find)

    a = sub.add_parser("apply", help="download the chosen candidate into the note")
    a.add_argument("note")
    a.add_argument("--pick", type=int, required=True)
    a.add_argument("--force", action="store_true")
    a.add_argument("--proxy", default=default_proxy())
    a.set_defaults(func=cmd_apply)

    au = sub.add_parser("auto", help="non-interactive: pick the top-ranked candidate")
    au.add_argument("note")
    au.add_argument("--limit", type=int, default=5)
    au.add_argument("--force", action="store_true")
    au.add_argument("--proxy", default=default_proxy())
    au.add_argument("--tmdb-key", default=os.environ.get("TMDB_API_KEY", ""))
    au.set_defaults(func=cmd_auto)

    srv = sub.add_parser("serve", help="open a visual picker in the browser")
    srv.add_argument("note")
    srv.add_argument("--limit", type=int, default=5)
    srv.add_argument("--port", type=int, default=0)
    srv.add_argument("--proxy", default=default_proxy())
    srv.add_argument("--tmdb-key", default=os.environ.get("TMDB_API_KEY", ""))
    srv.add_argument("--no-open", action="store_true")
    srv.add_argument("--enrich", action="store_true", help="after picking, fill frontmatter + background body")
    srv.add_argument("--exit-after-apply", action="store_true", help="stop the server after a successful pick")
    srv.set_defaults(func=cmd_serve)

    en = sub.add_parser("enrich", help="re-fill metadata/background for an already-picked note")
    en.add_argument("note")
    en.add_argument("--proxy", default=default_proxy())
    en.set_defaults(func=cmd_enrich)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
