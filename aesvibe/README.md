# aesvibe — 私人小站

`https://www.aesvibe.fun/` 的内容源。和 `content/`（主花园）隔离，不共用站点配置、主题、ICP、导航。

## 写

```
content/
  index.md
  notes/        # 短笔记/碎片
  visual/       # 图/视觉（图放 visual/images/，md 里用相对路径）
  about.md
```

最小 frontmatter：

```yaml
---
title: 标题
date: 2026-11-10
tags: [随手]
description: 一句话
draft: false      # true = 不发布
---
```

图片：md 里写普通相对路径，例如 `![x](images/test.svg)`。

## 预览 / 发布

```bash
# 本地预览（per-md 相对图，不走 OSS）
scripts/preview.sh          # http://localhost:8099

# 发布到香港 OSS
scripts/publish.sh
```

`publish.sh` 做三件事：

1. `QUARTZ_SITE=aesvibe` + `QUARTZ_CONFIG=aesvibe/quartz.config.yaml` 构建
2. `postbuild.py`：内部链接补 `.html`（OSS 没有 nginx `$uri.html` 回退）、注入 `noindex`、写 `robots.txt`、删 `assets-manifest.json` 等
3. `bin/oss sync-site public/ --bucket aesvibe-fun --region cn-hongkong`（`--delete` 清 stale）

**图片和 HTML 同桶**：生产时 `FLATTEN_ASSETS=1`、`ASSET_BASE_URL` 留空 → `public/assets/<hash>`，HTML 引用 `/assets/<hash>`；一次 sync 全上去。预览时不扁平化，按 per-md 相对路径。

## 隔离规则

- 不链回 `prosopon.junhangc.cn` / `junhangc.cn`
- 不引用 `assets.junhangc.cn`
- 页面全量 `noindex,nofollow` + `robots.txt: Disallow: /`
- 无 analytics
- 站点在 `www`；apex `aesvibe.fun` 只走邮箱（MX/SPF），不要 CNAME apex

## 实现位置

- 站点配置：`aesvibe/quartz.config.yaml`
- 站点定制：`prosopon-engine/quartz/sites/aesvibe/site.ts`
- 共享 engine：`prosopon-engine/quartz/quartz.ts`（`QUARTZ_SITE` 选 profile，`QUARTZ_CONFIG` 选 YAML）
- OSS 原语：`oikos/prosopon/skills/aliyun-ops/bin/oss`（`sync-site`）
