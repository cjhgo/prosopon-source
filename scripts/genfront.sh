#!/usr/bin/env bash
# genfront.sh — 给 markdown 快速补 frontmatter(只做机械格式化,智能内容留给 agent/reviewer)。
# 用法: scripts/genfront.sh <file.md> [file2.md ...]
#
# 做什么:
#   - 无 frontmatter:插入 title(取首个 # 一级标题,取走后从正文删除)、date(文件修改日期)、
#     tags: []、description: "" 占位;正文原样保留。
#   - 已有 frontmatter:只**补齐缺失**的 title/date/tags/description,不覆盖已有值。
#   - 幂等:重复跑不会重复插入。
# 不做什么(留给 agent 按 prosopon-source/CLAUDE.md 第三层智能补):
#   tags 的具体内容、description 文案、cover 路径、domain、platforms。
set -euo pipefail

[ $# -ge 1 ] || { echo "用法: genfront.sh <file.md> [...]"; exit 1; }

python3 - "$@" <<'PY'
import sys, os, re, datetime

FIELDS = ["title", "date", "tags", "description"]

def mtime_date(path):
    try:
        ts = os.stat(path).st_mtime
        return datetime.date.fromtimestamp(ts).isoformat()
    except OSError:
        return datetime.date.today().isoformat()

def yaml_val(s):
    # 需要时加引号(含冒号/井号/首尾特殊)。
    if s == "" or re.search(r'[:#\[\]{},&*!|>\'"%@`]', s) or s != s.strip():
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return s

def process(path):
    if not os.path.isfile(path):
        print(f"✗ 不存在: {path}"); return 1
    text = open(path, encoding="utf-8").read()
    norm = text.replace("\r\n", "\n")
    has_fm = norm.startswith("---\n")

    if has_fm:
        # 解析已有 frontmatter
        end = norm.find("\n---", 4)
        if end == -1:
            print(f"⚠ {path}: 有 --- 开头但找不到结束 ---,跳过"); return 1
        fm_block = norm[4:end]
        body = norm[end + 4:]
        existing = {}
        for line in fm_block.splitlines():
            m = re.match(r'^([A-Za-z_]+):\s*(.*)$', line)
            if m:
                existing[m.group(1)] = m.group(2)
        adds = []
        for k in FIELDS:
            if k not in existing:
                if k == "title":
                    h1 = re.search(r'^#\s+(.+)$', body, re.M)
                    val = yaml_val(h1.group(1).strip()) if h1 else yaml_val(os.path.splitext(os.path.basename(path))[0])
                    adds.append(f"title: {val}")
                elif k == "date":
                    adds.append(f"date: {mtime_date(path)}")
                elif k == "tags":
                    adds.append("tags: []")
                else:
                    adds.append('description: ""')
        if not adds:
            print(f"✓ {path}: frontmatter 已完整,跳过"); return 0
        new_fm = fm_block.rstrip("\n") + "\n" + "\n".join(adds)
        open(path, "w", encoding="utf-8").write("---\n" + new_fm + "\n---" + body)
        print(f"✓ {path}: 补齐 {', '.join(a.split(':')[0] for a in adds)}")
        return 0

    # 无 frontmatter:提取 H1 作 title 并从正文移除(避免标题重复)
    body = norm
    m = re.search(r'^#\s+(.+)$\n?', body, re.M)
    if m:
        title = m.group(1).strip()
        body = body[:m.start()] + body[m.end():]
    else:
        title = os.path.splitext(os.path.basename(path))[0]
    body = body.lstrip("\n")
    fm = (
        "---\n"
        f"title: {yaml_val(title)}\n"
        f"date: {mtime_date(path)}\n"
        "tags: []\n"
        'description: ""\n'
        "---\n\n"
    )
    open(path, "w", encoding="utf-8").write(fm + body)
    print(f"✓ {path}: 插入 frontmatter(title={title})")
    return 0

rc = 0
for p in sys.argv[1:]:
    rc = process(p) or rc
sys.exit(rc)
PY
