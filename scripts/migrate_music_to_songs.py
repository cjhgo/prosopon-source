#!/usr/bin/env python3
"""migrate_music_to_songs — 旧「专辑级」mouseion/music 库 → 歌曲级库(历史迁移)。

只在仓库还是专辑级模型时使用; 新内容一律走 import_netease.py(歌曲级写入口)。
渲染/合并逻辑与 importer 共用 scripts/music_model.py。

规则:
  - 一个 md = 一首歌(按标题聚合的作品), 同名多版本放同一个 md 的 `## 版本`
  - 专辑下沉为字段; 专辑简介/评分/封面从旧专辑条目搬到每首歌
  - 合并口径: 去尾部括号后标题相同 = 同一作品

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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "covers"))
sys.path.insert(0, HERE)
import music_model as mm  # noqa: E402
import note_cover as nc  # noqa: E402

ROOT = os.path.dirname(HERE)
MUSIC_DIR = os.path.join(ROOT, "content", "mouseion", "music")
CACHE = os.path.expanduser("~/.cache/prosopon/netease-28868179.json")


def read_album_notes() -> dict[str, dict]:
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
        m = re.search(
            r"## 专辑简介\n\n(.*?)(?=\n- (?:艺人|专辑|厂牌|发行|类型|曲目|评分|资料)：|\n<!-- gencover:end -->|\Z)",
            body,
            re.S,
        )
        out[title] = {
            "path": path,
            "title": title,
            "creator": fm.get("creator", ""),
            "year": fm.get("year", ""),
            "description": fm.get("description", ""),
            "intro": m.group(1).strip() if m else "",
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
    tracks = []
    m = re.search(r"## (?:曲目|版本)\n(.*?)(?=\n## |\n<!-- (?:gencover|music):|\Z)", body, re.S)
    if not m:
        return tracks
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        got = re.match(r"^- \[(.+?)\]\((https://music\.163\.com/#/song\?id=\d+)\)(?: — .*?)? — (\d\d:\d\d)$", line)
        if got:
            tracks.append({"name": got.group(1), "url": got.group(2), "duration": got.group(3)})
            continue
        got = re.match(r"^- (.+?)(?: — .*?)? — (\d\d:\d\d)$", line)
        if got:
            tracks.append({"name": got.group(1).replace("**", ""), "url": None, "duration": got.group(2)})
    return tracks


def load_playlist_songs() -> list[dict]:
    return json.load(open(CACHE, encoding="utf-8"))["songs"]


def build_groups(songs: list[dict], album_notes: dict[str, dict]) -> list[dict]:
    groups: dict[str, dict] = collections.OrderedDict()

    def add_version(version: dict):
        key = mm.norm_key(mm.base_title(version["name"])) or version["name"]
        group = groups.setdefault(key, {"title": mm.base_title(version["name"]), "versions": []})
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
                "song_id": song.get("id"),
                "name": song.get("name") or "",
                "artist": " / ".join(artists),
                "album": album.get("name") or "",
                "album_id": album.get("id") or 0,
                "duration": mm.fmt_duration(song.get("duration")),
                "year": year,
            }
        )

    # 非歌单条目(旧条目里的曲目)补进来; 相同 song_id 自动去重
    for album in album_notes.values():
        for track in album["tracks"]:
            song_id = None
            if track.get("url"):
                got = re.search(r"id=(\d+)", track["url"])
                song_id = int(got.group(1)) if got else None
            add_version(
                {
                    "song_id": song_id,
                    "name": track["name"],
                    "artist": album["creator"],
                    "album": album["title"],
                    "album_id": None,
                    "duration": track["duration"],
                    "year": album["year"],
                }
            )

    by_exact = album_notes
    by_norm = {mm.norm_key(k): v for k, v in album_notes.items()}
    for group in groups.values():
        primary = group["versions"][0]
        note = by_exact.get(primary["album"]) or by_norm.get(mm.norm_key(primary["album"])) or {}
        group["album_meta"] = note
        group["primary"] = primary
        group["title"] = mm.base_title(primary["name"])
    return list(groups.values())


def to_model_album(note: dict, primary: dict) -> dict:
    """旧专辑条目元数据 → music_model 的 album dict。"""
    album_id = primary.get("album_id") or (
        int(note["source_id"]) if str(note.get("source_id", "")).isdigit() else None
    )
    return {
        "album": note.get("title") or primary.get("album") or "",
        "album_id": album_id,
        "year": note.get("year") or primary.get("year") or "",
        "artist": note.get("creator") or "",
        "label": mm.parse_list(note.get("label")),
        "release_date": note.get("release_date") or "",
        "genres": mm.parse_list(note.get("genres")),
        "rating": note.get("neodb_rating") or "",
        "douban": note.get("douban") or "",
        "neodb_url": note.get("source_url") if note.get("source") == "neodb" else "",
        "netease_url": mm.album_url(album_id),
        "description": note.get("description") or "",
        "intro": note.get("intro") or "",
        "raw_tags": mm.parse_list(note.get("raw_tags")),
        "tags": mm.parse_list(note.get("tags")) or ["音乐"],
        "cover": note.get("cover") or "",
        "cover_source": note.get("cover_source") or "",
        "cover_status": note.get("cover_status") or "",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    album_notes = read_album_notes()
    songs = load_playlist_songs()
    groups = build_groups(songs, album_notes)
    print(f"album notes={len(album_notes)} tracks={len(songs)} song groups={len(groups)}")

    used: set[str] = set()
    conflicts = []
    for group in groups:
        stem = mm.safe_stem(group["title"])
        if stem.casefold() in used:  # macOS 大小写不敏感
            conflicts.append(stem)
        used.add(stem.casefold())
    print(f"filename conflicts={len(conflicts)}")
    for c in conflicts:
        print("  CONFLICT", c)

    if args.dry_run:
        for group in groups[:8]:
            print(" ", group["title"], f"({len(group['versions'])} versions)",
                  "album=", group["primary"].get("album"), "meta=", bool(group["album_meta"]))
        return 0

    written = []
    for group in groups:
        meta = to_model_album(group["album_meta"], group["primary"])
        fm, body = mm.render_note(group["title"], group["versions"], meta, added="2026-11-09")
        path = os.path.join(MUSIC_DIR, mm.safe_stem(group["title"]) + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(mm.frontmatter_text(fm) + body)
        written.append(path)

    written_keys = {p.casefold() for p in written}
    removed = 0
    for note in album_notes.values():
        path = note["path"]
        if path.casefold() in written_keys:
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    print(f"written={len(written)} removed_old={removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
