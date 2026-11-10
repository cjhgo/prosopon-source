#!/usr/bin/env python3
"""map_netease_playlists — 把「红心 = 1 bit」还原成「歌 → 播放列表集合」。

背景: 网易云只有「喜欢的音乐」一个红心, 情绪/场景/功能意图在点赞那一刻丢失了。
但用户自建的歌单本身就是一轮人工标注(睡/Turn on/想弹/想唱/旋律旋律...)。
本脚本把 membership 拉下来, 产出:
  1. ~/.cache/prosopon/song-playlists.json  — song_id → {name, artist, liked, playlists[]}
  2. ~/.cache/prosopon/song-playlists.md    — 可读映射表 + 统计(含"未归类"池)

只拉 membership(id), 不修改 content; 词表收敛留给人工。

用法:
  python3 scripts/map_netease_playlists.py --uid 36539585 --liked 28868179
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_netease as imp  # noqa: E402  复用 _get_json / CACHE_DIR

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
REFERER = "https://music.163.com/"
CACHE = imp.CACHE_DIR


def fetch_playlists(uid: int, refresh: bool = False) -> list[dict]:
    path = os.path.join(CACHE, f"user-playlists-{uid}.json")
    if os.path.exists(path) and not refresh:
        return json.load(open(path, encoding="utf-8"))
    data = imp._get_json(
        f"https://music.163.com/api/user/playlist?uid={uid}&limit=1000&offset=0"
    )
    playlists = data.get("playlist") or []
    json.dump(playlists, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return playlists


def fetch_track_ids(playlist_id: int, refresh: bool = False) -> list[int]:
    path = os.path.join(CACHE, f"playlist-ids-{playlist_id}.json")
    if os.path.exists(path) and not refresh:
        return json.load(open(path, encoding="utf-8"))
    data = imp._get_json(
        f"https://music.163.com/api/v6/playlist/detail?id={playlist_id}&n=1000&s=0"
    )
    ids = [row["id"] for row in (data.get("playlist") or {}).get("trackIds") or []]
    json.dump(ids, open(path, "w", encoding="utf-8"))
    time.sleep(0.35)
    return ids


def fetch_songs(ids: list[int], known: dict[int, dict]) -> dict[int, dict]:
    """补齐元数据: 先查已知(红心缓存), 剩下按 100 一批请求。"""
    out = dict(known)
    missing = [i for i in ids if i not in out]
    for start in range(0, len(missing), 100):
        batch = missing[start : start + 100]
        url = "https://music.163.com/api/song/detail?ids=[" + ",".join(map(str, batch)) + "]"
        try:
            data = imp._get_json(url)
        except Exception:
            data = {}
        for song in data.get("songs") or []:
            out[song["id"]] = {
                "name": song.get("name") or "",
                "artist": " / ".join(a.get("name") or "" for a in song.get("artists") or []),
                "album": (song.get("album") or {}).get("name") or "",
            }
        time.sleep(0.3)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uid", type=int, default=36539585)
    ap.add_argument("--liked", type=int, default=28868179)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument(
        "--browser-dump", default="",
        help="带登录态的 dump(opencli eval 产出, 含私密歌单); 含 id/name/owned/trackIds",
    )
    args = ap.parse_args(argv)

    os.makedirs(CACHE, exist_ok=True)
    browser = None
    if args.browser_dump:
        browser = json.load(open(args.browser_dump, encoding="utf-8"))
        playlists = browser
    else:
        playlists = fetch_playlists(args.uid, refresh=args.refresh)
    owned = [p for p in playlists if (p.get("creator") or {}).get("userId") == args.uid or p.get("owned")]
    print(f"playlists={len(playlists)} owned={len(owned)}")

    # 红心歌单的曲目(含元数据)
    cached = imp.load_playlist(str(args.liked))
    liked_songs = cached["songs"]
    liked_ids = [s["id"] for s in liked_songs]
    known = {
        s["id"]: {
            "name": s.get("name") or "",
            "artist": " / ".join(a.get("name") or "" for a in s.get("artists") or []),
            "album": (s.get("album") or {}).get("name") or "",
        }
        for s in liked_songs
    }

    memberships: dict[int, list[dict]] = collections.defaultdict(list)
    playlist_stats = []
    for i, playlist in enumerate(playlists, 1):
        pid = playlist["id"]
        if browser is not None:
            ids = playlist.get("trackIds") or []
            is_owned = bool(playlist.get("owned"))
        else:
            ids = fetch_track_ids(pid, refresh=args.refresh)
            is_owned = (playlist.get("creator") or {}).get("userId") == args.uid
        for sid in ids:
            memberships[sid].append(
                {"id": pid, "name": playlist.get("name") or "", "owned": is_owned}
            )
        overlap = len(set(ids) & set(liked_ids))
        playlist_stats.append(
            {
                "id": pid,
                "name": playlist.get("name") or "",
                "owned": is_owned,
                "tracks": len(ids),
                "liked_overlap": overlap,
            }
        )
        if i % 10 == 0:
            print(f"  fetched {i}/{len(playlists)} playlists")

    all_ids = list(memberships.keys())
    meta = fetch_songs(all_ids, known)

    mapping = {}
    for sid, pls in memberships.items():
        info = meta.get(sid, {})
        mapping[str(sid)] = {
            "name": info.get("name", ""),
            "artist": info.get("artist", ""),
            "album": info.get("album", ""),
            "liked": sid in known,
            "playlists": [p["name"] for p in pls if p["id"] != args.liked],
            "owned_playlists": [p["name"] for p in pls if p["owned"] and p["id"] != args.liked],
        }

    json.dump(mapping, open(os.path.join(CACHE, "song-playlists.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 统计
    liked_set = set(liked_ids)
    unlabeled = [sid for sid in liked_ids if not [p for p in memberships.get(sid, []) if p["id"] != args.liked]]
    dist = collections.Counter(len(v["owned_playlists"]) for v in mapping.values() if v["liked"])
    print(f"\nunion songs={len(mapping)} liked={len(liked_set)} likes_in_no_other_playlist={len(unlabeled)}")
    print("liked songs by #owned-playlists:", dict(sorted(dist.items())))

    # Markdown
    lines = ["# 歌 → 歌单 映射", "", f"生成: {time.strftime('%Y-%m-%d %H:%M')}  uid={args.uid}", ""]
    lines += ["## 歌单概览", "", "| 歌单 | 自建 | 曲目 | 与红心重合 |", "|---|---|---|---|"]
    for row in sorted(playlist_stats, key=lambda x: (-x["liked_overlap"], x["name"])):
        lines.append(f"| {row['name']} | {'✓' if row['owned'] else '订阅'} | {row['tracks']} | {row['liked_overlap']} |")
    lines += ["", f"## 红心歌中未进任何自建歌单（{len(unlabeled)} 首，待人工打标）", ""]
    for sid in unlabeled:
        info = meta.get(sid, {})
        lines.append(f"- {info.get('name','')} — {info.get('artist','')}")
    lines += ["", "## 歌 → 歌单（只列有自建歌单归属的）", "", "| 歌 | 艺人 | 自建歌单 |", "|---|---|---|"]
    rows = [v for v in mapping.values() if v["owned_playlists"]]
    rows.sort(key=lambda v: (v["artist"], v["name"]))
    for v in rows:
        lines.append(f"| {v['name']} | {v['artist']} | {', '.join(v['owned_playlists'])} |")
    md_path = os.path.join(CACHE, "song-playlists.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"\nwritten:\n  {os.path.join(CACHE, 'song-playlists.json')}\n  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
