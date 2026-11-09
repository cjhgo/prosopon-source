#!/usr/bin/env python3
"""import_netease — 网易云歌单 → mouseion/music 歌曲条目(唯一写入口)。

数据模型见 scripts/music_model.py: 一个 md = 一首歌(作品), 专辑只是字段。
本脚本负责:
  1. 拉歌单全量曲目(公开 API, 无需登录)
  2. 按 base title 聚合歌曲组(同名多版本 → 同一 md 的 `## 版本`)
  3. 只为「有新版本」的专辑取元数据: NeoDB 匹配/详情 → 简介/评分/类型/豆瓣;
     匹配不过闸回落 NetEase, 不伪造简介与评分
  4. 下载专辑封面(每张专辑一次, 多首歌共用)
  5. 写新条目 / 把新版本并进既有条目(按 song_id 去重, 幂等)

匹配闸门: 标题分层(精确/去括号基名) + 艺人校验 + 年份复核。
NeoDB 的 alt_titles 不可信(实测「勇气」会错配「如果有一天」、「1989 Deluxe」会错配
Taylor's Version), 只认 show 标题。

用法:
  python3 scripts/import_netease.py --playlist 28868179 --dry-run
  python3 scripts/import_netease.py --playlist 28868179
  python3 scripts/import_netease.py --playlist <id> --only "歌名A,歌名B" --limit 20
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "covers"))
sys.path.insert(0, HERE)

import imageops  # noqa: E402
import music_model as mm  # noqa: E402
import note_cover as nc  # noqa: E402
import sources  # noqa: E402
from match import edition_penalty  # noqa: E402

ROOT = os.path.dirname(HERE)
MUSIC_DIR = os.path.join(ROOT, "content", "mouseion", "music")
CACHE_DIR = os.path.expanduser("~/.cache/prosopon")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
NETEASE_REFERER = "https://music.163.com/"

COMPILATION_WORDS = (
    "精选", "合集", "原声", "ost", "试音", "演唱会", "live", "电视", "电影", "动画",
    "群星", "various", "soundtrack", "collection", "hits",
)
SOUNDTRACK_MARKERS = ("soundtrack", "original", "群星", "various", "原声", "ost")


# ---------------------------------------------------------------- netease
def _proxy() -> str:
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


def _get_json(url: str, referer: str = NETEASE_REFERER, proxy: str = "", timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(handler)
    else:
        opener = urllib.request.build_opener()
    with opener.open(req, timeout=timeout) as resp:
        return json.load(resp)


def load_playlist(playlist_id: str, refresh: bool = False) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"netease-{playlist_id}.json")
    if os.path.exists(cache) and not refresh:
        return json.load(open(cache, encoding="utf-8"))

    detail = _get_json(
        f"https://music.163.com/api/v6/playlist/detail?id={playlist_id}&n=1000&s=0"
    )
    playlist = detail["playlist"]
    ids = [row["id"] for row in playlist.get("trackIds") or []]
    songs: list[dict] = []
    for i in range(0, len(ids), 100):
        batch = ids[i : i + 100]
        url = "https://music.163.com/api/song/detail?ids=[" + ",".join(map(str, batch)) + "]"
        songs.extend(_get_json(url).get("songs") or [])
        time.sleep(0.3)
    data = {"playlist": playlist, "songs": songs}
    json.dump(data, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return data


def albumize(songs: list[dict]) -> dict[int, dict]:
    """按 album.id 聚合(只为取专辑元数据, 条目本身是歌曲级)。"""
    albums: dict[int, dict] = collections.OrderedDict()
    for song in songs:
        album = song.get("album") or {}
        if not album.get("id"):
            continue
        rec = albums.setdefault(
            album["id"],
            {
                "id": album["id"],
                "name": album.get("name") or "",
                "cover": album.get("picUrl") or "",
                "date": _stamp(album.get("publishTime")),
                "year": _stamp(album.get("publishTime"))[:4],
                "company": album.get("company") or "",
                "size": album.get("size") or "",
                "artists": [],
            },
        )
        for artist in song.get("artists") or []:
            name = artist.get("name")
            if name and name not in rec["artists"]:
                rec["artists"].append(name)
    for rec in albums.values():
        rec["creator"] = " / ".join(rec["artists"])
    return albums


def _stamp(ms) -> str:
    if not ms:
        return ""
    return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- matching
def _norm_keep(text: str | None) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[^\w㐀-鿿]", "", s)


def _base(text: str | None) -> str:
    s = re.sub(r"[\(（\[【].*?[\)）\]】]", "", str(text or ""))
    return _norm_keep(s)


def _creator_ok(query_artists: list[str], cand: dict) -> bool:
    blob = _norm_keep(" ".join(str(cand.get(k, "")) for k in ("creator", "raw", "title")))
    return any(a and _norm_keep(a) in blob for a in query_artists)


def _is_compilation(album: dict) -> bool:
    text = (album["name"] + " " + album["creator"]).lower()
    return len(album["artists"]) >= 3 or any(w in text for w in COMPILATION_WORDS)


def _tier(row: dict, qn: str, qb: str) -> int | None:
    display = _norm_keep(row.get("title"))
    if not display:
        return None
    if display == qn:
        return 0
    base = _base(row.get("title"))
    if qb and base == qb:
        return 1
    if qb and (base in qb or qb in base):
        return 2
    return None


def match_candidate(album: dict, rows: list[dict]) -> tuple[dict | None, str]:
    qn, qb = _norm_keep(album["name"]), _base(album["name"])
    tiers = [(t, row) for row in rows if (t := _tier(row, qn, qb)) is not None]
    if not tiers:
        return None, "no title match"
    tiers.sort(key=lambda x: x[0])

    strict = [(t, r) for t, r in tiers if t <= 1 and _creator_ok(album["artists"], r)]
    if strict:
        return strict[0][1], f"tier{strict[0][0]}"

    loose = [(t, r) for t, r in tiers if t <= 1]
    if len(loose) == 1 and _is_compilation(album):
        return loose[0][1], "tier≤1 合辑放行"
    if len(loose) == 1:
        blob = _norm_keep(" ".join(str(loose[0][1].get(k, "")) for k in ("creator", "raw")))
        if any(m in blob for m in SOUNDTRACK_MARKERS):
            return loose[0][1], "tier≤1 原声放行"
    return None, f"title ok but creator mismatch ({len(loose)} loose)"


def _search(item: dict, proxy: str, attempts: int = 2) -> list[dict]:
    for i in range(attempts):
        try:
            rows = sources.neodb_search(item, proxy=proxy)
            if rows:
                return rows
        except Exception:
            pass
        if i + 1 < attempts:
            time.sleep(1.5)
    return []


def _cand_year(cand: dict, detail: dict, album: dict) -> int:
    for value in ((detail.get("release_date") or "")[:4], str(cand.get("year") or ""), str(album.get("year") or "")):
        if value[:4].isdigit():
            return int(value[:4])
    return 0


def choose(album: dict, rows: list[dict], proxy: str, limit: int = 3) -> tuple[dict | None, dict, str]:
    cand, why = match_candidate(album, rows)
    if not cand:
        return None, {}, why

    pool = [cand]
    qn, qb = _norm_keep(album["name"]), _base(album["name"])
    for row in rows:
        if row is cand or len(pool) >= limit:
            continue
        if _tier(row, qn, qb) in (0, 1) and _creator_ok(album["artists"], row):
            pool.append(row)

    scored = []
    for row in pool:
        try:
            detail = sources.neodb_detail(row, "music", proxy=proxy)
        except Exception:
            detail = {}
        year = _cand_year(row, detail, album)
        year_ok = 1 if album["year"] and abs(year - int(album["year"])) <= 1 else 0
        tier = t if (t := _tier(row, qn, qb)) is not None else 2
        scored.append((year_ok, -tier, -edition_penalty(row.get("title")), 1 if row.get("cover") else 0, row, detail))
        time.sleep(1.0)

    scored.sort(key=lambda x: x[:4], reverse=True)
    year_ok, negtier, _, _, row, detail = scored[0]
    return row, detail, f"tier{-negtier} year{'✓' if year_ok else '?'} detail={'✓' if detail else '✗'}"


# ---------------------------------------------------------------- album meta
def _album_meta_cache_path(album_id: int) -> str:
    return os.path.join(CACHE_DIR, f"album-meta-{album_id}.json")


def album_meta(album: dict, proxy: str, dry_run: bool = False) -> dict:
    """取一张专辑的元数据 + 本地封面。结果缓存在 ~/.cache/prosopon。"""
    cached = _album_meta_cache_path(album["id"])
    if os.path.exists(cached):
        meta = json.load(open(cached, encoding="utf-8"))
    else:
        item = {"type": "music", "title": album["name"], "creator": album["creator"], "year": album["year"]}
        rows = _search(item, proxy)
        cand, detail, note = (None, {}, "no search result") if not rows else choose(album, rows, proxy)
        if cand:
            built = nc.build_meta(cand, "music", proxy=proxy, detail=detail)
            description = built.get("description") or ""
            meta = {
                "album": album["name"],
                "album_id": album["id"],
                "year": built.get("year") or album["year"],
                "artist": built.get("artist") or album["artists"][:3],
                "label": built.get("label") or ([album["company"]] if album["company"] else []),
                "release_date": built.get("release_date") or album["date"],
                "genres": built.get("genres") or [],
                "rating": built.get("neodb_rating") or "",
                "douban": built.get("douban") or "",
                "neodb_url": built.get("source_url") or "",
                "description": nc._short(description, 160),
                "intro": description[:4000],
                "raw_tags": built.get("tags") or [],
                "tags": ["音乐"],
                "cover_source": f"neodb:{cand.get('id')}",
                "cover_remote": cand.get("cover") or detail.get("cover_image_url") or album["cover"],
                "match": note,
            }
        else:
            meta = {
                "album": album["name"],
                "album_id": album["id"],
                "year": album["year"],
                "artist": album["artists"][:3],
                "label": [album["company"]] if album["company"] else [],
                "release_date": album["date"],
                "genres": [],
                "rating": "",
                "douban": "",
                "neodb_url": "",
                "description": "",
                "intro": "",
                "raw_tags": [],
                "tags": ["音乐"],
                "cover_source": f"netease:{album['id']}",
                "cover_remote": album["cover"],
                "match": f"netease fallback ({note})",
            }
        os.makedirs(CACHE_DIR, exist_ok=True)
        json.dump(meta, open(cached, "w", encoding="utf-8"), ensure_ascii=False)

    meta["netease_url"] = mm.album_url(album["id"])
    meta["cover_status"] = "auto"

    # 封面: 每张专辑一次, 多首歌共用
    stem = mm.safe_stem(meta.get("album") or album["name"])
    cover_path = os.path.join(MUSIC_DIR, "image", stem, "cover.webp")
    meta["cover"] = f"mouseion/music/image/{stem}/cover.webp"
    if not os.path.exists(cover_path) and not dry_run:
        os.makedirs(os.path.dirname(cover_path), exist_ok=True)
        raw = cover_path + ".raw"
        use_proxy = proxy if str(meta.get("cover_source", "")).startswith("neodb:") else ""
        last = None
        for _ in range(2):
            try:
                imageops.download(meta.get("cover_remote", ""), raw, referer=None, proxy=use_proxy)
                imageops.to_webp(raw, cover_path, 700)
                last = None
                break
            except Exception as exc:
                last = exc
                time.sleep(2)
        try:
            os.remove(raw)
        except OSError:
            pass
        if last is not None:
            print(f"  ! cover failed for {album['name']}: {last}", file=sys.stderr)
            meta["cover"] = ""
    return meta


# ---------------------------------------------------------------- grouping
def group_songs(songs: list[dict], albums: dict[int, dict]) -> list[dict]:
    groups: dict[str, dict] = collections.OrderedDict()
    for song in songs:
        album = song.get("album") or {}
        artists = [a.get("name") or "" for a in song.get("artists") or []]
        publish = album.get("publishTime")
        year = str(datetime.datetime.fromtimestamp(publish / 1000).year) if publish else ""
        name = song.get("name") or ""
        key = mm.norm_key(mm.base_title(name)) or name
        group = groups.setdefault(
            key,
            {"title": mm.base_title(name), "versions": [], "album_id": album.get("id") or 0},
        )
        if any(v.get("song_id") == song.get("id") for v in group["versions"]):
            continue
        group["versions"].append(
            {
                "song_id": song.get("id"),
                "name": name,
                "artist": " / ".join(artists),
                "album": album.get("name") or "",
                "album_id": album.get("id") or 0,
                "duration": mm.fmt_duration(song.get("duration")),
                "year": year,
            }
        )
    return list(groups.values())


# ---------------------------------------------------------------- notes
def existing_notes() -> dict[str, dict]:
    out = {}
    for name in os.listdir(MUSIC_DIR):
        if not name.endswith(".md") or name == "index.md":
            continue
        path = os.path.join(MUSIC_DIR, name)
        text = open(path, encoding="utf-8").read()
        try:
            fm, body, _ = nc.split_frontmatter(text)
        except Exception:
            continue
        title = (fm.get("title") or "").replace('\\"', '"')
        if title:
            out[title] = {
                "path": path,
                "text": text,
                "fm": fm,
                "body": body,
                "versions": mm.parse_versions(body),
            }
    return out


def write_new(group: dict, meta: dict) -> str:
    fm, body = mm.render_note(group["title"], group["versions"], meta)
    stem = mm.safe_stem(group["title"])
    path = os.path.join(MUSIC_DIR, stem + ".md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(mm.frontmatter_text(fm) + body)
    return path


def update_existing(note: dict, merged: list[dict], meta: dict) -> bool:
    a_url = note["fm"].get("album_url") or meta.get("netease_url") or ""
    body = mm.replace_versions(note["body"], merged, a_url)
    if body == note["body"] and str(len(merged)) == str(note["fm"].get("versions_count")):
        return False
    fm = dict(note["fm"])
    fm["versions_count"] = len(merged)
    with open(note["path"], "w", encoding="utf-8") as f:
        f.write(mm.frontmatter_text(fm) + body)
    return True


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--playlist", default="28868179")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="忽略歌单缓存")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 首新歌")
    ap.add_argument("--only", default="", help="逗号分隔的歌名, 只处理这些")
    args = ap.parse_args(argv)

    proxy = _proxy()
    data = load_playlist(args.playlist, refresh=args.refresh)
    songs = data["songs"]
    albums = albumize(songs)
    groups = group_songs(songs, albums)
    notes = existing_notes()

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    plan = []
    for group in groups:
        if only and group["title"] not in only:
            continue
        note = notes.get(group["title"])
        existing = note["versions"] if note else []
        merged = mm.merge_versions(existing, group["versions"])
        if note and len(merged) == len(existing):
            continue  # 没有新版本
        plan.append((group, note, merged))
    if args.limit:
        plan = plan[: args.limit]

    print(
        f"playlist={data['playlist']['name']} tracks={len(songs)} songs={len(groups)} "
        f"existing={len(notes)} to_write={len(plan)} proxy={proxy or 'direct'}"
    )

    # 只为有新歌的专辑取元数据
    needed_albums = collections.OrderedDict()
    for group, note, merged in plan:
        for v in merged:
            aid = v.get("album_id")
            if aid and aid in albums:
                needed_albums[aid] = albums[aid]

    metas: dict[int, dict] = {}
    for i, (aid, album) in enumerate(needed_albums.items(), 1):
        meta = album_meta(album, proxy, dry_run=args.dry_run)
        metas[aid] = meta
        if not args.dry_run:
            print(f"  [{i}/{len(needed_albums)}] album {album['name']} -> {meta.get('match', '')}")

    created = updated = failed = 0
    for group, note, merged in plan:
        primary_album = next((v.get("album_id") for v in merged if v.get("album_id")), 0)
        meta = metas.get(primary_album) or {}
        status = f"{group['title']} ({len(merged)} 版本, album={meta.get('album') or '—'})"
        if args.dry_run:
            print(f"  DRY {status}")
            continue
        try:
            if note:
                if update_existing(note, merged, meta):
                    updated += 1
                    print(f"  ~ {status}")
            else:
                write_new(group, meta)
                created += 1
                print(f"  + {status}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {group['title']}: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\ncreated={created} updated={updated} failed={failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
