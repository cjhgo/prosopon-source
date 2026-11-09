#!/usr/bin/env python3
"""migrate_music_to_songs — 专辑级 mouseion/music 条目 → 歌曲级条目。

心智模型(2026-11-09 定): 流媒体之后, 歌是基本单位, 专辑只是统计维度。
  - 一个 md = 一首歌(按标题聚合的"作品"), 同名多版本/多艺人放同一个 md
  - 专辑不再是实体, 下沉为字段: album / album_id / album_year /
    album_cover / album_rating / album_intro
  - 合并口径: 标题(去尾部括号)相同 = 同一作品; 若将来遇到同名不同作品,
    用「标题（艺人）」做文件名消歧(脚本会检测冲突并告警)

数据来源:
  - 歌单缓存 (~/.cache/prosopon/netease-<id>.json): 曲目/歌手/专辑/时长/单曲 id
  - 既有 324 篇专辑条目: 专辑简介/评分/封面/厂牌/tags

用法:
  python3 scripts/migrate_music_to_songs.py --dry-run
  python3 scripts/migrate_music_to_songs.py
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "covers"))
import note_cover as nc  # noqa: E402

ROOT = os.path.dirname(HERE)
MUSIC_DIR = os.path.join(ROOT, "content", "mouseion", "music")
CACHE = os.path.expanduser("~/.cache/prosopon/netease-28868179.json")
PLAYLIST_ID = "28868179"


def norm_key(text: str | None) -> str:
    s = re.sub(r"[\(（\[【].*?[\)）\]】]", "", str(text or ""))
    s = re.sub(r"[^\w㐀-鿿]+", "", s.lower())
    return s


def base_title(name: str) -> str:
    """去掉尾部括号(版本/影视说明)得到作品名; 只在尾部去, 避免吃掉标题一部分。"""
    t = re.sub(r"\s*[\(（\[【][^\)）\]】]*[\)）\]】]\s*$", "", str(name or "")).strip()
    return t or str(name or "").strip()


def fmt_duration(ms: int | None, fallback: str = "") -> str:
    if not ms:
        return fallback
    s = int(round(ms / 1000))
    return f"{s // 60:02d}:{s % 60:02d}"


def safe_stem(title: str) -> str:
    table = {
        "/": "／", "\\": "＼", ":": "：", "*": "＊", "?": "？", '"': "＂",
        "<": "＜", ">": "＞", "|": "｜", "%": "％", "#": "＃",
    }
    stem = "".join(table.get(ch, ch) for ch in title).strip()
    return stem[:60] or "untitled"


def read_album_notes() -> dict[str, dict]:
    """既有专辑条目: 专辑名 → 元数据(含正文里的完整简介)。"""
    out: dict[str, dict] = {}
    for name in os.listdir(MUSIC_DIR):
        if not name.endswith(".md") or name == "index.md":
            continue
        path = os.path.join(MUSIC_DIR, name)
        text = open(path, encoding="utf-8").read()
        fm, body, _ = nc.split_frontmatter(text)
        title = (fm.get("title") or "").replace('\\"', '"')
        if not title:
            continue
        intro = ""
        m = re.search(
            r"## 专辑简介\n\n(.*?)(?=\n- (?:艺人|专辑|厂牌|发行|类型|曲目|评分|资料)：|\n<!-- gencover:end -->|\Z)",
            body,
            re.S,
        )
        if m:
            intro = m.group(1).strip()
        out[title] = {
            "path": path,
            "title": title,
            "creator": fm.get("creator", ""),
            "year": fm.get("year", ""),
            "description": fm.get("description", ""),
            "intro": intro,
            "cover": fm.get("cover", ""),
            "cover_source": fm.get("cover_source", ""),
            "cover_status": fm.get("cover_status", ""),
            "neodb_rating": fm.get("neodb_rating", ""),
            "genres": fm.get("genres", ""),
            "label": fm.get("label", ""),
            "release_date": fm.get("release_date", ""),
            "douban": fm.get("douban", ""),
            "raw_tags": fm.get("raw_tags", ""),
            "tags": fm.get("tags", ""),
            "source": fm.get("source", ""),
            "source_id": fm.get("source_id", ""),
            "source_url": fm.get("source_url", ""),
            "tracks": parse_tracks(body),
        }
    return out


def parse_tracks(body: str) -> list[dict]:
    """从 `## 曲目` / `## 版本` 段解析曲名/链接/时长(用于非歌单条目)。"""
    tracks = []
    m = re.search(r"## (?:曲目|版本)\n(.*?)(?=\n## |\n<!-- (?:gencover|music):|\Z)", body, re.S)
    if not m:
        return tracks
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        mm = re.match(r"^- \[(.+?)\]\((https://music\.163\.com/#/song\?id=\d+)\)(?: — .*?)? — (\d\d:\d\d)$", line)
        if mm:
            tracks.append({"name": mm.group(1), "url": mm.group(2), "duration": mm.group(3)})
            continue
        mm = re.match(r"^- (.+?)(?: — .*?)? — (\d\d:\d\d)$", line)
        if mm:
            tracks.append({"name": mm.group(1).replace("**", ""), "url": None, "duration": mm.group(2)})
    return tracks


def load_playlist_songs() -> list[dict]:
    data = json.load(open(CACHE, encoding="utf-8"))
    return data["songs"]


def build_groups(songs: list[dict], album_notes: dict[str, dict]) -> list[dict]:
    """按 base title 聚合版本。"""
    groups: dict[str, dict] = collections.OrderedDict()

    def add_version(version: dict):
        key = norm_key(base_title(version["name"])) or version["name"]
        group = groups.setdefault(
            key, {"title": base_title(version["name"]), "versions": [], "album_meta": None}
        )
        # 同一首歌(id 相同)不重复
        if version.get("song_id") and any(v.get("song_id") == version["song_id"] for v in group["versions"]):
            return
        group["versions"].append(version)

    for song in songs:
        album = song.get("album") or {}
        artists = [a.get("name") or "" for a in song.get("artists") or []]
        publish = album.get("publishTime")
        year = str(datetime.datetime.fromtimestamp(publish / 1000).year) if publish else ""
        add_version(
            {
                "name": song.get("name") or "",
                "artist": " / ".join(artists),
                "album": album.get("name") or "",
                "album_id": album.get("id"),
                "song_id": song.get("id"),
                "duration": fmt_duration(song.get("duration")),
                "year": year,
            }
        )

    # 非歌单条目(旧条目里的曲目)补进来; 已在歌单里的 song_id 自动去重
    for album in album_notes.values():
        if not album["tracks"]:
            continue
        for track in album["tracks"]:
            song_id = None
            if track.get("url"):
                m = re.search(r"id=(\d+)", track["url"])
                song_id = int(m.group(1)) if m else None
            add_version(
                {
                    "name": track["name"],
                    "artist": album["creator"],
                    "album": album["title"],
                    "album_id": None,
                    "song_id": song_id,
                    "duration": track["duration"],
                    "year": album["year"],
                    "_album_note": album["title"],
                }
            )

    # 关联专辑元数据(先精确, 再去括号/标点归一)
    by_exact = album_notes
    by_norm = {norm_key(k): v for k, v in album_notes.items()}
    for group in groups.values():
        primary = group["versions"][0]
        note = by_exact.get(primary["album"]) or by_norm.get(norm_key(primary["album"]))
        if not note and primary.get("_album_note"):
            note = by_exact.get(primary["_album_note"])
        group["album_meta"] = note
        group["primary"] = primary
        group["title"] = base_title(primary["name"])
    return list(groups.values())


def parse_list(value) -> list[str]:
    """把 frontmatter 里的 ["a", "b"] 字符串还原成 Python list。"""
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text.replace("'", '"'))
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except Exception:
            return [x.strip().strip("\"'") for x in text.strip("[]").split(",") if x.strip()]
    return [text]


def render_note(group: dict, keep_album_note: dict | None) -> tuple[str, str]:
    primary = group["primary"]
    meta = group["album_meta"] or {}
    title = group["title"]
    album_name = primary["album"] or meta.get("title", "")
    album_id = primary.get("album_id") or meta.get("source_id")
    if isinstance(album_id, str) and not album_id.isdigit():
        album_id = None
    album_url = f"https://music.163.com/#/album?id={album_id}" if album_id else ""
    song_url = f"https://music.163.com/#/song?id={primary['song_id']}" if primary.get("song_id") else ""

    roles = [v.get("artist") for v in group["versions"] if v.get("artist")]
    creator = roles[0] if roles else meta.get("creator", "")

    # 封面: 专辑条目里的本地封面(相对 content 根)
    cover = meta.get("cover", "")
    # frontmatter 的 cover 从 content 根写; 正文图片必须相对本 md
    body_cover = cover[len("mouseion/music/"):] if cover.startswith("mouseion/music/") else cover
    cover_rel_encoded = urllib.parse.quote(body_cover, safe="/") if body_cover else ""

    # 版本行: 播放器 UI, 每行一个版本
    rows = []
    for i, v in enumerate(group["versions"], 1):
        name = v["name"]
        parts = [v.get("artist") or "", v.get("album") or ""]
        subtitle = " · ".join(p for p in parts if p)
        url = f"https://music.163.com/#/song?id={v['song_id']}" if v.get("song_id") else ""
        inner = (
            f'<span class="ncm-idx">{i}</span>'
            f'<span class="ncm-name">{_esc(name)}'
            + (f'<span class="ncm-sub">{_esc(subtitle)}</span>' if subtitle else "")
            + f'</span><span class="ncm-time">{_esc(v.get("duration",""))}</span>'
        )
        if url:
            rows.append(f'<a class="ncm-row" href="{url}" target="_blank" rel="noopener">{inner}</a>')
        else:
            rows.append(f'<span class="ncm-row ncm-row-static">{inner}</span>')
    play = (
        f'<a class="ncm-play" href="{album_url}" target="_blank" rel="noopener" '
        f'title="在网易云播放整张专辑" aria-label="在网易云播放整张专辑">'
        '<span class="ncm-play-icon">▶</span></a>'
        if album_url
        else ""
    )
    player = f'<div class="ncm-player">\n{play}\n<div class="ncm-list">\n' + "\n".join(rows) + "\n</div>\n</div>"

    # 专辑信息块
    intro = meta.get("intro") or meta.get("description") or ""
    bullets = []
    if album_name:
        bullets.append(f"- 专辑：{album_name}" + (f"（{meta.get('year')}）" if meta.get("year") else ""))
    if creator:
        bullets.append(f"- 艺人：{creator}")
    if meta.get("label"):
        bullets.append(f"- 厂牌：{meta['label'].strip('[]').replace(chr(34), '')}")
    if meta.get("release_date"):
        bullets.append(f"- 发行：{meta['release_date']}")
    if meta.get("neodb_rating"):
        bullets.append(f"- 评分：{meta['neodb_rating']}（NeoDB）")
    links = []
    if meta.get("source_url") and meta.get("source") == "neodb":
        links.append(f"[NeoDB]({meta['source_url']})")
    if meta.get("douban"):
        links.append(f"[Douban]({meta['douban']})")
    if album_url and album_url not in (meta.get("source_url"),):
        links.append(f"[网易云音乐]({album_url})")
    if links:
        bullets.append("- 资料：" + " · ".join(dict.fromkeys(links)))
    album_block = "<!-- music:album:begin -->\n## 专辑\n\n" + (intro + "\n\n" if intro else "") + "\n".join(bullets) + "\n<!-- music:album:end -->"

    body = "\n\n".join(
        [
            f"<!-- music:cover:begin -->\n![cover]({cover_rel_encoded})\n<!-- music:cover:end -->" if cover else "",
            "## 版本\n\n" + player,
            album_block,
        ]
    ).strip() + "\n"

    fm = collections.OrderedDict()
    fm["title"] = title
    fm["medium"] = "music"
    fm["creator"] = creator
    fm["album"] = album_name
    fm["album_id"] = album_id or ""
    fm["year"] = meta.get("year") or primary.get("year") or ""
    fm["duration"] = primary.get("duration") or ""
    fm["cover"] = cover
    fm["cover_source"] = meta.get("cover_source") or ""
    fm["cover_status"] = meta.get("cover_status") or ""
    fm["description"] = meta.get("description") or ""
    fm["source"] = "netease"
    fm["source_id"] = primary.get("song_id") or ""
    fm["source_url"] = song_url
    fm["album_url"] = album_url
    fm["album_rating"] = meta.get("neodb_rating") or ""
    fm["genres"] = parse_list(meta.get("genres"))
    fm["label"] = parse_list(meta.get("label"))
    fm["douban"] = meta.get("douban") or ""
    fm["added"] = "2026-11-09"
    fm["raw_tags"] = parse_list(meta.get("raw_tags"))
    fm["tags"] = parse_list(meta.get("tags")) or ["音乐"]
    fm["versions_count"] = len(group["versions"])
    return fm, body


def _esc(text) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    album_notes = read_album_notes()
    songs = load_playlist_songs()
    groups = build_groups(songs, album_notes)
    print(f"album notes={len(album_notes)} tracks={len(songs)} song groups={len(groups)}")

    used: dict[str, str] = {}
    conflicts = []
    for group in groups:
        stem = safe_stem(group["title"])
        # macOS 默认大小写不敏感: 冲突检测和删旧条目都必须按 casefold 比较,
        # 否则 "Hymn To Life" / "Hymn to Life" 会互相覆盖/误删。
        key = stem.casefold()
        if key in used:
            conflicts.append((stem, used[key], group["primary"].get("artist", "")))
        used[key] = group["primary"].get("artist", "")
    print(f"filename conflicts={len(conflicts)}")
    for c in conflicts:
        print("  CONFLICT", c)

    if args.dry_run:
        for group in groups[:8]:
            print(" ", group["title"], f"({len(group['versions'])} versions)",
                  "album=", group["primary"].get("album"), "meta=", bool(group["album_meta"]))
        return 0

    # 先写新条目, 再删旧条目(避免中途失败丢数据)
    written = []
    for group in groups:
        fm, body = render_note(group, album_notes.get(group["primary"].get("album", "")))
        stem = safe_stem(group["title"])
        path = os.path.join(MUSIC_DIR, stem + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(nc_frontmatter(fm) + body)
        written.append(path)

    written_keys = {p.casefold() for p in written}
    old_paths = {v["path"] for v in album_notes.values()}
    removed = 0
    for path in old_paths:
        if path.casefold() in written_keys:
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    print(f"written={len(written)} removed_old={removed}")
    return 0


def nc_frontmatter(fields) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}: {nc.yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
