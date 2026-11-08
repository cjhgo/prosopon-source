# scripts — 本地预览 + 上线

两个脚本把「写内容」和「engine 构建 / VPS 部署」解耦,你在 prosopon-source 里只管内容。

```bash
scripts/preview.sh [端口]        # 本地预览(默认 8080,热重载),改 md 自动刷新
scripts/deploy.sh  [子域名]      # 构建 + 上线(默认 quartz.junhangc.cn)
```

## 依赖与约定

- **三仓平级**:`~/workspace/{prosopon-source, prosopon-engine, oikos}`。脚本自动按相对路径找 engine 和 aliyun-ops;不平级则设环境变量:
  - `PROSOPON_ENGINE=/path/to/prosopon-engine`
  - `ALIYUN_OPS=/path/to/oikos/prosopon/skills/aliyun-ops`
  - `PROSOPON_DOMAIN=子域名`(或 deploy.sh 第一个参数)
- **node 走 nvm**(非 brew);脚本自动把 nvm 最新 node 加进 PATH。
- 预览 = `quartz build -d content --serve`;上线 = 构建 public/ 后交 `aliyun-ops vps deploy-dir`(分块传 + nginx vhost + cert-aware HTTPS)。

## 流水线

```
prosopon-source/content/*.md  ──preview──▶  localhost:8080
                              ──deploy───▶  Quartz build → public/ → vps deploy-dir → https://<子域名>
```

内容是本体,engine 是可换载体,aliyun-ops 是部署手——三者在此拼成一条线。
