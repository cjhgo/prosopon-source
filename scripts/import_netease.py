#!/usr/bin/env python3
"""import_netease — 网易云歌单 → mouseion/music 专辑条目。

数据分工:
  NetEase  = 骨架: 专辑身份(名/艺人/年/封面) + 我喜欢的那几首(曲目/时长) + 歌单顺序
  NeoDB    = 可选补全: 简介 / genres / 评分 / 豆瓣链接

匹配不过闸就回落 NetEase 元数据, **不伪造**简介与评分。
匹配闸门(见 match_candidate): 标题分层(精确/去括号基名) + 艺人校验 + 年份复核,
分数只用来排序同层候选, 不用来跨层裁决 —— 实测「取分数第一」会错配
(勇气→如果有一天; 1989 Deluxe→Taylor's Version)。

用法:
  python3 scripts/import_netease.py --playlist 28868179 --dry-run
  python3 scripts/import_netease.py --playlist 28868179 --limit 5
  python3 scripts/import_netease.py --playlist 28868179
"""

from __future__ import annotations

import argparse
import collections
import datetime
import difflib
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

import imageops  # noqa: E402
import note_cover as nc  # noqa: E402
import sources  # noqa: E402
from match import edition_penalty  # noqa: E402

ROOT = os.path.dirname(HERE)
MUSIC_DIR = os.path.join(ROOT, "content", "mouseion", "music")
CACHE_DIR = os.path.expanduser("~/.cache/prosopon")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
NETEASE_REFERER = "https://music.163.com/"
CATEGORY_TAG = "音乐"

# 合辑/原声/试音碟: 艺人字段不可靠, 允许标题唯一即通过
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
    """歌单元信息 + 全量曲目(公开 API, 无需登录)。结果缓存到 ~/.cache/prosopon。"""
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


def _stamp(ms) -> str:
    if not ms:
        return ""
    return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")


def albumize(songs: list[dict]) -> tuple[list[dict], list[dict]]:
    """按 album.id 聚合; 无专辑归属的单曲单独返回。"""
    albums: dict[int, dict] = collections.OrderedDict()
    orphans: list[dict] = []
    for song in songs:
        album = song.get("album") or {}
        if not album.get("id"):
            orphans.append(song)
            continue
        rec = albums.setdefault(
            album["id"],
            {
                "id": album["id"],
                "name": album["name"],
                "cover": album.get("picUrl") or "",
                "date": _stamp(album.get("publishTime")),
                "year": _stamp(album.get("publishTime"))[:4],
                "company": album.get("company") or "",
                "size": album.get("size") or "",
                "artists": [],
                "songs": [],
            },
        )
        for artist in song.get("artists") or []:
            name = artist.get("name")
            if name and name not in rec["artists"]:
                rec["artists"].append(name)
        rec["songs"].append(
            {
                "id": song.get("id"),
                "name": song.get("name") or "",
                "alias": (song.get("alias") or [None])[0],
                "duration": song.get("duration") or 0,
            }
        )
    for rec in albums.values():
        rec["creator"] = " / ".join(rec["artists"])
    return list(albums.values()), orphans


# ---------------------------------------------------------------- matching
def _norm_keep(text: str | None) -> str:
    """NFKC + 小写 + 去标点, 但保留括号内容 → 1989deluxe ≠ 1989taylorsversion。"""
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[^\w㐀-鿿]", "", s)


def _base(text: str | None) -> str:
    """去掉括号内容后的基名。"""
    s = re.sub(r"[\(（\[【].*?[\)）\]】]", "", str(text or ""))
    return _norm_keep(s)


def _creator_ok(query_artists: list[str], cand: dict) -> bool:
    blob = _norm_keep(
        " ".join(str(cand.get(k, "")) for k in ("creator", "raw", "title"))
    )
    return any(a and _norm_keep(a) in blob for a in query_artists)


def _is_compilation(album: dict) -> bool:
    text = (album["name"] + " " + album["creator"]).lower()
    return len(album["artists"]) >= 3 or any(w in text for w in COMPILATION_WORDS)


