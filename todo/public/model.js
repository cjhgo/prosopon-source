/* 模型层：树的纯函数操作，不碰 DOM。 */

export const COLORS = ['red', 'orange', 'yellow', 'green', 'blue', 'purple'];

export const uid = (prefix = 'n') =>
  prefix + '_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

/** 文档：左侧文件树里的一个条目，自身带一棵独立大纲树 */
export function newDoc(title = '未命名文档') {
  const now = new Date().toISOString();
  return {
    id: uid('d'),
    title,
    created: now,
    updated: now,
    tree: { id: 'root', text: '', note: '', open: true, children: [] },
  };
}

/** 文件夹：只存在于 explorer 里，可嵌套 */
export function newFolder(title = '新建文件夹') {
  return { id: uid('f'), type: 'folder', title, open: true, children: [] };
}

export function findEntry(node, id, parent = null, depth = 0) {
  for (const entry of node.children || []) {
    if (entry.id === id) return { entry, parent: node, depth };
    if (entry.type === 'folder') {
      const hit = findEntry(entry, id, entry, depth + 1);
      if (hit) return hit;
    }
  }
  return null;
}

export function flattenEntries(node, depth = 0, out = []) {
  for (const entry of node.children || []) {
    out.push({ entry, parent: node, depth });
    if (entry.type === 'folder') flattenEntries(entry, depth + 1, out);
  }
  return out;
}

/** 把条目移到目标文件夹（targetId='root' 表示根） */
export function moveEntry(explorer, id, targetId) {
  const hit = findEntry(explorer, id);
  if (!hit) return false;
  if (id === targetId) return false;
  if (hit.entry.type === 'folder') {
    const target = targetId === 'root' ? explorer : findEntry(explorer, targetId)?.entry;
    if (target && containsEntry(hit.entry, targetId)) return false; // 不能移进自己的子树
  }
  hit.parent.children.splice(hit.parent.children.indexOf(hit.entry), 1);
  const target = targetId === 'root' ? explorer : findEntry(explorer, targetId)?.entry;
  if (!target || target.type !== 'folder') {
    hit.parent.children.push(hit.entry);
    return false;
  }
  target.open = true;
  target.children.push(hit.entry);
  return true;
}

export function containsEntry(folder, id) {
  if (folder.id === id) return true;
  return (folder.children || []).some((c) => containsEntry(c, id));
}

export function removeEntry(explorer, id) {
  const hit = findEntry(explorer, id);
  if (!hit) return null;
  hit.parent.children.splice(hit.parent.children.indexOf(hit.entry), 1);
  return hit.entry;
}

export function newNode(extra = {}) {
  return {
    id: uid(),
    text: '',
    note: '',
    done: false,
    open: true,
    due: null,
    color: null,
    heading: 0,
    numbered: false,
    children: [],
    ...extra,
  };
}

/** 找到节点：{node, parent, index, path[]}（path 为从 root 的子节点起的 id 链） */
export function find(tree, id, node = tree, parent = null, path = []) {
  if (node.id === id) return { node, parent, index: parent ? parent.children.indexOf(node) : -1, path };
  for (const child of node.children) {
    const hit = find(tree, id, child, node, [...path, child.id]);
    if (hit) return hit;
  }
  return null;
}

export function pathOf(tree, id) {
  const hit = find(tree, id);
  return hit ? hit.path : null;
}

export function nodeByPath(tree, path) {
  let node = tree;
  for (const id of path) {
    const next = node.children.find((c) => c.id === id);
    if (!next) return node;
    node = next;
  }
  return node;
}

export function counts(node) {
  let total = 0;
  let pending = 0;
  for (const c of node.children) {
    const sub = counts(c);
    total += 1 + sub.total;
    pending += (c.done ? 0 : 1) + sub.pending;
  }
  return { total, pending };
}

export function walk(node, cb, depth = 0, names = []) {
  for (const c of node.children) {
    cb(c, depth, names);
    walk(c, cb, depth + 1, [...names, c.text || '（未命名）']);
  }
}

/** 扁平化整棵树（用于搜索 / 视图 / 移动目标） */
export function flatten(tree) {
  const out = [];
  walk(tree, (node, depth, names) => {
    out.push({ node, depth, names });
  });
  return out;
}

