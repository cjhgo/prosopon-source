"""music_model — mouseion/music 的歌曲级数据模型(唯一渲染入口)。

模型(2026-11-09 定):
  - 一个 md = 一首歌(按标题聚合的作品), 同名多版本放同一个 md 的 `## 版本`
  - 专辑不是实体, 下沉为字段(album/album_id/album_url/album_rating), 简介在 `## 专辑`

importer(歌单 → 歌曲库) 与 migrate(旧专辑库 → 歌曲库) 共用这里的:
  - 标题归一 / 文件名安全
  - render_note: 从「歌曲组 + 专辑元数据」渲染 frontmatter/正文
  - parse_versions / merge_versions: 把新版本并进既有条目(按 song_id 去重)
"""

from __future__ import annotations

import collections
import datetime
import json
import os
import re
import urllib.parse

# ---------------------------------------------------------------- text utils


def norm_key(text: str | None) -> str:
    s = re.sub(r"[\(（\[【].*?[\)）\]】]", "", str(text or ""))
    return re.sub(r"[^\w㐀-鿿]+", "", s.lower())


def base_title(name: str) -> str:
    """去掉尾部括号(版本/影视说明)得到作品名; 只在尾部去。"""
    t = re.sub(r"\s*[\(（\[【][^\)）\]】]*[\)）\]】]\s*$", "", str(name or "")).strip()
    return t or str(name or "").strip()


def safe_stem(title: str) -> str:
    # `%` 会让 FlattenLocalAssets 的 decodeURIComponent 抛 URI malformed;
    # `#` 在正文链接里是 fragment 分隔符; macOS 大小写不敏感, 冲突按 casefold 判。
    table = {
        "/": "／", "\\": "＼", ":": "：", "*": "＊", "?": "？", '"': "＂",
        "<": "＜", ">": "＞", "|": "｜", "%": "％", "#": "＃",
    }
    stem = "".join(table.get(ch, ch) for ch in title).strip()
    return stem[:60] or "untitled"


def fmt_duration(ms: int | None, fallback: str = "") -> str:
    if not ms:
        return fallback
    s = int(round(ms / 1000))
    return f"{s // 60:02d}:{s % 60:02d}"


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


def esc(text) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def song_url(song_id) -> str:
    return f"https://music.163.com/#/song?id={song_id}" if song_id else ""


def album_url(album_id) -> str:
    return f"https://music.163.com/#/album?id={album_id}" if album_id else ""


# ---------------------------------------------------------------- rendering

VERSIONS_BEGIN = "## 版本"
ALBUM_BEGIN = "<!-- music:album:begin -->"
ALBUM_END = "<!-- music:album:end -->"
COVER_BEGIN = "<!-- music:cover:begin -->"
COVER_END = "<!-- music:cover:end -->"


def render_versions(versions: list[dict], album_url_value: str = "") -> str:
    """`## 版本` 段: 播放器 UI, 每行一个版本。"""
    rows = []
    for i, v in enumerate(versions, 1):
        subtitle = " · ".join(p for p in (v.get("artist") or "", v.get("album") or "") if p)
        inner = (
            f'<span class="ncm-idx">{i}</span>'
            f'<span class="ncm-name">{esc(v.get("name"))}'
            + (f'<span class="ncm-sub">{esc(subtitle)}</span>' if subtitle else "")
            + f'</span><span class="ncm-time">{esc(v.get("duration", ""))}</span>'
        )
        url = song_url(v.get("song_id"))
        if url:
            rows.append(f'<a class="ncm-row" href="{url}" target="_blank" rel="noopener">{inner}</a>')
        else:
            rows.append(f'<span class="ncm-row ncm-row-static">{inner}</span>')
    play = (
        f'<a class="ncm-play" href="{album_url_value}" target="_blank" rel="noopener" '
        f'title="在网易云播放整张专辑" aria-label="在网易云播放整张专辑">'
        '<span class="ncm-play-icon">▶</span></a>'
        if album_url_value
        else ""
    )
    return (
        f"{VERSIONS_BEGIN}\n\n<div class=\"ncm-player\">\n{play}\n"
        '<div class="ncm-list">\n' + "\n".join(rows) + "\n</div>\n</div>"
    )


def render_album_block(album: dict) -> str:
    """`## 专辑` 段: 完整简介 + 专辑字段 + 资料链接。"""
    intro = str(album.get("intro") or album.get("description") or "").strip()
    bullets = []
    name = album.get("album") or ""
    if name:
        bullets.append(f"- 专辑：{name}" + (f"（{album['year']}）" if album.get("year") else ""))
    if album.get("artist"):
        artist = album["artist"]
        artist_text = "、".join(artist) if isinstance(artist, list) else str(artist)
        bullets.append(f"- 艺人：{artist_text}")
    label = album.get("label")
    if label:
        label_text = "、".join(label) if isinstance(label, list) else str(label)
        bullets.append(f"- 厂牌：{label_text}")
    if album.get("release_date"):
        bullets.append(f"- 发行：{album['release_date']}")
    if album.get("rating"):
        bullets.append(f"- 评分：{album['rating']}（NeoDB）")
    links = []
    if album.get("neodb_url"):
        links.append(f"[NeoDB]({album['neodb_url']})")
    if album.get("douban"):
        links.append(f"[Douban]({album['douban']})")
    if album.get("netease_url"):
        links.append(f"[网易云音乐]({album['netease_url']})")
    if links:
        bullets.append("- 资料：" + " · ".join(dict.fromkeys(links)))
    body = (intro + "\n\n" if intro else "") + "\n".join(bullets)
    return f"{ALBUM_BEGIN}\n## 专辑\n\n{body}\n{ALBUM_END}"


