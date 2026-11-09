# prosopon-source — 数字花园的内容源(Quartz content vault)

> 本 repo 是 **[prosopon-engine](../prosopon-engine)(Quartz)的内容源**;内容是**本体**,engine 是可换载体(图=本体,见下第一层)。
> 一句话定位:这里放 markdown + 随文图/视频,被 Quartz 构建成 junhangc.cn,将来也被发布 skill 读去发小红书——**一本体,多载体**。

---

## 核心原则:格式是 md 的「增量」,不是「干扰项」

你的写作流程 = **普通 md**:
0. (可选)写完先跑 `bash scripts/genfront.sh <file>` 生成 frontmatter 骨架(机械部分),智能补全交 agent。
1. 在编辑器(cweijan / Obsidian / 任意)里写正文,粘贴图片(cweijan 自动存到 `当前folder/image/<文件名>/<时间戳>.png`,写成标准相对路径——**顺其自然,别手改**)。
2. 写完把草稿交给 agent:**agent 按本文件第三层,补齐 frontmatter、规整 cover,不碰你的正文文字。**

你不用记格式;格式负担由 agent 消化。下面三层:第一层是「为什么」(上游认知),第二层是「写时要知道的最小集」,第三层是「agent 补全的细则」。

---

## 第一层(meta · 为什么这样组织)

完整认知在上游(**不在本 repo**,是 prosopon 域的决策):
**`~/workspace/oikos/prosopon/hypertext-数字花园.md`** —— hypertext / 「图本链末」/ 认知三态(图-树-链)/ **组织的三正交零件**(frontmatter 语义 · wikilink 图的边 · folder 物理层)。

一句话够用:**组织靠 frontmatter(查询生成视图)+ wikilink(图的边),folder 只管物理整齐与面包屑。** 领域/时间线/tag 页都是 transform 读 frontmatter **自动生成**的,不是手搭的。

---

### 参考区 `content/_refer/`(预览可见、上线忽略)

放示例/草稿/写作参考:本地 `preview.sh` 照常渲染,**上线自动忽略**。
机制(复用 Quartz 原生规则):`deploy.sh` 设 `QUARTZ_PROD=1` → engine 的 `quartz.ts` 里 `ignorePatterns` 才追加 `_refer/**`;预览不设,故可见。目录内示例见 `_refer/README-图文混排.md`。

### 图文混排(md 只到块级图;布局用 raw HTML + 工具类)

Quartz 会解析 raw HTML(rehype-raw),它照常进 AST、**里面的图照样被扁平化到 OSS**——不破管线。规则:

- **图片一律相对路径** `![](image/..)` 或 `<img src="image/..">`。**别用 `![[图|宽]]`**——能显示但绕过扁平化(走 ECS)、普通预览也不认。
- 块级图(默认上下排)用 md `![]()` 即可;要尺寸/布局再用 HTML。
- 现成工具类(engine `custom.scss`):

| 想要 | 写法 |
|---|---|
| 并排 2 / 3 张 | `<div class="grid2">…</div>` / `<div class="grid3">…</div>` |
| 自适应画廊(任意张) | `<div class="gallery">` + 若干 `<img>` |
| 带图注 | `<figure><img src="image/.." width="460"><figcaption>说明</figcaption></figure>` |
| 文字绕图 | `<img class="float-right" src="image/.." width="220">` **空一行** 再写正文,段落末尾 `<div class="clearfix"></div>` |

⚠️ raw HTML 块**内部的 markdown 不解析**(`**粗体**`、`[[双链]]` 在 HTML 里不生效)。尤其:**`<img>` 和正文之间必须空一行**,否则正文被吸进 HTML 块、不是独立 `<p>`,float 就没东西可绕(实测踩坑)。绕图适合横图/方图,竖长图会把文字挤成窄缝。
✅ 移动端 grid/float 已自动降级(单列 / 不浮动)。

### Bases（v5）：`*.base` = 查询 + 视图

v5 起支持 Obsidian Bases。`.base` 是 YAML 查询/视图配置，**数据仍在每篇 note 的 frontmatter 里**：

```yaml
filters:
  and:
    - file.inFolder("mouseion/books")
    - file.hasProperty("cover")
views:
  - type: cards
    name: Cards
  - type: table
    name: All
  - type: gallery
    name: Gallery
  - type: board
    name: Board
  - type: list
    name: List
```