def _tier(row: dict, qn: str, qb: str) -> int | None:
    """只用 show 标题分层; NeoDB 的 alt_titles 是用户维护的, 不可信(会把单曲名塞进
    专辑别名里, 实测「勇气」→「如果有一天」)。"""
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
    """返回 (候选, 说明)。不过闸返回 (None, 原因)。"""
    qname, qartists = album["name"], album["artists"]
    qn, qb = _norm_keep(qname), _base(qname)

    tiers = [(t, row) for row in rows if (t := _tier(row, qn, qb)) is not None]
    if not tiers:
        return None, "no title match"
    tiers.sort(key=lambda x: x[0])

    strict = [(t, r) for t, r in tiers if t <= 1 and _creator_ok(qartists, r)]
    if strict:
        return strict[0][1], f"tier{strict[0][0]}"

    loose_pool = [(t, r) for t, r in tiers if t <= 1]
    if len(loose_pool) == 1 and _is_compilation(album):
        return loose_pool[0][1], "tier≤1 合辑放行"
    if len(loose_pool) == 1:
        blob = _norm_keep(
            " ".join(str(loose_pool[0][1].get(k, "")) for k in ("creator", "raw"))
        )
        if any(m in blob for m in SOUNDTRACK_MARKERS):
            return loose_pool[0][1], "tier≤1 原声放行"
    return None, f"title ok but creator mismatch ({len(loose_pool)} loose)"


def _search(item: dict, proxy: str, attempts: int = 2) -> list[dict]:
    """NeoDB 偶发空响应(实测 The Rose 首次 0 条、重试 8 条), 空结果重试一次。"""
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
    for value in (
        (detail.get("release_date") or "")[:4],
        str(cand.get("year") or ""),
        str(album.get("year") or ""),
    ):
        if value[:4].isdigit():
            return int(value[:4])
    return 0


def choose(album: dict, rows: list[dict], proxy: str, limit: int = 3) -> tuple[dict | None, dict, str]:
    """过闸 + 拉 detail 复核年份, 返回 (候选, detail, 说明)。"""
    cand, why = match_candidate(album, rows)
    if not cand:
        return None, {}, why

    # 同层候选按年份复核: 只对标题精确/基名相等的候选拉 detail
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
        scored.append(
            (
                year_ok,
                -tier,
                -edition_penalty(row.get("title")),
                1 if row.get("cover") else 0,
                row,
                detail,
            )
        )
        time.sleep(1.0)

    scored.sort(key=lambda x: x[:4], reverse=True)
    year_ok, negtier, _, _, row, detail = scored[0]
    note = f"tier{-negtier} year{'✓' if year_ok else '?'} detail={'✓' if detail else '✗'}"
    return row, detail, note


# ---------------------------------------------------------------- rendering
def _fmt_duration(ms: int) -> str:
    seconds = int(round((ms or 0) / 1000))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _song_url(song_id) -> str:
    return f"https://music.163.com/#/song?id={song_id}"


def _album_url(album_id) -> str:
    return f"https://music.163.com/#/album?id={album_id}"


def _track_line(song: dict) -> str:
    name = song["name"]
    if song.get("alias"):
        name = f"{name} ({song['alias']})"
    if song.get("id"):
        return f"- [{name}]({_song_url(song['id'])}) — {_fmt_duration(song['duration'])}"
    return f"- {name} — {_fmt_duration(song['duration'])}"


def _play_link(album_id) -> str:
    """内嵌播放器已不可用(网易云 outchain 在 iframe 里报「资源加载失败」,
    直链 mp3 也 302 到 /404), 退化为一个显式播放入口。"""
    return f"> [▶ 在网易云播放整张专辑]({_album_url(album_id)})"


def _tracks_section(album: dict) -> str:
    """我喜欢的曲目(每条链到网易云单曲页) + 整专播放入口。"""
    lines = "\n".join(_track_line(s) for s in album["songs"])
    return f"## 曲目\n\n{lines}\n\n{_play_link(album['id'])}"


def _safe_stem(title: str) -> str:
    # `%` 会让 FlattenLocalAssets 的 decodeURIComponent 抛 URI malformed, 必须换掉;
    # `#` 在正文链接里是 fragment 分隔符, 一并换。
    table = {
        "/": "／", "\\": "＼", ":": "：", "*": "＊", "?": "？", '"': "＂",
        "<": "＜", ">": "＞", "|": "｜", "%": "％", "#": "＃",
    }
    stem = "".join(table.get(ch, ch) for ch in title).strip()
    return stem[:60] or "untitled"  # 与既有条目一致的文件名截断长度


