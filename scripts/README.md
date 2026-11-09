# scripts — 本地预览 + 上线

两个脚本把「写内容」和「engine 构建 / VPS 部署」解耦,你在 prosopon-source 里只管内容。

```bash
scripts/genfront.sh <file.md> [...] # 补 frontmatter 骨架(title/date/tags/description 占位,幂等)
scripts/preview.sh [端口]        # 本地预览(默认 8080,热重载),改 md 自动刷新
scripts/deploy.sh  [子域名]      # 构建 + 上线主站 + MOUSEION 子域(默认 prosopon/mouseion.junhangc.cn)
scripts/gencover.sh             # 单篇书影音:专用 frontmatter + 选封面 + 元数据/背景(不调用 genfront)
```

## 依赖与约定

- **三仓平级**:`~/workspace/{prosopon-source, prosopon-engine, oikos}`。脚本自动按相对路径找 engine 和 aliyun-ops;不平级则设环境变量:
  - `PROSOPON_ENGINE=/path/to/prosopon-engine`
  - `ALIYUN_OPS=/path/to/oikos/prosopon/skills/aliyun-ops`
  - `PROSOPON_DOMAIN=子域名`(或 deploy.sh 第一个参数)
- **node 走 nvm**(非 brew);脚本自动把 nvm 最新 node 加进 PATH。
- **engine 已迁 Quartz v5**:官方插件是 npm 依赖(根 `npm install` 即装);og-image 用 engine 内 `vendor/og-image` fork(已带 `dist/`),无需额外步骤。
- 预览 = `quartz build -d content --serve`；上线 = `scripts/deploy.sh`：主站 build + feed → assets OSS 增量 → MOUSEION 静态站 → 主站 HTML，均交 `aliyun-ops vps deploy-dir`（vhost + cert-aware HTTPS）。

## 流水线

```
prosopon-source/content/*.md  ──preview──▶  localhost:8080
                              ──deploy───▶  Quartz build → public/ → vps deploy-dir → https://prosopon.junhangc.cn
                                                   │
                                                   └─ static/mouseion.json → mouseion-site/build.py → vps deploy-dir → https://mouseion.junhangc.cn
```

- 主站是 SoT/canonical note 页；`mouseion.junhangc.cn` 是同一内容的独立全屏载体，条目链接回主站。
- deploy 缓存：OG/字体/扁平图在 engine `.quartz-cache/`；OSS 用内容 hash `--ignore-existing`，只传新图。

内容是本体,engine 是可换载体,aliyun-ops 是部署手——三者在此拼成一条线。

## genfront.sh 说明

只做**机械格式化**,智能内容留给 agent(reviewer):
- 无 frontmatter → 插入 `title`(取首个 `#` 标题并从正文移除)、`date`(文件修改日)、`tags: []`、`description: ""`。
- 有 frontmatter → 只补缺失键,不覆盖已有值,幂等。
- **不做**:tags 具体内容、description 文案、cover、domain、platforms —— 这些交 agent 按 `CLAUDE.md` 第三层补。
