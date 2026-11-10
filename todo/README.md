# todo.junhangc.cn

一棵可 zoom 的待办大纲。交互范式参考 [Dynalist](https://dynalist.io/)（Obsidian 团队 2016 年的前作）：无限嵌套的条目、zoom 进出、键盘优先、行内格式。差别是组织单位——这里用**文档 / 文件夹**，不是「智能视图」；另外补了多空间与只读分享。

设计上刻意做了三个"反潮流"的选择：

1. **零依赖**：只用 node stdlib（`http`/`fs`/`crypto`），没有 npm install，没有构建步骤。
2. **每个空间一个 JSON**：写入走临时文件 + `rename` 原子替换，每次保存前留 `data/history/` 快照（滚动保留 200 份）。
3. **代码与状态分离**：代码在 `/www/wwwroot/todo.junhangc.cn/`，状态在 `/var/lib/todo-junhangc/`；重复部署只覆盖代码，数据不动。

## 自用 + 分享：三个概念

| 概念 | 作用 |
|---|---|
| **space** | 一个独立空间（自己的文件树 + 文档 + 设置），互相不可见 |
| **密码** | 空间身份：可读写。给朋友密码 = 让 TA 能一起改 |
| **只读分享 token** | 免登录链接，只能看和搜，不能改；随时关闭/换新；不受改密码影响 |

页面分区：

```
/            落地页：介绍 + 创建入口 + 进入我的空间
/me          跳转到 owner 空间（/s/me）
/s/<id>      某个空间
/s/<id>?share=<token>   只读链接，验证后种 viewer cookie 并跳回 /s/<id>
```

- **自用**：`/me` → 密码登录。owner 空间 id 固定为 `me`。
- **分享给别人用（各用各的）**：朋友在落地页创建自己的空间，数据完全隔离；需要邀请码时在部署里设 `TODO_INVITE`。
- **分享给朋友看**：设置里生成只读链接。
- 创建入口按 IP 限流（5 次/小时），登录 30 次/分钟。

## 功能

**多根文件组织（My files）**
- 左侧是真正的文件/文件夹树：文档可以有多个根，文件夹可无限嵌套
- 新建文档 / 新建文件夹；双击或菜单重命名；拖拽或「移动到文件夹…」调整归属；删除带确认
- 每个文档一棵独立大纲，文档标题可直接点开改；侧栏显示每个文档的未完成数
- 深链：`/s/<space>/#d=<docId>`，条目再加 `&z=<nodeId>`

**大纲**
- 无限嵌套；`Enter` 新建同级、`Tab` / `⇧Tab` 缩进提升、点圆点折叠、悬停放大镜或双击 zoom、面包屑回退
- 拖拽换父/换序；条目菜单可 duplicate / move / sort / delete
- 编号子项、标题 1–3、6 种颜色标签

**内容**
- 每条有正文 + 备注（`⇧Enter`），备注显示为第二行灰字
- 行内 Markdown：`**粗体**` `__斜体__` `~~删除线~~` `==高亮==` `` `代码` `` `[文字](链接)`
- `#标签` 自动识别；截止日期 `📅`，逾期标红
- 快速收集 `⌘⇧I`

**工具**
- 搜索跨本空间所有文档，支持 `#tag`、`is:done`、`is:undone`、`has:due`、`due:today`、`due:overdue`
- 撤销 / 重做（`⌘Z` / `⌘⇧Z`）覆盖文档与条目操作
- 设置：主题、密度、字号、窄版、显示备注/已完成（存服务端）；只读分享；改密码
- 导出 Markdown / JSON；快捷键面板 `⌘/`；移动端底部编辑工具条

## 后端

| 路由 | 说明 |
|---|---|
| `GET /api/health` | 无需登录 |
| `GET /api/space?space=` | 空间名（登录页用） |
| `POST /api/spaces` | 创建空间 `{name,password,invite}`，创建者即 owner |
| `POST /api/login` | `{spaceId,password}` → HMAC cookie（含空间、角色、会话版本） |
| `GET /api/session?space=` | `{authed, role, name}` |
| `GET /api/state?space=` | workspace；viewer 也能读 |
| `PUT /api/state?space=` | 仅 owner；带 `version` 乐观锁，落后返回 `409` |
| `GET/POST /api/share?space=` | owner 生成 / 关闭只读链接 |
| `POST /api/password?space=` | owner 改密码；`sessionVersion+1` 使其它设备失效 |

数据布局：

```
data/spaces/index.json    {ownerId, spaces:{id:{name,salt,passHash,shareToken,sessionVersion}}}
data/spaces/<id>.json     {version, updatedAt, explorer, docs, settings}
data/history/             每次保存的快照
```

密码用 scrypt 加盐哈希。旧版单树数据在首次启动时自动迁移成 owner 空间 `/s/me`，不丢数据。

### 前端结构

```
public/
  landing.html/css/js   落地页与创建空间
  index.html            空间 app 壳
  app.js / model.js / markdown.js / style.css
```

## 部署

```bash
todo/deploy.sh                          # 复用 ~/.config/todo/password
TODO_PASSWORD=xxx todo/deploy.sh        # 仅影响首次迁移出的 owner 空间密码
TODO_INVITE=xxxx todo/deploy.sh         # 创建空间需要邀请码（不设则开放、按 IP 限流）
```

链路：

```
DNS: acs dns add-a todo                 → todo.junhangc.cn → 8.146.205.93
代码: vps serve（OSS 中转 tar）          → /www/wwwroot/todo.junhangc.cn
状态: DATA_DIR=/var/lib/todo-junhangc   → 重复部署不碰
进程: systemd todo-junhangc.service     → node server.js, Restart=always
证书: 复用 *.junhangc.cn
出口: nginx 反代 → 127.0.0.1:3020       → 内部端口不进安全组
```

`TODO_PASSWORD` 只用于**第一次**迁移；之后密码以空间内设置为准（设置 → 修改密码）。改密码会让自己其它设备的登录失效。