- 一个条目 = 一篇 note（如 `mouseion/film/花样年华.md`，frontmatter 写 `medium/creator/year/...`）。
- 视图：`cards` / `table` / `gallery` / `board` / `list`；`/mouseion/*` 页面**默认 Cards**。
- `/mouseion/` 综合页用 `mouseion` custom view（书架 / 胶片夹 / 密铺封面墙）；`/mouseion/{books,film,music}/` 用嵌入 `.base` 的原生视图。
- 独立子域 `mouseion.junhangc.cn` 是同一内容的第二载体：主站 build 产 `static/mouseion.json`，独立站消费；条目点击回主站 note 页。
- 内容分类仍只认 folder；Bases 是**读 frontmatter 的派生视图**，不是新分类轴。

## 第二层(Quartz 规则 · 写时的最小集)

- **文本链接 = wikilink `[[标题]]`**:只写文件名(不带路径),Quartz 按名全局解析,**跨 folder、挪 folder 都不断**。本地普通预览显字面(可读不可点);用 Obsidian 可点。**不模糊**——错字/异大小写会静默死链,需要别名就在目标 frontmatter 加 `aliases: [...]`。
- **图片 = 标准相对路径 `![](相对路径)`**(cweijan 粘图即此,顺其自然)。本地普通预览直接认;上线由 engine 的自定义 transformer `FlattenLocalAssets` 在构建时改写成扁平 `/assets/<hash>`(解决 Quartz flat-url 下标准相对图会碎的坑,并与 slug/OSS 解耦)。**作者不用管**——写标准相对即可,两端都完整。别手写 `![[图]]`(本地预览器不认)。
- **folder = 大类物理分组**(定稿:`生活/工作/读书/新知/随笔` + `mouseion/{books,film,music}`):给面包屑用。领域/主题**不靠 folder**,靠 frontmatter。
- **assets 不手动搬**:图放哪个 folder 都行,`FlattenLocalAssets` + `AssetManifest` 构建时统一扁平化到 `/assets/<hash>`、出 `assets-manifest.json`;生产图走 OSS。

### frontmatter schema(双用:花园展示 + 小红书 SoT)

```yaml
title:        # 必填。标题(也是 wikilink 目标名,全局唯一)
date:         # 有则显示,无则留白(绝不用 git/文件时间伪造)。YYYY-MM-DD
modified:     # 可选。YYYY-MM-DD
tags: []      # 主题标签(驱动 tag 页/graph)
domain:       # 可选。所属域:cliopolis|beautyseek|agora|storgeros|oikonomia|prosopon
description:  # 一句话。用于卡片摘要 + SEO + 小红书 caption 种子
cover:        # 卡片缩略图。★从 content 根算的相对路径★(不是相对本文);构建时自动扁平化
platforms: [] # 可选。发布目标,如 [xiaohongshu]
status:       # 可选。draft | published
source:       # 可选。摘录/外链的出处
```

**内容分类只用 folder,不用 `type` 字段**:长文放主题 folder(历史/思考/…),短内容统一放 `随笔/`。
「长文 vs 短文」信息量太低,不配一个字段——folder 位置即分类。

### 书影音（MOUSEION）专用 frontmatter

`content/mouseion/` 的条目由 `scripts/gencover.sh` 生成/补全，**不使用 genfront 的通用骨架**：

```yaml
title:       # 条目标题（歌曲/专辑/电影/书）
medium:      # book | film | music
added:       # YYYY-MM-DD
cover:       # 从 content 根算相对路径，构建时扁平化到 OSS
cover_source:  # neodb:<id> | netease:<id> | generated
cover_status:  # manual | auto | fallback
creator:     # 作者/导演/艺人
year:
description: # 短摘要（正文 gencover 区块有完整背景）
raw_tags: [] # **原始标签**（NeoDB 等），保留，不驱动 tag 页
tags: []     # **人工策展标签**；gencover 只写一个粗分类(书/电影/音乐)
source:      # neodb | netease
source_id / source_url
# 类型特有：director/cast/genres/release_date/country；author/publisher/isbn/pages；artist/label/track_count
```