def _frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}: {nc.yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def build_note(album: dict, cand: dict | None, detail: dict, proxy: str) -> tuple[dict, str, str, str]:
    """返回 (frontmatter 字段, 正文, 封面 URL, cover_source)。cand=None → NetEase 回落。"""
    if cand:
        meta = nc.build_meta(cand, "music", proxy=proxy, detail=detail)
        source, source_id = "neodb", cand.get("id")
        source_url = cand.get("url", "")
        label = "NeoDB"
        cover = cand.get("cover") or detail.get("cover_image_url") or album["cover"]
        cover_source = f"neodb:{source_id}"
    else:
        meta = {
            "description": "",
            "tags": [],
            "genres": [],
            "release_date": album["date"],
            "artist": album["artists"][:3],
            "label": [album["company"]] if album["company"] else [],
            "track_count": album["size"],
            "year": album["year"],
            "creator": album["creator"],
            "source_url": f"https://music.163.com/#/album?id={album['id']}",
        }
        source, source_id = "netease", album["id"]
        source_url = meta["source_url"]
        label = "网易云音乐"
        cover = album["cover"]
        cover_source = f"netease:{source_id}"

    meta["netease_url"] = _album_url(album["id"])

    fields = {
        "title": album["name"],
        "medium": "music",
        "creator": meta.get("creator") or album["creator"],
        "year": meta.get("year") or album["year"],
        "description": nc._short(meta.get("description"), 160),
        "source": source,
        "source_id": source_id,
        "source_url": source_url,
        "genres": meta.get("genres") or [],
        "release_date": meta.get("release_date") or album["date"],
        "artist": meta.get("artist") or album["artists"][:3],
        "label": meta.get("label") or [],
        "track_count": meta.get("track_count") or album["size"],
        "neodb_rating": meta.get("neodb_rating") or "",
        "douban": meta.get("douban") or "",
        "added": datetime.date.today().isoformat(),
        "raw_tags": meta.get("tags") or [],
        "tags": [CATEGORY_TAG],
    }

    cover_rel = f"image/{_safe_stem(album['name'])}/cover.webp"
    # 正文链接必须 URL-encode(空格/CJK/%/括号), 否则 FlattenLocalAssets 的
    # decodeURIComponent 抛 "URI malformed"; frontmatter 的 cover 保持解码路径。
    cover_url_enc = urllib.parse.quote(cover_rel, safe="/")
    body = "\n\n".join(
        [
            f"{nc.COVER_BEGIN}\n![cover]({cover_url_enc})\n{nc.COVER_END}",
            _tracks_section(album),
            nc.render_background("music", meta, source_label=label),
        ]
    ) + "\n"
    return fields, body, cover, cover_source


def write_note(album: dict, fields: dict, body: str, cover_url: str, cover_source: str, proxy: str) -> str:
    stem = _safe_stem(album["name"])
    note_path = os.path.join(MUSIC_DIR, stem + ".md")
    cover_dir = os.path.join(MUSIC_DIR, "image", stem)
    os.makedirs(cover_dir, exist_ok=True)

    raw = os.path.join(cover_dir, "cover.raw")
    dest = os.path.join(cover_dir, "cover.webp")
    # NeoDB 封面可能被墙, 走代理; 网易云封面走直连。超时重试一次。
    use_proxy = proxy if cover_source.startswith("neodb:") else ""
    last = None
    for attempt in range(2):
        try:
            imageops.download(cover_url, raw, referer=None, proxy=use_proxy)
            imageops.to_webp(raw, dest, 700)
            last = None
            break
        except Exception as exc:
            last = exc
            time.sleep(2)
    if last is not None:
        raise last
    try:
        os.remove(raw)
    except OSError:
        pass

    fields = dict(fields)
    fields["cover"] = f"mouseion/music/image/{stem}/cover.webp"
    # 保持现有条目的键顺序: cover/cover_source/cover_status 紧随 creator/year
    ordered = {}
    for key in ("title", "medium", "creator", "cover", "cover_source", "cover_status"):
        if key == "cover":
            ordered["cover"] = fields["cover"]
            ordered["cover_source"] = cover_source
            ordered["cover_status"] = "auto"
        elif key in fields:
            ordered[key] = fields[key]
    for key, value in fields.items():
        if key not in ordered:
            ordered[key] = value

    with open(note_path, "w", encoding="utf-8") as f:
        f.write(_frontmatter(ordered) + body)
    return note_path


# ---------------------------------------------------------------- main
def _title_map() -> dict[str, str]:
    """frontmatter title → 笔记路径(既有文件名有 60 字截断, 不能按 stem 找)。"""
    out = {}
    for name in os.listdir(MUSIC_DIR):
        if not name.endswith(".md") or name == "index.md":
            continue
        path = os.path.join(MUSIC_DIR, name)
        try:
            fm, _, _ = nc.split_frontmatter(open(path, encoding="utf-8").read())
            title = (fm.get("title") or "").replace('\\"', '"')
            if title:
                out[title] = path
        except Exception:
            continue
    return out


def refresh_links(albums: list[dict], dry_run: bool = False) -> tuple[int, list[str]]:
    """回填: 曲目加网易云单曲链接 + 整专播放器 + 资料区专辑链接。"""
    paths = _title_map()
    changed, missing = 0, []
    for album in albums:
        path = paths.get(album["name"])
        if not path:
            missing.append(album["name"])
            continue
        text = open(path, encoding="utf-8").read()
        new_section = _tracks_section(album)
        updated, n = re.subn(
            r"## 曲目[^\n]*\n.*?(?=\n<!-- gencover:begin -->|\Z)",
            new_section + "\n",
            text,
            count=1,
            flags=re.S,
        )
        if not n:
            missing.append(album["name"])
            continue
        url = _album_url(album["id"])
        if url not in updated:
            updated = re.sub(
                r"^(- 资料：.*)$",
                lambda m: f"{m.group(1)} · [网易云音乐]({url})",
                updated,
                count=1,
                flags=re.M,
            )
        if updated != text:
            changed += 1
            if not dry_run:
                open(path, "w", encoding="utf-8").write(updated)
    return changed, missing


def _netease_song_search(query: str, limit: int = 8, attempts: int = 4) -> list[dict]:
    url = (
        "https://music.163.com/api/search/get/web?s="
        + urllib.parse.quote(query)
        + f"&type=1&limit={limit}"
    )
    for i in range(attempts):
        try:
            data = _get_json(url)
        except Exception:
            data = {}
        if int(data.get("code") or 0) == 406:  # 操作频繁
            time.sleep(8 * (i + 1))
            continue
        return (data.get("result") or {}).get("songs") or []
    return []


def resolve_missing(dry_run: bool = False, songs: list[dict] | None = None) -> tuple[int, list[str]]:
    """给还没有网易云链接的条目按「曲名 + 艺人」反查单曲, 补链接/专辑链接/播放器。

    先查歌单缓存(零请求), 再走网易云搜索接口(限流很紧)。
    """
    by_name: dict[str, list[dict]] = {}
    by_id: dict[int, dict] = {}
    for song in songs or []:
        by_name.setdefault(_norm_keep(song.get("name")), []).append(song)
        if song.get("id"):
            by_id[song["id"]] = song

    def cached(plain: str, creator: str) -> dict | None:
        exact = by_name.get(_norm_keep(plain)) or []
        for song in exact:
            artists = [a.get("name") or "" for a in song.get("artists") or []]
            if creator and not any(
                _norm_keep(creator) in _norm_keep(a) or _norm_keep(a) in _norm_keep(creator)
                for a in artists
            ):
                continue
            return song
        # 曲名拼写有出入(NeoDB 与网易云不一致)时, 同艺人 + 高相似度才认
        target = _norm_keep(plain)
        for song in songs or []:
            artists = [a.get("name") or "" for a in song.get("artists") or []]
            if not creator or not any(
                _norm_keep(creator) in _norm_keep(a) or _norm_keep(a) in _norm_keep(creator)
                for a in artists
            ):
                continue
            if difflib.SequenceMatcher(None, target, _norm_keep(song.get("name"))).ratio() >= 0.88:
                return song
        return None

    changed, unresolved = 0, []
    for name in sorted(os.listdir(MUSIC_DIR)):
        if not name.endswith(".md") or name == "index.md":
            continue
        path = os.path.join(MUSIC_DIR, name)
        text = open(path, encoding="utf-8").read()
        if "在网易云播放整张专辑" in text:
            continue
        fm, _, _ = nc.split_frontmatter(text)
        creator = (fm.get("creator") or "").split(" / ")[0]
        album_ids: collections.Counter = collections.Counter()
        hit = 0

        def link_line(match: re.Match) -> str:
            nonlocal hit
            # 兼容两种既有写法: "- 曲名 — 时长" 和 "- 曲名 — 艺人 — 时长"
            raw_name, line_artist, dur = match.group(1), match.group(2) or "", match.group(3)
            if raw_name.startswith("["):  # 已经链过
                hit += 1
                return match.group(0)
            raw_name = raw_name.replace("**", "")
            artist = line_artist.replace("**", "").split(" / ")[0].strip() or creator
            mid = f" — {line_artist.replace('**','')}" if line_artist else ""
            plain = re.sub(r"\s*\([^)]*\)\s*$", "", raw_name).strip()

            found = cached(raw_name, artist) or cached(plain, artist)
            if found:
                hit += 1
                album = found.get("album") or {}
                if album.get("id"):
                    album_ids[album["id"]] += 1
                return f"- [{raw_name}]({_song_url(found['id'])}){mid} — {dur}"

            for song in _netease_song_search(f"{plain} {artist}"):
                song_plain = re.sub(r"\s*\([^)]*\)\s*$", "", song.get("name") or "").strip()
                artists = [a.get("name") or "" for a in song.get("artists") or []]
                if _norm_keep(song_plain) != _norm_keep(plain):
                    continue
                if artist and not any(_norm_keep(artist) in _norm_keep(a) or _norm_keep(a) in _norm_keep(artist) for a in artists):
                    continue
                hit += 1
                album = song.get("album") or {}
                if album.get("id"):
                    album_ids[album["id"]] += 1
                return f"- [{raw_name}]({_song_url(song['id'])}){mid} — {dur}"
            return match.group(0)

        updated = re.sub(
            r"^- (.*?)(?: — (.*?))? — (\d\d:\d\d)$", link_line, text, flags=re.M
        )
        # 已有单曲链接的条目(上一轮部分成功): 从 song/detail 反推专辑, 补播放器
        existing_ids = [int(i) for i in re.findall(r"music\.163\.com/#/song\?id=(\d+)", updated)]
        if existing_ids and not album_ids:
            for sid in existing_ids:  # 歌单缓存里就有专辑归属, 不必打接口
                album = (by_id.get(sid) or {}).get("album") or {}
                if album.get("id"):
                    album_ids[album["id"]] += 1
            missing_ids = [i for i in existing_ids if i not in by_id]
            if missing_ids:
                try:
                    data = _get_json(
                        "https://music.163.com/api/song/detail?ids=["
                        + ",".join(map(str, missing_ids[:10]))
                        + "]"
                    )
                    for song in data.get("songs") or []:
                        album = song.get("album") or {}
                        if album.get("id"):
                            album_ids[album["id"]] += 1
                except Exception:
                    pass
        if not hit and not existing_ids:
            unresolved.append(name[:-3])
            continue
        album_id = album_ids.most_common(1)[0][0] if album_ids else None
        if album_id:
            url = _album_url(album_id)
            if url not in updated:
                updated = re.sub(
                    r"^(- 资料：.*)$",
                    lambda m: f"{m.group(1)} · [网易云音乐]({url})",
                    updated, count=1, flags=re.M,
                )
            link = _play_link(album_id)
            if link not in updated:
                if re.search(r"^## 曲目$", updated, re.M):
                    updated = re.sub(
                        r"(## 曲目\n\n(?:- .*\n)+)",
                        lambda m: f"{m.group(1)}\n{link}\n",
                        updated, count=1,
                    )
                else:  # 没有曲目段的老条目: 追加到末尾
                    updated = updated.rstrip() + "\n\n" + link + "\n"
        if updated != text:
            changed += 1
            if not dry_run:
                open(path, "w", encoding="utf-8").write(updated)
        time.sleep(2.0)  # 网易云搜索接口限流很紧(406), 主动降速
    return changed, unresolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--playlist", default="28868179")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="忽略歌单缓存")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 张新专辑")
    parser.add_argument("--only", default="", help="逗号分隔的专辑名, 只处理这些")
    parser.add_argument(
        "--refresh-links", action="store_true",
        help="回填既有条目: 曲目加网易云单曲链接 + 播放器 + 专辑链接(不重建条目)",
    )
    parser.add_argument(
        "--resolve-missing", action="store_true",
        help="给没有网易云链接的条目按曲名+艺人反查单曲, 补链接/播放器",
    )
    args = parser.parse_args(argv)

    proxy = _proxy()
    data = load_playlist(args.playlist, refresh=args.refresh)
    albums, orphans = albumize(data["songs"])

    if args.refresh_links:
        changed, missing = refresh_links(albums, dry_run=args.dry_run)
        print(f"refresh-links: changed={changed} not_found={len(missing)}")
        for name in missing[:10]:
            print("  NOT FOUND", name)
        return 0

    if args.resolve_missing:
        changed, unresolved = resolve_missing(dry_run=args.dry_run, songs=data["songs"])
        print(f"resolve-missing: changed={changed} unresolved={len(unresolved)}")
        for name in unresolved:
            print("  UNRESOLVED", name)
        return 0
    # 按 stem 和 frontmatter title 双查重: 既有条目的文件名有 60 字截断,
    # 只比 stem 会给长名专辑造出重复条目(实测 Interstellar / Hateful Eight)
    existing = {
        os.path.splitext(f)[0] for f in os.listdir(MUSIC_DIR) if f.endswith(".md")
    }
    existing_titles = set()
    for name in os.listdir(MUSIC_DIR):
        if not name.endswith(".md"):
            continue
        try:
            fm, _, _ = nc.split_frontmatter(
                open(os.path.join(MUSIC_DIR, name), encoding="utf-8").read()
            )
            existing_titles.add(fm.get("title", ""))
        except Exception:
            pass

    todo = []
    skipped = []
    for album in albums:
        if _safe_stem(album["name"]) in existing or album["name"] in existing_titles:
            skipped.append(album["name"])
            continue
        if args.only and album["name"] not in {x.strip() for x in args.only.split(",")}:
            continue
        todo.append(album)
    if args.limit:
        todo = todo[: args.limit]

    print(
        f"playlist={data['playlist']['name']} tracks={len(data['songs'])} "
        f"albums={len(albums)} existing={len(skipped)} todo={len(todo)} proxy={proxy or 'direct'}"
    )
    if orphans:
        print(f"orphan tracks (no album): {', '.join(s['name'] for s in orphans)}")

    created, failed = [], []
    for i, album in enumerate(todo, 1):
        item = {
            "type": "music",
            "title": album["name"],
            "creator": album["creator"],
            "year": album["year"],
        }
        rows = _search(item, proxy)
        cand, detail, note = (None, {}, "no search result") if not rows else choose(album, rows, proxy)
        status = f"[{i}/{len(todo)}] {album['name']} | {album['creator']} | {album['year']} -> "
        status += f"{'neodb:' + cand['title'] + ' ' + note if cand else 'netease fallback (' + note + ')'}"

        if args.dry_run:
            print(status)
            continue
        fields, body, cover_url, cover_source = build_note(album, cand, detail, proxy)
        try:
            try:
                path = write_note(album, fields, body, cover_url, cover_source, proxy)
            except Exception:
                # NeoDB 封面挂了(超时/404)就换网易云封面, 封面来源随之改写
                if not cover_source.startswith("neodb:") or not album["cover"]:
                    raise
                path = write_note(
                    album, fields, body, album["cover"], f"netease:{album['id']}", proxy
                )
                print(status + "  ↺ cover: netease fallback")
            created.append(os.path.basename(path))
            print(status + "  ✓")
        except Exception as exc:
            failed.append((album["name"], f"{type(exc).__name__}: {exc}"))
            print(status + f"  ✗ {type(exc).__name__}: {exc}")

    print(f"\ncreated={len(created)} skipped={len(skipped)} failed={len(failed)}")
    for name, why in failed:
        print(f"  FAILED {name}: {why}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
