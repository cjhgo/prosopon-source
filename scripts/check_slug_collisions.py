#!/usr/bin/env python3
"""check_slug_collisions — 检查全库文件名 slug 冲突。

Quartz 的 wikilink 解析策略是 `shortest`: `[[某名]]` 只有在全库**恰好一个**
文件名匹配时才会解析成链接; 撞名(如电影与歌都叫 Stand by Me)会退化成根路径
→ 404。撞名时 wikilink 必须写成路径限定: `[[mouseion/film/stand-by-me|显示名]]`。

用法:
  python3 scripts/check_slug_collisions.py
退出码: 0 = 无冲突; 1 = 有冲突(index.md 除外, 它不靠 wikilink 引用)。
"""

from __future__ import annotations

import collections
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content")


def slug(segment: str) -> str:
    # 与 Quartz slugify 近似: 空格→-, &→-and-, 去标点, 小写
    s = segment.replace(" ", "-").replace("&", "-and-")
    s = s.replace("%", "-percent").replace("?", "").replace("#", "")
    for ch in '<>:"|*':
        s = s.replace(ch, "")
    return s.lower()


def main() -> int:
    by_name: dict[str, list[str]] = collections.defaultdict(list)
    for dirpath, _, files in os.walk(ROOT):
        for name in files:
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
            by_name[slug(os.path.basename(rel)[:-3])].append(rel)

    collisions = {
        name: paths
        for name, paths in by_name.items()
        if len(paths) > 1 and name != "index"
    }
    if not collisions:
        print("no slug collisions")
        return 0

    print(f"{len(collisions)} basename slug collision(s):")
    for name, paths in sorted(collisions.items()):
        print(f"\n  [{name}]")
        for path in sorted(paths):
            target = path[:-3]
            print(f"    - {path}")
            print(f"      wikilink → [[{target}|显示名]]")
    print("\n撞名时用路径限定写 [[folder/name|显示名]], 否则 [[name]] 会 404。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
