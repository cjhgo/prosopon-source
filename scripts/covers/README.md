# covers — 单篇笔记的封面助手（书影音）

**note 就是 item。** 这不是数据平台，是单篇 authoring 助手：
给定一篇笔记，召回几个封面候选，你挑一个，它下载并写回，**正文一个字不动**。
书影音有自己的 frontmatter（`medium` 等），**不调用 `genfront.sh`**；genfront 留给一般笔记。

## 一条命令

```bash
bash scripts/gencover.sh content/mouseion/film/stand-by-me.md
# 非交互：直接取排名第一，不打开浏览器
bash scripts/gencover.sh content/mouseion/film/stand-by-me.md --auto
```

1. 没有 frontmatter → 生成**书影音专用**骨架（title / medium / added），不调用 genfront.sh
2. 起本地选封面页（浏览器自动打开）
3. 你点 **Use this cover** → 下载封面 → 写 `cover / cover_source / cover_status`，并在正文顶部插入 `![cover](…)`
4. 自动补 frontmatter（导演/演员/年份/类型/评分/豆瓣/IMDb/TMDB 链接等）
5. 自动在正文末尾生成 `<!-- gencover:begin --> … <!-- gencover:end -->` 背景区块
6. 服务退出，命令结束

正文里你自己写的内容保留；再次运行只会替换 `gencover` 和 `gencover:cover` 标记之间的区块。
`gencover.sh` 是唯一入口；代理自动探测（`FETCH_PROXY` → 本机 7890 → 直连），不用手写 `--proxy`。

## 目录

```
content/mouseion/
├── books/
│   └── 置身事内.md
├── film/
│   └── 花样年华.md
└── music/
    └── 万能青年旅店.md
```

封面按笔记就近存放（note-anchored）：

```
content/mouseion/film/花样年华.md
content/mouseion/film/image/花样年华/cover.webp
```

frontmatter：

```yaml
---
title: 花样年华
creator: 王家卫
year: 2000
cover: mouseion/film/image/花样年华/cover.webp
cover_source: neodb:3lfsaPPZ1kXX09dPlzU2YQ
cover_status: manual
---
正文：个人感受 + [[跨作品]] wikilink
```

`gencover.sh` 初始化/补齐的专用字段（只补缺失/空值，不覆盖你手写的）：

```yaml
title / medium / added                 # 初始化
creator / year / description / tags    # enrich
director / cast / genres / release_date / country   # film
author / publisher / isbn / pages                   # book
artist / label / genres / track_count               # music
source / source_id / source_url / neodb_rating
douban / imdb / tmdb / openlibrary
raw_tags: [...]      # 原始标签(NeoDB 等),保留不参与 tag 页
tags: ["电影"]        # 人工策展入口:gencover 只写一个粗分类,后续人工接管
```

> `tags` 是认知/审美的策展字段,`gencover` 只塞一个保守分类(书/电影/音乐);
> 原始标签全部进 `raw_tags`,不会生成 `tags/<actor>/` 之类薄页面。

## 视觉选封面（主）

```bash
cd prosopon-source/scripts/covers
python3 note_cover.py serve ../../content/mouseion/film/花样年华.md
```

启动一个本地页面（默认 `http://127.0.0.1:8765/`，自动开浏览器）：

- 每张候选显示封面、年份、creator、置信度、来源
- **`source ↗`** 打开源条目页（NeoDB / TMDB / Wikipedia / iTunes）
- **`Use this cover`** 直接下载 → WebP → 写回这篇笔记
- 已有封面会显示在顶部；再点一张会替换
- 缩略图先下载到本地，不走热链；页面只绑定 127.0.0.1

CLI 版本留给脚本/批量：

```bash
python3 note_cover.py find ../../content/mouseion/film/花样年华.md
python3 note_cover.py apply ../../content/mouseion/film/花样年华.md --pick 2
python3 note_cover.py find --type film --title 花样年华 --creator 王家卫 --year 2000
```

`find` 生成 `out/candidates/<type>-<stem>.json/html`；`apply` 取第 N 个。
已有 `cover` 时默认拒绝覆盖，`--force` 才替换。

**版本/封面是品味确认**：工具只负责把候选的年份、来源、标题摆出来，不替你做
「哪个封面才是我的那一版」的判断。

## 数据源

主源 **NeoDB**（AGPL，开源联邦目录；API 直接给封面，中文覆盖好）。兜底：

| 类型 | 顺序 |
|---|---|
| book | NeoDB → Open Library |
| film | NeoDB → TMDB（有 `TMDB_API_KEY` 时）→ Wikipedia（frontmatter 有 `wiki`/`alt` 时） |
| music | NeoDB → iTunes Search API |

不使用浏览器抓豆瓣。NeoDB 已经聚合豆瓣、MusicBrainz、Apple Music 等来源。

## 匹配

`match.py` 是纯函数：标题相似度 + 包含关系 + creator + 年份 − 版本惩罚。
NeoDB 的 `localized_title`（中文/英文别名）会一起参与匹配，所以《花样年华》能对上
`In the Mood for Love`；但同名/同系列仍可能并列（如 2001 短片），由你在候选页里挑。

低置信度/版本词/不同作品接近时，**不自动选**；`find` 只展示，`apply` 需要 `--pick`。

## 可选：批量模式

`coverfetch.py` + `items.json` 是探索/回归用的批量工具，**不是维护主路径**。
它读一份清单、跑多源、出 manifest/report/preview。新条目不要往这里加；用
`note_cover.py` 对着笔记跑。

```bash
python3 coverfetch.py fetch --limit-per-type 8
python3 -m http.server 8098 --directory out   # out/preview.html
```

## 文件

```
note_cover.py   单篇 serve（视觉选封面）/ find / apply / enrich（书影音专用）
sources.py      NeoDB / TMDB / Wikipedia / Open Library / iTunes 适配
match.py        标题/别名/creator/年份打分
imageops.py     下载、校验、cwebp 压图、hash、尺寸
store.py        批量模式的缓存/限流
coverfetch.py   批量探索工具（可选）
ui.py           静态 UI 原型：书架 / 胶片夹 / 磁带夹
items.json      批量工具的示例清单（不是维护单位）
tests/          离线匹配测试：python3 -m unittest discover -s tests
out/            生成物（gitignore）
```

## 限制与版权

- NeoDB 是社区实例，会限流/超时；`find` 失败就重试或换源，缓存不是必需。
- 电影条目常只有英文名；在 frontmatter 里补 `wiki: In the Mood for Love` 可显著提高召回。
- 封面版权归原权利人；个人非商业站使用并在页脚注明来源。不要热链，下载到自己的 OSS/内容仓。
- 这是 authoring-time 工具：不在浏览器里抓，不在页面里调 API。