export function tagsIn(text) {
  const out = [];
  const re = /(^|[\s(（])#([^\s#，。；、（）()]+)/gu;
  let m;
  while ((m = re.exec(text || ''))) out.push(m[2]);
  return out;
}

export function allTags(tree) {
  const counts = new Map();
  walk(tree, (node) => {
    for (const t of tagsIn(node.text)) counts.set(t, (counts.get(t) || 0) + 1);
  });
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
}

export function todayStr(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

export function dueState(due) {
  if (!due) return null;
  const today = todayStr();
  if (due < today) return 'overdue';
  if (due === today) return 'today';
  if (due <= todayStr(7)) return 'soon';
  return 'later';
}

export function formatDue(due) {
  if (!due) return '';
  const today = todayStr();
  const diff = Math.round((new Date(due + 'T00:00:00') - new Date(today + 'T00:00:00')) / 86400000);
  if (diff === 0) return '今天';
  if (diff === 1) return '明天';
  if (diff === -1) return '昨天';
  const d = new Date(due + 'T00:00:00');
  const sameYear = d.getFullYear() === new Date().getFullYear();
  const md = `${d.getMonth() + 1}月${d.getDate()}日`;
  return sameYear ? md : `${d.getFullYear()}年${md}`;
}

export function cloneWithNewIds(node) {
  return {
    ...node,
    id: uid(),
    children: node.children.map(cloneWithNewIds),
  };
}

/** id 是否在 node 的子树里（拖拽防环） */
export function contains(node, id) {
  if (node.id === id) return true;
  return node.children.some((c) => contains(c, id));
}

/** 把 id 节点移动到 target 的前/后/内部 */
export function moveNode(tree, id, targetId, position) {
  if (id === targetId) return false;
  const src = find(tree, id);
  if (!src) return false;
  const target = find(tree, targetId);
  if (!target) return false;
  if (contains(src.node, targetId)) return false; // 不能移进自己的子树

  src.parent.children.splice(src.index, 1);

  if (position === 'child') {
    target.node.open = true;
    target.node.children.push(src.node);
  } else if (position === 'before') {
    target.parent.children.splice(target.parent.children.indexOf(target.node), 0, src.node);
  } else {
    const i = target.parent.children.indexOf(target.node);
    target.parent.children.splice(i + 1, 0, src.node);
  }
  return true;
}

export function sortChildren(parent, mode) {
  const cmp = {
    'title-asc': (a, b) => (a.text || '').localeCompare(b.text || ''),
    'title-desc': (a, b) => (b.text || '').localeCompare(a.text || ''),
    'due-asc': (a, b) => (a.due || '9999') .localeCompare(b.due || '9999'),
    'due-desc': (a, b) => (b.due || '0000').localeCompare(a.due || '0000'),
    'done-last': (a, b) => Number(a.done) - Number(b.done),
    'done-first': (a, b) => Number(b.done) - Number(a.done),
  }[mode];
  if (!cmp) return;
  parent.children.sort(cmp);
}

export function cloneTree(tree) {
  return JSON.parse(JSON.stringify(tree));
}

/** 当前 zoom 视图里可见的 id（顺序 = 屏幕顺序） */
export function visibleIds(tree, zoom, showDone = true) {
  const start = nodeByPath(tree, zoom);
  const out = [];
  (function walker(node) {
    for (const c of node.children) {
      if (!showDone && c.done) continue;
      out.push(c.id);
      if (c.open) walker(c);
    }
  })(start);
  return out;
}

/** 按视图收集条目 */
export function collectView(tree, view, tag) {
  const rows = [];
  const today = todayStr();
  const week = todayStr(7);
  walk(tree, (node, depth, names) => {
    const path = names;
    if (view === 'tag') {
      if (!tagsIn(node.text).includes(tag)) return;
    } else if (view === 'inbox') {
      if (node.done) return;
    } else if (view === 'today') {
      if (node.done || !node.due || node.due > today) return;
    } else if (view === 'week') {
      if (node.done || !node.due || node.due > week) return;
    } else if (view === 'overdue') {
      if (node.done || !node.due || node.due >= today) return;
    } else if (view === 'done') {
      if (!node.done) return;
    }
    rows.push({ node, depth, names: path });
  });
  return rows;
}