- **音乐的心智模型（2026-11-09 定）**：**歌是基本单位，专辑只是统计维度**（流媒体之后人们以歌接触音乐；专辑是买盘时代的心智单位）。所以 `mouseion/music` 下**一个 md = 一首歌（作品）**，专辑不是实体、不建 md，只下沉为字段（`album / album_id / album_url / album_rating`，`description` 保留专辑短简介，正文 `## 专辑` 保留完整简介）。
- **同名多版本合并**：`真夜中のドア` 的多个版本、`明天会更好` 原版/Live 都放在**同一个 md** 的 `## 版本` 段；合并口径是"同一作品"（去尾部括号后标题相同），同名但不同作品用 `标题（艺人）` 消歧。
- **正文（音乐条目）固定结构**：`cover block` → `## 版本`（播放器 UI）→ `## 专辑`（简介 + 专辑字段 + 资料链接）。
  - `## 版本` 是 `<div class="ncm-player">`（样式在 engine `custom.scss`）：播放钮链专辑页，每行 `序号 / 版本名 + 艺人·专辑 / 时长` 链单曲页。**是外观，不是内嵌播放**——网易云 outchain iframe 在第三方域报「资源加载失败」（`player/url` 对 `fee=1` 返回 `code:-110`），mp3 直链也已 404。
- **迁移工具**：`scripts/migrate_music_to_songs.py` 把专辑级条目转成歌曲级（从既有专辑条目提取简介/评分/封面，按标题聚合版本）。`scripts/import_netease.py` 目前仍是专辑级导入，需加 `--legacy-album-model` 才运行，避免在歌曲级仓库里重新造出专辑条目。

- **tags 是认知/审美策展字段**：目前是 32 个受控 facet（中国/历史/微观史/犯罪/黑色幽默/OST/器乐/华语/…），不再使用 NeoDB 原始标签直接生成 tag 页。
- `raw_tags` 保留原始数据，供以后人工筛选；不参与 tag 页。
- 正文封面由 `gencover` 生成并 URL-encode；不要手写带空格的 `![](image/Way Back...)`（Markdown 不会识别为图片）。
- 独立站 `mouseion.junhangc.cn` 只读 `static/mouseion.json` 投影；内容改动仍以主站构建为准。

---

## 第三层(agent reviewer 职责 · quartz 感知 + 内容感知)

当用户交来一篇草稿(正文 + 已粘的图),agent 扮演 **「Quartz 感知 + 内容感知的 reviewer」**,执行:

1. **读正文,推断并补 frontmatter**(内容感知):
   - `title`:取一级标题或首句凝练;确保**全局唯一**(撞名则加限定词,否则 wikilink 会歧义)。
   - **folder**:判断放哪——长文归主题大类(历史/思考/…),短内容归 `随笔/`。不写 type 字段。
   - `date`:正文里有写(如「crystal 自 2026-08-24」)就抽出来补上;没有就**留空**(宁可不显示,不伪造)。
   - `tags`:从正文主题抽 2–4 个;`domain`:映射到 oikos 域(可留空)。**书影音条目例外**:`raw_tags` 保留源标签，`tags` 只用一个粗分类，facet 由人工策展。
   - `description`:一句话概括(≤40 字),供卡片/小红书 caption。
2. **cover(关键·路径规整)**:取**正文第一张图**作 cover;把它的相对路径转成**从 content 根的路径**(= 该 md 所在 folder 前缀 + 正文相对路径)。例:`生活/十月的光.md` 正文 `![](image/十月的光/x.png)` → `cover: 生活/image/十月的光/x.png`。CardList 按根解析 cover,故必须从根写。
3. **图片规整(仅当发现 `![[...]]` 图)**:把 wikilink 图改成标准相对 `![](...)`(保本地预览)。正常 cweijan 粘的无需动。
4. **发布意图**:正文提到"发小红书"类意图时,补 `platforms: [xiaohongshu]` + `status: draft`;note 旁的图集即小红书轮播图源。
5. **纪律**:**不改正文文字**(增量不干扰);不删用户的 wikilink;脱敏内部标记(`[溯因]`/`[leaky]`/原声)是**单独一步**,非本职除非用户要。

> 本文件是 living 的:规则随实践调整。图片/链接的机制依据见第一层指针的 §1.4/§1.5a/§1.6。
