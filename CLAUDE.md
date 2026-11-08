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

## 第二层(Quartz 规则 · 写时的最小集)

- **文本链接 = wikilink `[[标题]]`**:只写文件名(不带路径),Quartz 按名全局解析,**跨 folder、挪 folder 都不断**。本地普通预览显字面(可读不可点);用 Obsidian 可点。**不模糊**——错字/异大小写会静默死链,需要别名就在目标 frontmatter 加 `aliases: [...]`。
- **图片 = 标准相对路径 `![](相对路径)`**(cweijan 粘图即此,顺其自然)。本地普通预览直接认;上线由 engine 的自定义 transformer `LocalImageToWikilink` 在构建时转成 wikilink 逻辑(解决 Quartz flat-url 下标准相对图会碎的坑)。**作者不用管**——写标准相对即可,两端都完整。别手写 `![[图]]`(本地预览器不认)。
- **folder = 大类物理分组**(当前占位 `历史/生活/思考`,命名待定):给面包屑用。领域/主题**不靠 folder**,靠 frontmatter。
- **assets 不手动搬**:图放哪个 folder 都行,Quartz 的 Assets+CrawlLinks 构建时统一搬到 public、改写引用。

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

---

## 第三层(agent reviewer 职责 · quartz 感知 + 内容感知)

当用户交来一篇草稿(正文 + 已粘的图),agent 扮演 **「Quartz 感知 + 内容感知的 reviewer」**,执行:

1. **读正文,推断并补 frontmatter**(内容感知):
   - `title`:取一级标题或首句凝练;确保**全局唯一**(撞名则加限定词,否则 wikilink 会歧义)。
   - **folder**:判断放哪——长文归主题大类(历史/思考/…),短内容归 `随笔/`。不写 type 字段。
   - `date`:正文里有写(如「crystal 自 2026-08-24」)就抽出来补上;没有就**留空**(宁可不显示,不伪造)。
   - `tags`:从正文主题抽 2–4 个;`domain`:映射到 oikos 域(可留空)。
   - `description`:一句话概括(≤40 字),供卡片/小红书 caption。
2. **cover(关键·路径规整)**:取**正文第一张图**作 cover;把它的相对路径转成**从 content 根的路径**(= 该 md 所在 folder 前缀 + 正文相对路径)。例:`生活/十月的光.md` 正文 `![](image/十月的光/x.png)` → `cover: 生活/image/十月的光/x.png`。CardList 按根解析 cover,故必须从根写。
3. **图片规整(仅当发现 `![[...]]` 图)**:把 wikilink 图改成标准相对 `![](...)`(保本地预览)。正常 cweijan 粘的无需动。
4. **发布意图**:正文提到"发小红书"类意图时,补 `platforms: [xiaohongshu]` + `status: draft`;note 旁的图集即小红书轮播图源。
5. **纪律**:**不改正文文字**(增量不干扰);不删用户的 wikilink;脱敏内部标记(`[溯因]`/`[leaky]`/原声)是**单独一步**,非本职除非用户要。

> 本文件是 living 的:规则随实践调整。图片/链接的机制依据见第一层指针的 §1.4/§1.5a/§1.6。