def render_note(
    title: str,
    versions: list[dict],
    album: dict,
    added: str | None = None,
) -> tuple[collections.OrderedDict, str]:
    """歌曲组 + 主版本专辑元数据 → (frontmatter, 正文)。"""
    primary = versions[0]
    a_url = album.get("netease_url") or album_url(album.get("album_id"))

    cover = album.get("cover") or ""
    body_cover = cover[len("mouseion/music/"):] if cover.startswith("mouseion/music/") else cover
    cover_encoded = urllib.parse.quote(body_cover, safe="/") if body_cover else ""

    blocks = []
    if cover_encoded:
        blocks.append(f"{COVER_BEGIN}\n![cover]({cover_encoded})\n{COVER_END}")
    blocks.append(render_versions(versions, a_url))
    blocks.append(render_album_block(album))
    body = "\n\n".join(blocks) + "\n"

    fm = collections.OrderedDict()
    fm["title"] = title
    fm["medium"] = "music"
    fm["creator"] = primary.get("artist") or album.get("artist_text") or ""
    fm["album"] = album.get("album") or primary.get("album") or ""
    fm["album_id"] = album.get("album_id") or primary.get("album_id") or ""
    fm["year"] = album.get("year") or primary.get("year") or ""
    fm["duration"] = primary.get("duration") or ""
    fm["cover"] = cover
    fm["cover_source"] = album.get("cover_source") or ""
    fm["cover_status"] = album.get("cover_status") or ""
    fm["description"] = album.get("description") or ""
    fm["source"] = "netease"
    fm["source_id"] = primary.get("song_id") or ""
    fm["source_url"] = song_url(primary.get("song_id"))
    fm["album_url"] = a_url
    fm["album_rating"] = album.get("rating") or ""
    fm["genres"] = parse_list(album.get("genres"))
    fm["label"] = parse_list(album.get("label"))
    fm["douban"] = album.get("douban") or ""
    fm["added"] = added or datetime.date.today().isoformat()
    fm["raw_tags"] = parse_list(album.get("raw_tags"))
    fm["tags"] = parse_list(album.get("tags")) or ["音乐"]
    fm["versions_count"] = len(versions)
    return fm, body


def frontmatter_text(fields) -> str:
    from note_cover import yaml_value  # 复用既有序列化(含引号规则)

    lines = ["---"]
    for key, value in fields.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str) and value.strip().startswith("["):
            # 从既有条目读回的 ["a", "b"] 是字符串; 还原成 list 再序列化
            value = parse_list(value)
        lines.append(f"{key}: {yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- merging

ROW_RE = re.compile(
    r'<a class="ncm-row" href="https://music\.163\.com/#/song\?id=(?P<id>\d+)"[^>]*>'
    r'<span class="ncm-idx">\d+</span>'
    r'<span class="ncm-name">(?P<name>.*?)(?:<span class="ncm-sub">(?P<sub>.*?)</span>)?</span>'
    r'<span class="ncm-time">(?P<dur>[^<]*)</span></a>',
    re.S,
)


def _unesc(text: str) -> str:
    return (
        (text or "")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
    )


def parse_versions(body: str) -> list[dict]:
    """从既有正文 `## 版本` 段还原版本列表(用于增量导入合并)。"""
    start = body.find(VERSIONS_BEGIN)
    if start < 0:
        return []
    end = body.find(ALBUM_BEGIN, start)
    section = body[start : end if end > 0 else len(body)]
    out = []
    for m in ROW_RE.finditer(section):
        sub = _unesc(m.group("sub") or "")
        parts = [p.strip() for p in sub.split("·")] if sub else []
        artist = parts[0] if parts else ""
        album = " · ".join(parts[1:]).strip() if len(parts) > 1 else ""
        out.append(
            {
                "song_id": int(m.group("id")),
                "name": _unesc(m.group("name")).strip(),
                "artist": artist,
                "album": album,
                "duration": m.group("dur").strip(),
            }
        )
    return out


def merge_versions(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """按 song_id 去重合并; 无 id 的按 name+album 判重。"""
    merged = list(existing)
    seen = {
        v["song_id"] if v.get("song_id") else ("noid", v.get("name"), v.get("album"))
        for v in merged
    }
    for v in incoming:
        key = v["song_id"] if v.get("song_id") else ("noid", v.get("name"), v.get("album"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(v)
    return merged


def replace_versions(body: str, versions: list[dict], album_url_value: str) -> str:
    """只替换 `## 版本` 段, 保留封面/专辑块。"""
    start = body.find(VERSIONS_BEGIN)
    if start < 0:
        return body
    end = body.find(ALBUM_BEGIN, start)
    end = end if end > 0 else len(body)
    block = render_versions(versions, album_url_value)
    prefix = body[:start]
    suffix = body[end:]
    return (prefix + block + ("\n\n" if suffix.strip() else "\n") + suffix).rstrip() + "\n"
