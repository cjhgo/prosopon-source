/* todo.junhangc.cn — 多文档大纲式 todo 的前端。 */
'use strict';

import {
  COLORS, uid, newNode, newDoc, newFolder, find, pathOf, nodeByPath, counts,
  flatten, tagsIn, todayStr, dueState, formatDue, cloneWithNewIds, contains,
  moveNode, sortChildren, visibleIds, findEntry, flattenEntries, moveEntry,
  removeEntry, containsEntry,
} from './model.js';
import { renderInline } from './markdown.js';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const listEl = $('#list');
const crumbsEl = $('#crumbs');
const statEl = $('#stat');
const saveEl = $('#save');
const sidebarEl = $('#sidebar');
const docTitleEl = $('#doc-title');
const docMetaEl = $('#doc-meta');

const DEFAULT_SETTINGS = {
  theme: 'auto', density: 'cozy', fontSize: 15, narrow: false,
  showNotes: true, showDone: true,
};

const state = {
  explorer: null,
  docs: {},
  docId: null,
  settings: { ...DEFAULT_SETTINGS },
  version: 0,
  zoom: [],
  dirty: false,
  closed: false,
  editing: null,
  undo: [],
  redo: [],
  role: null,
  spaceName: '',
};

function readonly() { return state.role === 'viewer'; }

function guard() {
  if (!readonly()) return true;
  toast('只读分享，不能修改');
  return false;
}

const PLAINTEXT = (() => {
  try {
    const d = document.createElement('div');
    d.contentEditable = 'plaintext-only';
    return d.contentEditable === 'plaintext-only';
  } catch { return false; }
})();
const CE = PLAINTEXT ? 'plaintext-only' : 'true';
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = isMac ? '⌘' : 'Ctrl';

const SPACE = (location.pathname.match(/^\/s\/([A-Za-z0-9_-]+)/) || [])[1] || '';
const api = (route) => `${route}?space=${encodeURIComponent(SPACE)}`;

// ------------------------------------------------------------------ 小工具

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function plain(text) {
  return String(text || '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_~=`]/g, '')
    .trim();
}

function currentDoc() { return state.docs[state.docId] || null; }
function docTree() { return currentDoc()?.tree || null; }
function hit(id) { return docTree() ? find(docTree(), id) : null; }
function currentNode() { return docTree() ? nodeByPath(docTree(), state.zoom) : null; }
function pendingIn(tree) { return flatten(tree).filter((x) => !x.node.done).length; }

function itemOf(id) {
  return listEl.querySelector(`.item[data-id="${CSS.escape(id)}"]`);
}

function caretEnd(node) {
  const range = document.createRange();
  range.selectNodeContents(node);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function toast(text) {
  let t = $('#toast');
  if (!t) { t = el('div', 'toast'); t.id = 'toast'; document.body.append(t); }
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => t.classList.remove('show'), 1600);
}

// ------------------------------------------------------------------ 保存

let saveTimer = null;

function setSave(text, isErr = false) {
  saveEl.textContent = text;
  saveEl.classList.toggle('err', isErr);
}

function scheduleSave() {
  if (state.closed) return;
  state.dirty = true;
  setSave('未保存');
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => save(), 500);
}

function payload() {
  return {
    version: state.version,
    explorer: state.explorer,
    docs: state.docs,
    settings: state.settings,
  };
}

async function save(force = false) {
  if (state.closed) return;
  clearTimeout(saveTimer);
  if (!state.dirty && !force) return;
  setSave('保存中…');
  try {
    const res = await fetch(api('/api/state'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload()),
    });
    if (res.status === 409) return showConflict(await res.json());
    if (res.status === 401) { setSave('登录已失效', true); return showLogin(); }
    if (res.status === 403) { setSave('只读分享', true); return; }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    state.version = data.version;
    state.dirty = false;
    setSave('已保存 ' + new Date().toTimeString().slice(0, 5));
  } catch {
    setSave('保存失败，稍后重试', true);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save(true), 3000);
  }
}

function flushSave() {
  if (!state.dirty) return;
  fetch(api('/api/state'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload()),
    keepalive: true,
  }).catch(() => {});
}
window.addEventListener('pagehide', flushSave);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flushSave();
});

// ------------------------------------------------------------------ 撤销

function snapshot() {
  state.undo.push(JSON.stringify({ explorer: state.explorer, docs: state.docs, docId: state.docId }));
  if (state.undo.length > 80) state.undo.shift();
  state.redo.length = 0;
}

function restore(raw) {
  const data = JSON.parse(raw);
  state.explorer = data.explorer;
  state.docs = data.docs;
  state.docId = data.docId;
  if (!state.docs[state.docId]) state.docId = firstDocId();
  state.zoom = state.zoom.filter((id) => hit(id));
  render();
}

function undo() {
  if (!state.undo.length) return;
  finishEdit(true);
  state.redo.push(JSON.stringify({ explorer: state.explorer, docs: state.docs, docId: state.docId }));
  restore(state.undo.pop());
  scheduleSave();
  setSave('已撤销');
}

function redo() {
  if (!state.redo.length) return;
  finishEdit(true);
  state.undo.push(JSON.stringify({ explorer: state.explorer, docs: state.docs, docId: state.docId }));
  restore(state.redo.pop());
  scheduleSave();
  setSave('已重做');
}

function firstDocId() {
  const docEntry = flattenEntries(state.explorer).find((x) => x.entry.type === 'doc');
  return docEntry ? docEntry.entry.id : null;
}

// ------------------------------------------------------------------ 设置

function applySettings() {
  const s = state.settings;
  document.documentElement.dataset.theme = s.theme;
  document.documentElement.dataset.density = s.density;
  document.documentElement.style.setProperty('--font-size', s.fontSize + 'px');
  document.body.classList.toggle('narrow', !!s.narrow);
}

// ------------------------------------------------------------------ 渲染

function render() {
  finishEdit(true);
  closeMenu();
  applySettings();
  if (!state.docs[state.docId]) state.docId = firstDocId();
  renderExplorer();
  renderDocHead();
  renderCrumbs();
  renderTree();
  renderStat();
  applyHash();
}

// ------------------------------ My files

function renderExplorer() {
  sidebarEl.textContent = '';

  const head = el('div', 'side-head');
  head.append(el('span', 'side-title', 'My files'));
  const add = el('button', 'side-icon', '＋');
  add.type = 'button';
  add.dataset.action = 'new-menu';
  add.title = '新建文档 / 文件夹';
  head.append(add);
  sidebarEl.append(head);

  const host = el('div', 'explorer');
  host.dataset.id = 'root';
  appendEntries(host, state.explorer, 0);
  sidebarEl.append(host);
}

function appendEntries(host, folder, depth) {
  for (const entry of folder.children || []) {
    host.append(entryEl(entry, depth));
    if (entry.type === 'folder' && entry.open) {
      const kids = el('div', 'entry-children');
      appendEntries(kids, entry, depth + 1);
      host.append(kids);
    }
  }
}

function entryEl(entry, depth) {
  const row = el('div', 'entry');
  row.dataset.id = entry.id;
  row.dataset.type = entry.type;
  row.dataset.depth = String(depth);
  row.draggable = true;
  if (entry.type === 'doc' && entry.id === state.docId) row.classList.add('on');

  if (entry.type === 'folder') {
    const caret = el('button', 'caret', entry.open ? '▾' : '▸');
    caret.type = 'button';
    caret.dataset.action = 'toggle-folder';
    row.append(caret);
  } else {
    row.append(el('span', 'caret-space'));
  }

  row.append(el('span', 'entry-ico', entry.type === 'folder' ? '📁' : '📄'));
  row.append(el('span', 'entry-title', entry.title));

  if (entry.type === 'doc') {
    const doc = state.docs[entry.id];
    const pending = doc ? pendingIn(doc.tree) : 0;
    row.append(el('span', 'entry-n', pending ? String(pending) : ''));
  } else {
    const n = countDocs(entry);
    row.append(el('span', 'entry-n', n ? String(n) : ''));
  }

  const more = el('button', 'entry-more', '⋯');
  more.type = 'button';
  more.dataset.action = 'entry-menu';
  row.append(more);
  return row;
}

function countDocs(folder) {
  return (folder.children || []).reduce((n, c) =>
    n + (c.type === 'doc' ? 1 : countDocs(c)), 0);
}

// ------------------------------ 文档

function renderDocHead() {
  const doc = currentDoc();
  if (!doc) {
    docTitleEl.textContent = '没有打开的文档';
    docMetaEl.textContent = '';
    return;
  }
  if (docTitleEl.textContent !== doc.title) docTitleEl.textContent = doc.title;
  const pending = pendingIn(doc.tree);
  docMetaEl.textContent = pending ? `${pending} 未完成` : '全部完成';
}

function renderCrumbs() {
  crumbsEl.textContent = '';
  const doc = currentDoc();
  if (!doc) return;
  crumbsEl.append(el('span', 'crumb-doc', plain(doc.title) || '未命名文档'));
  let node = doc.tree;
  const chain = [];
  for (const id of state.zoom) {
    const next = node.children.find((c) => c.id === id);
    if (!next) break;
    node = next;
    chain.push({ id: next.id, text: plain(next.text) || '（未命名）' });
  }
  for (const item of chain) {
    crumbsEl.append(el('span', 'sep', '›'));
    const btn = el('button', '', item.text);
    btn.type = 'button';
    btn.addEventListener('click', () => {
      const ids = [];
      let n = doc.tree;
      for (const id of state.zoom) {
        const c = n.children.find((x) => x.id === id);
        if (!c) break;
        n = c;
        ids.push(id);
        if (id === item.id) break;
      }
      state.zoom = ids;
      render();
    });
    crumbsEl.append(btn);
  }
}

function renderTree() {
  const doc = currentDoc();
  listEl.textContent = '';
  if (!doc) {
    listEl.dataset.view = 'empty';
    listEl.append(el('p', 'empty', '左侧还没有文档。点「＋」新建一个。'));
    return;
  }
  listEl.dataset.view = 'tree';
  const current = currentNode() || doc.tree;
  appendChildren(listEl, current, 0);
  if (!current.children.length) {
    listEl.append(el('p', 'empty', '这个文档还是空的 — Enter 或点「＋ 新条目」开始'));
  }
}

function appendChildren(host, parent, depth) {
  let i = 0;
  for (const node of parent.children) {
    if (!state.settings.showDone && node.done) continue;
    i += 1;
    host.appendChild(itemEl(node, depth, parent.numbered ? i : 0));
  }
}

function itemEl(node, depth, number = 0) {
  const item = el('div', 'item');
  item.dataset.id = node.id;
  if (node.done) item.classList.add('done');
  if (!node.open) item.classList.add('collapsed');
  if (node.color) item.classList.add('color-' + node.color);
  if (node.heading) item.classList.add('heading-' + node.heading);

  const row = el('div', 'row');
  const handle = el('span', 'handle');
  handle.title = '点圆点折叠；双击或放大镜 zoom；可拖动';
  handle.draggable = true;

  const zoom = el('button', 'zoom', '⌕');
  zoom.type = 'button';
  zoom.dataset.action = 'zoom';
  zoom.setAttribute('aria-label', 'zoom 进入');

  const bullet = el('span', 'bullet');
  bullet.dataset.action = 'toggle-open';
  handle.append(zoom, bullet);

  const check = el('input', 'check');
  check.type = 'checkbox';
  check.checked = !!node.done;
  check.setAttribute('aria-label', '完成');

  const wrap = el('div', 'text-wrap');
  const line = el('div', 'line');
  if (number) line.append(el('span', 'num', number + '.'));

  const view = el('div', 'text-view');
  view.tabIndex = 0;
  view.dataset.id = node.id;
  view.append(renderInline(node.text));
  if (!node.text) view.append(el('span', 'placeholder', '写点什么…'));

  const editor = el('div', 'text-editor');
  editor.contentEditable = CE;
  editor.spellcheck = false;
  editor.hidden = true;

  line.append(view, editor);
  wrap.append(line);

  if (state.settings.showNotes && node.note) {
    const noteView = el('div', 'note-view');
    noteView.append(renderInline(node.note));
    wrap.append(noteView);
  }

  if (node.due) {
    const meta = el('div', 'meta');
    const chip = el('button', 'due-chip ' + (dueState(node.due) || ''), '📅 ' + formatDue(node.due));
    chip.type = 'button';
    chip.dataset.action = 'due';
    chip.title = node.due + '（点按修改）';
    meta.append(chip);
    line.append(meta);
  }

  const n = counts(node);
  const count = el('span', 'count', node.children.length ? String(n.pending || n.total) : '');
  count.hidden = !node.children.length;
  count.title = `${n.pending} 未完成 / 共 ${n.total}`;

  const more = el('button', 'more', '⋯');
  more.type = 'button';
  more.dataset.action = 'menu';
  more.title = '条目操作';

  row.append(handle, check, wrap, count, more);
  item.append(row);

  const kids = el('div', 'children');
  item.append(kids);
  appendChildren(kids, node, depth + 1);
  return item;
}

function renderStat() {
  const doc = currentDoc();
  if (!doc) { statEl.textContent = ''; return; }
  const pending = pendingIn(doc.tree);
  statEl.textContent = pending ? `${pending} 未完成` : '全部完成';
}

function applyHash() {
  const parts = [];
  if (state.docId) parts.push('d=' + state.docId);
  const z = state.zoom[state.zoom.length - 1];
  if (z) parts.push('z=' + z);
  const target = parts.length ? '#' + parts.join('&') : '#';
  if (location.hash !== target) history.replaceState(null, '', target);
}

// ------------------------------------------------------------------ 文档操作

function openDoc(id) {
  if (!state.docs[id]) return;
  finishEdit();
  state.docId = id;
  state.zoom = [];
  render();
  window.scrollTo({ top: 0 });
}

function parentFolderOf(entryId) {
  const hitE = findEntry(state.explorer, entryId);
  return hitE ? hitE.parent : state.explorer;
}

function createDoc(insideFolder = null) {
  if (!guard()) return;
  snapshot();
  const doc = newDoc('未命名文档');
  state.docs[doc.id] = doc;
  const entry = { id: doc.id, type: 'doc', title: doc.title };

  let target = insideFolder || null;
  if (!target) {
    const active = findEntry(state.explorer, state.docId);
    target = active && active.parent.type === 'folder' ? active.parent : state.explorer;
  }
  target.open = true;
  const activeIdx = target.children.findIndex((c) => c.id === state.docId);
  if (activeIdx >= 0) target.children.splice(activeIdx + 1, 0, entry);
  else target.children.push(entry);

  state.docId = doc.id;
  render();
  scheduleSave();
  startRename(doc.id);
}

function createFolder(insideFolder = null) {
  if (!guard()) return;
  snapshot();
  const folder = newFolder('新建文件夹');
  const target = insideFolder || state.explorer;
  target.open = true;
  target.children.push(folder);
  render();
  scheduleSave();
  startRename(folder.id);
}

function renameEntry(id, title) {
  if (!guard()) return;
  const found = findEntry(state.explorer, id);
  if (!found) return;
  const clean = String(title || '').trim().slice(0, 200) || (found.entry.type === 'folder' ? '未命名文件夹' : '未命名文档');
  snapshot();
  found.entry.title = clean;
  if (found.entry.type === 'doc' && state.docs[id]) state.docs[id].title = clean;
  render();
  scheduleSave();
}

function startRename(id) {
  const row = sidebarEl.querySelector(`.entry[data-id="${CSS.escape(id)}"]`);
  if (!row) return;
  const titleEl = row.querySelector('.entry-title');
  const entry = findEntry(state.explorer, id)?.entry;
  if (!titleEl || !entry) return;
  const input = el('input', 'entry-rename');
  input.value = entry.title;
  input.maxLength = 200;
  titleEl.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const commit = (save) => {
    if (done) return;
    done = true;
    if (save) renameEntry(id, input.value);
    else renderExplorer();
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commit(true); }
    if (e.key === 'Escape') { e.preventDefault(); commit(false); }
  });
  input.addEventListener('blur', () => commit(true));
}

function openEntryMove(id) {
  const hitE = findEntry(state.explorer, id);
  if (!hitE) return;
  const list = $('#entrymove-list');
  list.textContent = '';
  const addTarget = (label, targetId, depth, disabled) => {
    const b = el('button', 'move-item' + (disabled ? ' disabled' : ''));
    b.type = 'button';
    b.disabled = !!disabled;
    b.append(el('span', 'path', depth ? '文件夹' : '根目录'), el('span', 'hit', label));
    if (!disabled) {
      b.addEventListener('click', () => {
        const moved = moveEntry(state.explorer, id, targetId);
        if (moved) { snapshot(); render(); scheduleSave(); }
        closeModals();
      });
    }
    list.append(b);
  };
  addTarget('全部（顶层）', 'root', 0, hitE.parent.id === 'root');
  for (const { entry, depth } of flattenEntries(state.explorer)) {
    if (entry.type !== 'folder') continue;
    const bad = entry.id === id || containsEntry(hitE.entry, entry.id);
    addTarget(entry.title, entry.id, depth + 1, bad);
  }
  openModal('entrymove');
}

function deleteEntry(id) {
  if (!guard()) return;
  const found = findEntry(state.explorer, id);
  if (!found) return;
  const name = found.entry.title;
  const docCount = found.entry.type === 'doc' ? 1 : countDocs(found.entry);
  confirmModal(`删除「${name}」？${docCount > 1 ? `其中的 ${docCount} 个文档会一起删除。` : ''}`, () => {
    snapshot();
    const removed = removeEntry(state.explorer, id);
    if (removed) removeDocsIn(removed);
    if (!state.docs[state.docId]) state.docId = firstDocId();
    render();
    scheduleSave();
  });
}

function removeDocsIn(entry) {
  if (entry.type === 'doc') delete state.docs[entry.id];
  else (entry.children || []).forEach(removeDocsIn);
}

// ------------------------------------------------------------------ 编辑

function startEdit(id, kind = 'text') {
  if (!guard()) return;
  const item = itemOf(id);
  if (!item) return;
  const h = hit(id);
  if (!h) return;
  if (state.editing && state.editing.id === id && state.editing.kind === kind) return;
  finishEdit(true);
  snapshot();

  let view = item.querySelector(kind === 'text' ? '.text-view' : '.note-view');
  let editor = item.querySelector(kind === 'text' ? '.text-editor' : '.note-editor');
  if (kind === 'note' && !editor) {
    const wrap = item.querySelector('.text-wrap');
    view = el('div', 'note-view');
    editor = el('div', 'note-editor');
    editor.contentEditable = CE;
    editor.spellcheck = false;
    wrap.append(view, editor);
  }
  if (!editor) return;

  if (view) view.hidden = true;
  editor.hidden = false;
  editor.textContent = kind === 'text' ? h.node.text : h.node.note;
  item.classList.add('editing');
  editor.focus();
  caretEnd(editor);
  state.editing = { id, kind };
  hideMobileBar();
  if (kind === 'text') showMobileBar();
}

function finishEdit(silent = false) {
  const ed = state.editing;
  if (!ed) return;
  state.editing = null;
  const item = itemOf(ed.id);
  const h = hit(ed.id);
  if (item && h) {
    const editor = item.querySelector(ed.kind === 'text' ? '.text-editor' : '.note-editor');
    const view = item.querySelector(ed.kind === 'text' ? '.text-view' : '.note-view');
    if (editor) {
      const value = editor.innerText.replace(/ /g, ' ').replace(/\n+$/, '');
      if (ed.kind === 'text') h.node.text = value; else h.node.note = value;
      editor.hidden = true;
      if (view) {
        view.hidden = false;
        view.textContent = '';
        view.append(renderInline(value));
        if (!value && ed.kind === 'text') view.append(el('span', 'placeholder', '写点什么…'));
      }
    }
    item.classList.remove('editing');
  }
  hideMobileBar();
  if (!silent) {
    renderExplorer();
    renderDocHead();
    renderStat();
    scheduleSave();
  }
}

function focusItem(id) {
  const item = itemOf(id);
  const target = item?.querySelector('.text-view');
  if (target) target.focus();
}

// ------------------------------------------------------------------ 键盘（条目）

function onEditorKeydown(e) {
  const ed = state.editing;
  if (!ed) return;
  const h = hit(ed.id);
  if (!h) return;
  const mod = e.metaKey || e.ctrlKey;

  if (ed.kind === 'note') {
    if (e.key === 'Escape' || (e.key === 'Enter' && mod)) { e.preventDefault(); finishEdit(); }
    return;
  }

  if (e.key === 'Enter' && !mod && !e.shiftKey) { e.preventDefault(); insertSibling(h); return; }
  if (e.key === 'Enter' && e.shiftKey && !mod) { e.preventDefault(); finishEdit(); startEdit(ed.id, 'note'); return; }
  if (e.key === 'Tab' && !mod) { e.preventDefault(); if (e.shiftKey) outdent(h); else indent(h); return; }
  if (e.key === 'Enter' && mod) { e.preventDefault(); snapshot(); toggleDone(h.node); refresh(h.node.id); scheduleSave(); return; }
  if (e.key === 'Backspace' && !h.node.text && !mod) { e.preventDefault(); removeNode(h); return; }
  if (mod && (e.key === ']' || e.key === '[')) {
    e.preventDefault();
    snapshot();
    finishEdit();
    if (e.key === ']') zoomInto(ed.id); else zoomOut();
    return;
  }
  if (e.key === 'Escape') { e.preventDefault(); finishEdit(); focusItem(ed.id); }
}

function onViewKeydown(e) {
  const focused = e.target.closest('.item');
  if (!focused) return;
  const id = focused.dataset.id;
  const h = hit(id);
  if (!h) return;
  const mod = e.metaKey || e.ctrlKey;

  if (e.key === 'Enter' && !mod && !e.shiftKey) { e.preventDefault(); insertSibling(h); return; }
  if (e.key === 'Enter' && e.shiftKey && !mod) { e.preventDefault(); startEdit(id, 'note'); return; }
  if (e.key === 'Tab') { e.preventDefault(); if (e.shiftKey) outdent(h); else indent(h); return; }
  if (e.key === 'Backspace') { e.preventDefault(); removeNode(h); return; }
  if (e.key === ' ' || e.key === 'F2') { e.preventDefault(); startEdit(id); return; }
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    e.preventDefault();
    const dir = e.key === 'ArrowUp' ? -1 : 1;
    const ids = visibleIds(docTree(), state.zoom, state.settings.showDone);
    const i = ids.indexOf(id);
    const next = ids[i + dir];
    if (next) focusItem(next);
    return;
  }
  if (e.key.length === 1 && !mod && !e.altKey) {
    e.preventDefault();
    startEdit(id);
    document.execCommand('insertText', false, e.key);
  }
}

// ------------------------------------------------------------------ 结构操作

function insertSibling(h) {
  if (!guard()) return;
  const { node, parent, index } = h;
  snapshot();
  const fresh = newNode();
  parent.children.splice(index + 1, 0, fresh);
  render();
  startEdit(fresh.id);
  scheduleSave();
}

function indent(h) {
  if (!guard()) return;
  const { node, parent, index } = h;
  if (index <= 0) return;
  snapshot();
  const prev = parent.children[index - 1];
  parent.children.splice(index, 1);
  prev.open = true;
  prev.children.push(node);
  render();
  startEdit(node.id);
  scheduleSave();
}

function outdent(h) {
  if (!guard()) return;
  const { node, parent } = h;
  const grand = find(docTree(), parent.id);
  if (!grand || !grand.parent) return;
  snapshot();
  const idx = grand.parent.children.indexOf(grand.node);
  grand.parent.children.splice(idx + 1, 0, node);
  parent.children.splice(parent.children.indexOf(node), 1);
  render();
  startEdit(node.id);
  scheduleSave();
}

function removeNode(h) {
  if (!guard()) return;
  const { node, parent } = h;
  const idx = parent.children.indexOf(node);
  if (idx < 0) return;
  snapshot();
  const before = visibleIds(docTree(), state.zoom, state.settings.showDone);
  const pos = before.indexOf(node.id);
  parent.children.splice(idx, 1, ...node.children);
  const prev = before[Math.max(0, pos - 1)];
  render();
  if (prev && hit(prev)) focusItem(prev);
  scheduleSave();
}

function removeItem(id) {
  if (!guard()) return;
  const h = hit(id);
  if (!h) return;
  snapshot();
  h.parent.children.splice(h.index, 1);
  render();
  scheduleSave();
  closeModals();
}

function toggleDone(node) { node.done = !node.done; }

function duplicateItem(id) {
  if (!guard()) return;
  const h = hit(id);
  if (!h) return;
  snapshot();
  h.parent.children.splice(h.index + 1, 0, cloneWithNewIds(h.node));
  render();
  scheduleSave();
  toast('已复制条目');
}

function refresh(id) {
  const item = itemOf(id);
  const h = hit(id);
  if (!item || !h) return;
  item.classList.toggle('done', !!h.node.done);
  const check = item.querySelector('.check');
  if (check) check.checked = !!h.node.done;
  if (!state.editing) {
    const view = item.querySelector('.text-view');
    if (view) {
      view.textContent = '';
      view.append(renderInline(h.node.text));
      if (!h.node.text) view.append(el('span', 'placeholder', '写点什么…'));
    }
  }
  renderStat();
  renderDocHead();
  renderExplorer();
}

function moveTo(id, targetId, position) {
  if (!guard()) return;
  snapshot();
  if (moveNode(docTree(), id, targetId, position)) {
    render();
    scheduleSave();
  }
}

function toggleNumbered(id) {
  if (!guard()) return;
  const h = hit(id);
  if (!h) return;
  snapshot();
  h.node.numbered = !h.node.numbered;
  render();
  scheduleSave();
}

function setHeading(id, level) {
  if (!guard()) return;
  const h = hit(id);
  if (!h) return;
  snapshot();
  h.node.heading = level;
  render();
  scheduleSave();
}

function setColor(id, color) {
  if (!guard()) return;
  const h = hit(id);
  if (!h) return;
  snapshot();
  h.node.color = color;
  render();
  scheduleSave();
}

function setDue(id, due) {
  if (!guard()) return;
  const h = hit(id);
  if (!h) return;
  snapshot();
  h.node.due = due || null;
  render();
  scheduleSave();
}

function expandAll(open) {
  if (!guard()) return;
  snapshot();
  flatten(docTree()).forEach(({ node }) => { node.open = open; });
  render();
  scheduleSave();
}

function copyLink(id) {
  const url = `${location.origin}/s/${SPACE}/#d=${state.docId}&z=${id}`;
  navigator.clipboard?.writeText(url).then(() => toast('链接已复制'), () => toast('复制失败'));
}

// ------------------------------------------------------------------ 视图导航

function zoomInto(id) {
  const path = pathOf(docTree(), id);
  if (!path) return;
  state.zoom = path;
  render();
  window.scrollTo({ top: 0 });
}

function zoomOut() {
  state.zoom = state.zoom.slice(0, -1);
  render();
}

function goHome() {
  state.zoom = [];
  render();
  window.scrollTo({ top: 0 });
}

// ------------------------------------------------------------------ 列表事件

listEl.addEventListener('mousedown', (e) => {
  const editingItem = state.editing && itemOf(state.editing.id);
  if (state.editing && editingItem && !editingItem.contains(e.target)) finishEdit();
});

listEl.addEventListener('click', (e) => {
  const item = e.target.closest('.item');
  if (!item) return;
  const id = item.dataset.id;

  const tag = e.target.closest('.tag');
  if (tag) { e.preventDefault(); openSearch('#' + tag.dataset.tag); return; }

  const action = e.target.closest('[data-action]')?.dataset.action;
  if (action === 'toggle-open') {
    const h = hit(id);
    if (!h) return;
    h.node.open = !h.node.open;
    item.classList.toggle('collapsed', !h.node.open);
    scheduleSave();
    return;
  }
  if (action === 'zoom') { zoomInto(id); return; }
  if (action === 'menu') { e.stopPropagation(); openItemMenu(e.target.closest('.more'), id); return; }
  if (action === 'due') { openDateModal(id); return; }

  if (e.target.closest('.text-view')) {
    e.preventDefault();
    startEdit(id);
  }
});

listEl.addEventListener('dblclick', (e) => {
  const handle = e.target.closest('.handle');
  const item = e.target.closest('.item');
  if (!handle || !item) return;
  zoomInto(item.dataset.id);
});

listEl.addEventListener('change', (e) => {
  if (!e.target.classList.contains('check')) return;
  if (!guard()) { e.target.checked = !e.target.checked; return; }
  const item = e.target.closest('.item');
  const h = hit(item.dataset.id);
  if (!h) return;
  snapshot();
  h.node.done = e.target.checked;
  render();
  scheduleSave();
});

listEl.addEventListener('keydown', (e) => {
  if (e.target.classList.contains('text-editor') || e.target.classList.contains('note-editor')) {
    return onEditorKeydown(e);
  }
  if (e.target.classList.contains('text-view')) return onViewKeydown(e);
});

listEl.addEventListener('input', (e) => {
  const editor = e.target.closest('.text-editor, .note-editor');
  if (!editor || !state.editing) return;
  const h = hit(state.editing.id);
  if (!h) return;
  const value = editor.innerText.replace(/ /g, ' ');
  if (state.editing.kind === 'text') h.node.text = value; else h.node.note = value;
  scheduleSave();
});

listEl.addEventListener('focusout', (e) => {
  if (!e.target.classList.contains('text-editor') && !e.target.classList.contains('note-editor')) return;
  if (state.editing) finishEdit();
});

listEl.addEventListener('paste', (e) => {
  const editor = e.target.closest('.text-editor, .note-editor');
  if (!editor) return;
  e.preventDefault();
  const raw = (e.clipboardData || window.clipboardData).getData('text/plain') || '';
  const clean = editor.classList.contains('text-editor') ? raw.replace(/\s*\n+\s*/g, ' ') : raw;
  document.execCommand('insertText', false, clean);
});

// ------------------------------------------------------------------ 文档内拖拽

let dragId = null;
let dropHint = null;

listEl.addEventListener('dragstart', (e) => {
  const handle = e.target.closest('.handle');
  if (!handle) return;
  const item = handle.closest('.item');
  dragId = item.dataset.id;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', dragId);
  setTimeout(() => item.classList.add('dragging'), 0);
});

listEl.addEventListener('dragend', () => {
  clearDrop();
  dragId = null;
  $$('.item.dragging').forEach((n) => n.classList.remove('dragging'));
});

listEl.addEventListener('dragover', (e) => {
  if (!dragId) return;
  const item = e.target.closest('.item');
  if (!item || item.dataset.id === dragId) return;
  e.preventDefault();
  const rect = item.getBoundingClientRect();
  const y = (e.clientY - rect.top) / rect.height;
  const position = y < 0.28 ? 'before' : y > 0.72 ? 'after' : 'child';
  if (dropHint && dropHint.id === item.dataset.id && dropHint.position === position) return;
  clearDrop();
  item.classList.add('drop-' + position);
  dropHint = { id: item.dataset.id, position };
});

listEl.addEventListener('drop', (e) => {
  if (!dragId) return;
  e.preventDefault();
  const hint = dropHint;
  const id = dragId;
  clearDrop();
  dragId = null;
  if (hint) moveTo(id, hint.id, hint.position);
});

function clearDrop() {
  $$('.item.drop-before, .item.drop-after, .item.drop-child').forEach((n) =>
    n.classList.remove('drop-before', 'drop-after', 'drop-child'));
  dropHint = null;
}

// ------------------------------------------------------------------ 侧栏事件

let entryDragId = null;

sidebarEl.addEventListener('click', (e) => {
  const actionEl = e.target.closest('[data-action]');
  const row = e.target.closest('.entry');
  const action = actionEl?.dataset.action;

  if (action === 'new-menu') {
    e.stopPropagation();
    openMenu(actionEl, [
      { label: '新建文档', hint: `${MOD}⇧N`, action: () => createDoc() },
      { label: '新建文件夹', action: () => createFolder() },
    ]);
    return;
  }
  if (action === 'new-doc') { e.stopPropagation(); createDoc(); return; }
  if (action === 'new-folder') { e.stopPropagation(); createFolder(); return; }

  if (!row) return;
  const id = row.dataset.id;
  const entry = findEntry(state.explorer, id)?.entry;
  if (!entry) return;

  if (action === 'toggle-folder') {
    entry.open = !entry.open;
    renderExplorer();
    scheduleSave();
    return;
  }
  if (action === 'entry-menu') {
    e.stopPropagation();
    openEntryMenu(e.target.closest('.entry-more'), id, entry);
    return;
  }
  if (entry.type === 'doc') { openDoc(id); return; }
  // 点文件夹整行 = 折叠/展开
  entry.open = !entry.open;
  renderExplorer();
  scheduleSave();
});

sidebarEl.addEventListener('dblclick', (e) => {
  const row = e.target.closest('.entry');
  if (!row) return;
  startRename(row.dataset.id);
});

sidebarEl.addEventListener('dragstart', (e) => {
  const row = e.target.closest('.entry');
  if (!row) return;
  entryDragId = row.dataset.id;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', entryDragId);
  setTimeout(() => row.classList.add('dragging'), 0);
});

sidebarEl.addEventListener('dragend', () => {
  sidebarEl.querySelectorAll('.entry.dragging, .entry.drop-target').forEach((n) =>
    n.classList.remove('dragging', 'drop-target'));
  entryDragId = null;
});

sidebarEl.addEventListener('dragover', (e) => {
  if (!entryDragId) return;
  const row = e.target.closest('.entry');
  const targetFolder = row && row.dataset.type === 'folder' ? row : null;
  if (!row && !e.target.closest('.explorer')) return;
  if (row && row.dataset.id === entryDragId) return;
  e.preventDefault();
  sidebarEl.querySelectorAll('.entry.drop-target').forEach((n) => n.classList.remove('drop-target'));
  if (targetFolder) targetFolder.classList.add('drop-target');
});

sidebarEl.addEventListener('drop', (e) => {
  if (!entryDragId) return;
  e.preventDefault();
  const row = e.target.closest('.entry');
  const targetId = row && row.dataset.type === 'folder' ? row.dataset.id : 'root';
  const moved = moveEntry(state.explorer, entryDragId, targetId);
  sidebarEl.querySelectorAll('.entry.dragging, .entry.drop-target').forEach((n) =>
    n.classList.remove('dragging', 'drop-target'));
  entryDragId = null;
  if (moved) { snapshot(); render(); scheduleSave(); }
});

// ------------------------------------------------------------------ 顶栏 / 文档头

$('#btn-menu').addEventListener('click', () => sidebarEl.classList.toggle('open'));
$('#btn-search').addEventListener('click', () => openSearch(''));
$('#btn-help').addEventListener('click', () => openModal('help'));
$('#btn-settings').addEventListener('click', openSettings);
$('#btn-logout').addEventListener('click', async () => {
  await fetch('/api/logout', { method: 'POST' });
  location.reload();
});

docTitleEl.addEventListener('input', () => {
  const doc = currentDoc();
  if (!doc || readonly()) return;
  const title = docTitleEl.textContent.replace(/\n+/g, ' ').slice(0, 200);
  doc.title = title || '未命名文档';
  const entry = findEntry(state.explorer, doc.id)?.entry;
  if (entry) entry.title = doc.title;
  renderExplorer();
  scheduleSave();
});
docTitleEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); docTitleEl.blur(); }
  if (e.key === 'Escape') {
    e.preventDefault();
    const doc = currentDoc();
    docTitleEl.textContent = doc?.title || '';
    docTitleEl.blur();
  }
});
docTitleEl.addEventListener('blur', () => {
  const doc = currentDoc();
  if (!doc) return;
  const title = docTitleEl.textContent.replace(/\n+/g, ' ').trim().slice(0, 200) || '未命名文档';
  doc.title = title;
  const entry = findEntry(state.explorer, doc.id)?.entry;
  if (entry) entry.title = title;
  docTitleEl.textContent = title;
  renderExplorer();
  scheduleSave();
});

$('#add-root').addEventListener('click', () => {
  if (!guard()) return;
  if (!docTree()) return createDoc();
  const current = currentNode() || docTree();
  const fresh = newNode();
  current.children.push(fresh);
  render();
  startEdit(fresh.id);
  scheduleSave();
});

$('#brand').addEventListener('click', (e) => { e.preventDefault(); goHome(); });

// ------------------------------------------------------------------ 弹层基础

function openModal(id) {
  $$('.overlay').forEach((o) => { if (o.id !== id) o.hidden = true; });
  closeMenu();
  const m = document.getElementById(id);
  if (m) m.hidden = false;
}
function closeModals() {
  $$('.overlay').forEach((o) => { if (o.id !== 'login') o.hidden = true; });
  closeMenu();
  confirmAction = null;
}
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('overlay')) closeModals();
});
$$('.modal-close').forEach((b) => b.addEventListener('click', closeModals));

// 确认框
let confirmAction = null;
function confirmModal(message, action) {
  $$('.overlay').forEach((o) => { o.hidden = true; });
  closeMenu();
  $('#confirm-text').textContent = message;
  confirmAction = action;
  $('#confirm').hidden = false;
}
$('#confirm-ok').addEventListener('click', () => {
  const fn = confirmAction;
  confirmAction = null;
  $('#confirm').hidden = true;
  if (fn) fn();
});
$('#confirm-cancel').addEventListener('click', () => {
  confirmAction = null;
  $('#confirm').hidden = true;
});

// ------------------------------------------------------------------ 搜索（跨文档）

const searchInput = $('#search-input');
const searchResults = $('#search-results');

function openSearch(initial = '') {
  openModal('search');
  searchInput.value = initial;
  renderSearch(initial);
  searchInput.focus();
  searchInput.select();
}
function closeSearch() { $('#search').hidden = true; }

function parseQuery(q) {
  const ops = {};
  const rest = [];
  for (const part of q.split(/\s+/)) {
    if (!part) continue;
    if (part.startsWith('#')) ops.tag = part.slice(1);
    else if (part === 'is:done') ops.done = true;
    else if (part === 'is:undone') ops.done = false;
    else if (part === 'has:due') ops.hasDue = true;
    else if (part === 'due:today') ops.due = 'today';
    else if (part === 'due:overdue') ops.due = 'overdue';
    else rest.push(part);
  }
  return { text: rest.join(' ').toLowerCase(), ...ops };
}

function renderSearch(q) {
  const { text, tag, done, hasDue, due } = parseQuery(q || '');
  searchResults.textContent = '';
  if (!q) {
    searchResults.append(el('div', 'search-empty', '跨所有文档。支持 #tag、is:done、is:undone、has:due、due:today、due:overdue'));
    return;
  }
  const hits = [];
  for (const doc of Object.values(state.docs)) {
    flatten(doc.tree).forEach(({ node, names }) => {
      if (text && !(node.text + ' ' + node.note).toLowerCase().includes(text)) return;
      if (tag && !tagsIn(node.text).includes(tag)) return;
      if (done != null && !!node.done !== done) return;
      if (hasDue && !node.due) return;
      if (due === 'today' && node.due !== todayStr()) return;
      if (due === 'overdue' && !(node.due && node.due < todayStr())) return;
      hits.push({ doc, node, names });
    });
  }
  if (!hits.length) { searchResults.append(el('div', 'search-empty', '没有匹配的条目')); return; }
  for (const h of hits.slice(0, 100)) {
    const btn = el('button', 'search-item');
    btn.type = 'button';
    const where = [plain(h.doc.title) || '未命名文档', ...h.names.slice(0, -1).map(plain)].join(' / ');
    btn.append(el('span', 'path', where));
    const line = el('span', 'hit');
    line.append(renderInline(h.node.text));
    btn.append(line);
    btn.addEventListener('click', () => {
      closeSearch();
      openDoc(h.doc.id);
      zoomInto(h.node.id);
    });
    searchResults.append(btn);
  }
}

searchInput.addEventListener('input', () => renderSearch(searchInput.value));
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeSearch();
  if (e.key === 'Enter') searchResults.querySelector('.search-item')?.click();
});

// ------------------------------------------------------------------ 帮助

const HELP_ROWS = [
  ['基础', [
    ['新建文档', `${MOD}⇧N`], ['新建同级', 'Enter'], ['缩进 / 提升', 'Tab / ⇧Tab'],
    ['折叠 / 展开', '点圆点'], ['zoom 进入 / 退回', `${MOD}] / ${MOD}[`],
    ['完成 / 取消', `${MOD} Enter`], ['写备注', '⇧Enter'],
    ['删除空条目', 'Backspace'], ['撤销 / 重做', `${MOD}Z / ${MOD}⇧Z`],
  ]],
  ['导航', [
    ['上下移动', '↑ / ↓'], ['进入编辑', 'Space'], ['展开全部', `${MOD}⇧,`],
    ['收起全部', `${MOD}⇧.`], ['搜索（跨文档）', `${MOD}F`], ['侧栏', `${MOD}⇧F`],
  ]],
  ['条目', [
    ['设日期', `${MOD}⇧D`], ['设为今天', `${MOD}⇧T`], ['子项编号', `${MOD}⇧X`],
    ['标题 1/2/3', `${MOD}⇧1/2/3`], ['颜色标签', `${MOD}⌥1…6`],
    ['复制链接', `${MOD}⇧L`], ['移动…', `${MOD}⇧M`], ['复制条目', `${MOD}⇧D`],
  ]],
  ['文档', [
    ['重命名文档', '双击左侧文档 / 点标题'], ['重命名文件夹', '双击左侧文件夹'],
    ['移动文档/文件夹', '拖到目标文件夹'], ['删除文档/文件夹', '左侧 ⋯ 菜单'],
    ['快速收集', `${MOD}⇧I`], ['设置', `${MOD},`], ['帮助', `${MOD}/`],
    ['删除已完成', `${MOD}⇧⌫`], ['导出', '设置 → 导出'],
  ]],
];

function buildHelp() {
  const host = $('#help-body');
  host.textContent = '';
  for (const [section, rows] of HELP_ROWS) {
    host.append(el('h3', '', section));
    const table = el('div', 'keys');
    for (const [name, key] of rows) {
      const r = el('div', 'key-row');
      r.append(el('span', 'key-name', name), el('kbd', '', key));
      table.append(r);
    }
    host.append(table);
  }
}
buildHelp();

// ------------------------------------------------------------------ 设置

let shareMode = 'off';

async function loadShare() {
  const box = $('#share-box');
  if (!box) return;
  box.hidden = readonly();
  if (readonly()) return;
  try {
    const r = await fetch(api('/api/share'), { cache: 'no-store' });
    if (!r.ok) return;
    const d = await r.json();
    shareMode = d.mode;
    $('#share-url').value = d.url || '';
    $('#share-toggle').textContent = d.mode === 'view' ? '关闭分享' : '生成只读链接';
  } catch { /* 忽略 */ }
}

$('#share-toggle').addEventListener('click', async () => {
  const enable = shareMode !== 'view';
  const r = await fetch(api('/api/share'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: enable ? 'view' : 'off' }),
  });
  if (!r.ok) { toast('操作失败'); return; }
  const d = await r.json();
  shareMode = d.mode;
  $('#share-url').value = d.url || '';
  $('#share-toggle').textContent = d.mode === 'view' ? '关闭分享' : '生成只读链接';
  toast(d.mode === 'view' ? '只读链接已生成' : '分享已关闭');
});

$('#share-copy').addEventListener('click', () => {
  const v = $('#share-url').value;
  if (!v) return toast('还没有生成链接');
  navigator.clipboard?.writeText(v).then(() => toast('已复制'), () => toast('复制失败'));
});

$('#pwd-save').addEventListener('click', async () => {
  const current = $('#pwd-current').value;
  const next = $('#pwd-next').value;
  if (next.length < 6) return toast('新密码至少 6 位');
  const r = await fetch(api('/api/password'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current, next }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) return toast(d.error || '修改失败');
  $('#pwd-current').value = '';
  $('#pwd-next').value = '';
  toast('密码已更新');
});

function openSettings() {
  const s = state.settings;
  loadShare();
  $('#set-theme').value = s.theme;
  $('#set-density').value = s.density;
  $('#set-fontsize').value = String(s.fontSize);
  $('#set-narrow').checked = s.narrow;
  $('#set-notes').checked = s.showNotes;
  $('#set-done').checked = s.showDone;
  openModal('settings');
}

function bindSetting(id, apply) {
  const input = document.getElementById(id);
  input.addEventListener('change', () => {
    apply(input);
    applySettings();
    render();
    if (!readonly()) scheduleSave();
  });
}
bindSetting('set-theme', (i) => { state.settings.theme = i.value; });
bindSetting('set-density', (i) => { state.settings.density = i.value; });
bindSetting('set-fontsize', (i) => { state.settings.fontSize = Number(i.value); });
bindSetting('set-narrow', (i) => { state.settings.narrow = i.checked; });
bindSetting('set-notes', (i) => { state.settings.showNotes = i.checked; });
bindSetting('set-done', (i) => { state.settings.showDone = i.checked; });

$('#set-export-md').addEventListener('click', exportMarkdown);
$('#set-export-json').addEventListener('click', exportJSON);

function download(name, text, type = 'text/plain') {
  const blob = new Blob([text], { type });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function exportMarkdown() {
  const lines = [];
  for (const doc of Object.values(state.docs)) {
    lines.push(`# ${doc.title}`, '');
    (function walk(node, depth) {
      for (const c of node.children) {
        const indent = '  '.repeat(depth);
        let line = `${indent}- ${c.done ? '[x]' : '[ ]'} ${c.text}`;
        if (c.due) line += ` 📅 ${c.due}`;
        lines.push(line);
        if (c.note) for (const n of c.note.split('\n')) lines.push(`${indent}  ${n}`);
        walk(c, depth + 1);
      }
    })(doc.tree, 0);
    lines.push('');
  }
  download('todo.md', lines.join('\n'), 'text/markdown');
  toast('已导出 Markdown');
}

function exportJSON() {
  download('todo.json', JSON.stringify({ explorer: state.explorer, docs: state.docs, settings: state.settings }, null, 2), 'application/json');
  toast('已导出 JSON');
}

// ------------------------------------------------------------------ 菜单

let menuEl = null;

function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }

function openMenu(anchor, items) {
  closeMenu();
  const menu = el('div', 'menu');
  for (const it of items) {
    if (it === '-') { menu.append(el('div', 'menu-sep')); continue; }
    const b = el('button', 'menu-item' + (it.danger ? ' danger' : ''));
    b.type = 'button';
    b.append(el('span', 'mi-label', it.label));
    if (it.hint) b.append(el('kbd', '', it.hint));
    b.addEventListener('click', (e) => { e.stopPropagation(); closeMenu(); it.action(); });
    menu.append(b);
  }
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  const mw = menu.offsetWidth;
  const mh = menu.offsetHeight;
  const left = Math.min(r.left, window.innerWidth - mw - 12);
  let top = r.bottom + 6;
  if (top + mh > window.innerHeight - 12) top = Math.max(12, r.top - mh - 6);
  menu.style.left = Math.max(12, left) + 'px';
  menu.style.top = top + 'px';
  menuEl = menu;
}

document.addEventListener('click', (e) => {
  if (menuEl && !menuEl.contains(e.target)) closeMenu();
});

function openEntryMenu(anchor, id, entry) {
  const items = [];
  if (entry.type === 'folder') {
    items.push(
      { label: '新建文档', action: () => createDoc(entry) },
      { label: '新建子文件夹', action: () => createFolder(entry) },
      '-',
      { label: '重命名', action: () => startRename(id) },
      { label: '移动到文件夹…', action: () => openEntryMove(id) },
      { label: '删除文件夹', danger: true, action: () => deleteEntry(id) },
    );
  } else {
    items.push(
      { label: '打开', action: () => openDoc(id) },
      { label: '重命名', action: () => startRename(id) },
      { label: '移动到文件夹…', action: () => openEntryMove(id) },
      '-',
      { label: '复制链接', action: () => {
        closeMenu();
        navigator.clipboard?.writeText(`${location.origin}/#d=${id}`)
          .then(() => toast('链接已复制'), () => toast('复制失败'));
      } },
      { label: '删除文档', danger: true, action: () => deleteEntry(id) },
    );
  }
  openMenu(anchor, items);
}

function openItemMenu(anchor, id) {
  const h = hit(id);
  if (!h) return;
  const n = h.node;
  openMenu(anchor, [
    { label: 'zoom 进入', hint: `${MOD}]`, action: () => zoomInto(id) },
    { label: n.note ? '编辑备注' : '添加备注', hint: '⇧Enter', action: () => startEdit(id, 'note') },
    { label: '设日期 / 清除', hint: `${MOD}⇧D`, action: () => openDateModal(id) },
    '-',
    { label: n.numbered ? '取消子项编号' : '子项编号', hint: `${MOD}⇧X`, action: () => toggleNumbered(id) },
    { label: '标题 1 / 2 / 3', hint: `${MOD}⇧1/2/3`, action: () => openHeadingMenu(anchor, id) },
    { label: '颜色', action: () => openColorMenu(anchor, id) },
    { label: '排序子项', action: () => openSortMenu(anchor, id) },
    '-',
    { label: '复制条目', hint: `${MOD}⇧D`, action: () => duplicateItem(id) },
    { label: '复制链接', hint: `${MOD}⇧L`, action: () => copyLink(id) },
    { label: '移动…', hint: `${MOD}⇧M`, action: () => openMoveModal(id) },
    '-',
    { label: '删除条目', danger: true, action: () => removeItem(id) },
  ]);
}

function openHeadingMenu(anchor, id) {
  openMenu(anchor, [1, 2, 3, 0].map((lv) => ({
    label: lv ? `标题 ${lv}` : '清除标题',
    action: () => setHeading(id, lv),
  })));
}

function openColorMenu(anchor, id) {
  const names = { red: '红', orange: '橙', yellow: '黄', green: '绿', blue: '蓝', purple: '紫' };
  openMenu(anchor, COLORS.map((c) => ({ label: names[c], action: () => setColor(id, c) }))
    .concat([{ label: '清除颜色', action: () => setColor(id, null) }]));
}

function openSortMenu(anchor, id) {
  const modes = [
    ['title-asc', '标题 A→Z'], ['title-desc', '标题 Z→A'],
    ['due-asc', '日期 早→晚'], ['due-desc', '日期 晚→早'],
    ['done-last', '未完成在前'], ['done-first', '已完成在前'],
  ];
  openMenu(anchor, modes.map(([mode, label]) => ({
    label,
    action: () => {
      const h = hit(id);
      if (!h) return;
      snapshot();
      sortChildren(h.node, mode);
      render();
      scheduleSave();
    },
  })));
}

// ------------------------------------------------------------------ 日期

let dateTarget = null;
function openDateModal(id) {
  dateTarget = id;
  const h = hit(id);
  $('#date-input').value = h?.node.due || '';
  openModal('date');
  setTimeout(() => $('#date-input').focus(), 30);
}

$('#date-input').addEventListener('change', () => {
  if (dateTarget) setDue(dateTarget, $('#date-input').value);
  closeModals();
});
$('#date-today').addEventListener('click', () => { if (dateTarget) setDue(dateTarget, todayStr()); closeModals(); });
$('#date-tomorrow').addEventListener('click', () => { if (dateTarget) setDue(dateTarget, todayStr(1)); closeModals(); });
$('#date-nextweek').addEventListener('click', () => { if (dateTarget) setDue(dateTarget, todayStr(7)); closeModals(); });
$('#date-clear').addEventListener('click', () => { if (dateTarget) setDue(dateTarget, null); closeModals(); });

// ------------------------------------------------------------------ 移动条目

let moveTarget = null;
function openMoveModal(id) {
  moveTarget = id;
  $('#move-input').value = '';
  renderMoveList('');
  openModal('move');
  setTimeout(() => $('#move-input').focus(), 30);
}

function renderMoveList(q) {
  const host = $('#move-list');
  host.textContent = '';
  const src = moveTarget ? hit(moveTarget)?.node : null;
  const rows = flatten(docTree()).filter(({ node }) =>
    (!src || !contains(src, node.id)) &&
    (node.text || '').toLowerCase().includes((q || '').toLowerCase()));
  if (!q) {
    const root = el('button', 'move-item');
    root.type = 'button';
    root.append(el('span', 'path', '顶层'), el('span', 'hit', '全部（移到根目录）'));
    root.addEventListener('click', () => { if (moveTarget) moveTo(moveTarget, 'root', 'child'); closeModals(); });
    host.append(root);
  }
  for (const { node, names } of rows.slice(0, 100)) {
    const b = el('button', 'move-item');
    b.type = 'button';
    b.append(el('span', 'path', names.slice(0, -1).map(plain).join(' / ') || '根目录'));
    b.append(el('span', 'hit', node.text || '（未命名）'));
    b.addEventListener('click', () => {
      if (moveTarget) moveTo(moveTarget, node.id, 'child');
      closeModals();
    });
    host.append(b);
  }
  if (!rows.length && q) host.append(el('div', 'search-empty', '没有可移入的目标'));
}

$('#move-input').addEventListener('input', () => renderMoveList($('#move-input').value));

// ------------------------------------------------------------------ 快速收集

function openCapture() {
  if (!docTree()) { toast('先新建一个文档'); return; }
  $('#capture').hidden = false;
  const input = $('#capture-input');
  input.value = '';
  input.focus();
}
function closeCapture() { $('#capture').hidden = true; }

$('#capture-input').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeCapture();
  if (e.key === 'Enter') {
    const text = $('#capture-input').value.trim();
    if (!text) return closeCapture();
    if (!guard()) return;
    snapshot();
    (currentNode() || docTree()).children.push(newNode({ text }));
    closeCapture();
    render();
    scheduleSave();
    toast('已收集到当前文档');
  }
});

// ------------------------------------------------------------------ 移动端工具条

function showMobileBar() { $('#mobile-bar').hidden = false; }
function hideMobileBar() { $('#mobile-bar').hidden = true; }

$('#mobile-bar').addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]');
  if (!b || !state.editing) return;
  const id = state.editing.id;
  finishEdit();
  const fresh = hit(id);
  if (!fresh) return;
  switch (b.dataset.act) {
    case 'indent': indent(fresh); break;
    case 'outdent': outdent(fresh); break;
    case 'done': snapshot(); toggleDone(fresh.node); refresh(id); scheduleSave(); break;
    case 'date': openDateModal(id); break;
    case 'note': startEdit(id, 'note'); break;
    case 'delete': removeNode(fresh); break;
  }
});

// ------------------------------------------------------------------ 全局键盘

document.addEventListener('keydown', (e) => {
  const mod = e.metaKey || e.ctrlKey;
  const inEditor = e.target.closest?.('.text-editor, .note-editor');
  const inInput = e.target.matches?.('input, textarea, select') || e.target.isContentEditable;

  if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); finishEdit(); save(true); return; }
  if (mod && e.key === '/') { e.preventDefault(); openModal('help'); return; }
  if (mod && e.key === ',') { e.preventDefault(); openSettings(); return; }
  if (mod && e.key.toLowerCase() === 'f') { e.preventDefault(); openSearch(''); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'n') { e.preventDefault(); createDoc(); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'f') {
    e.preventDefault();
    sidebarEl.classList.toggle('open');
    return;
  }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'i') { e.preventDefault(); openCapture(); return; }
  if (mod && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); redo(); return; }
  if (e.key === 'Escape') { closeModals(); closeCapture(); return; }

  if (inEditor || inInput) return;

  const focused = document.activeElement?.closest?.('.item');
  const id = focused?.dataset.id;
  if (!id) return;
  const h = hit(id);
  if (!h) return;

  if (mod && e.shiftKey && e.key.toLowerCase() === 'd') { e.preventDefault(); openDateModal(id); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 't') { e.preventDefault(); setDue(id, todayStr()); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'x') { e.preventDefault(); toggleNumbered(id); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'l') { e.preventDefault(); copyLink(id); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'm') { e.preventDefault(); openMoveModal(id); return; }
  if (mod && e.shiftKey && ['1', '2', '3'].includes(e.key)) { e.preventDefault(); setHeading(id, Number(e.key)); return; }
  if (mod && e.shiftKey && e.key === 'Backspace') { e.preventDefault(); deleteChecked(); return; }
  if (mod && e.shiftKey && e.key === '.') { e.preventDefault(); expandAll(false); return; }
  if (mod && e.shiftKey && e.key === ',') { e.preventDefault(); expandAll(true); return; }
  if (mod && e.altKey && /^[1-6]$/.test(e.key)) {
    e.preventDefault();
    setColor(id, COLORS[Number(e.key) - 1]);
  }
});

function deleteChecked() {
  if (!guard()) return;
  snapshot();
  (function walker(node) {
    node.children = node.children.filter((c) => !c.done);
    node.children.forEach(walker);
  })(docTree());
  render();
  scheduleSave();
  toast('已删除完成项');
}

// ------------------------------------------------------------------ 冲突

function showConflict(server) {
  state.closed = true;
  setSave('有冲突', true);
  $('#conflict').hidden = false;
  window.__serverPending = server;
}

$('#conflict-local').addEventListener('click', async () => {
  const server = window.__serverPending || {};
  state.version = server.version ?? state.version;
  state.closed = false;
  $('#conflict').hidden = true;
  state.dirty = true;
  await save(true);
});
$('#conflict-server').addEventListener('click', () => {
  const server = window.__serverPending || {};
  if (server.docs) {
    state.explorer = server.explorer;
    state.docs = server.docs;
    state.settings = { ...DEFAULT_SETTINGS, ...(server.settings || {}) };
    state.version = server.version;
    state.dirty = false;
    state.closed = false;
    $('#conflict').hidden = true;
    if (!state.docs[state.docId]) state.docId = firstDocId();
    state.zoom = state.zoom.filter((id) => hit(id));
    render();
    setSave('已载入服务器版本');
  }
});

// ------------------------------------------------------------------ 登录 & 启动

const loginOverlay = $('#login');
const loginForm = $('#login-form');
const loginErr = $('#login-err');
const loginInput = $('#login-password');

function showLogin(name) {
  const label = $('#login-space');
  if (label) label.textContent = name ? `空间：${name}` : '';
  loginOverlay.hidden = false;
  loginInput.focus();
}

function applyRole() {
  const ro = readonly();
  document.body.classList.toggle('readonly', ro);
  docTitleEl.contentEditable = ro ? 'false' : 'plaintext-only';
  const bar = $('#viewer-bar');
  if (bar) bar.hidden = !ro;
}

loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  loginErr.textContent = '';
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ spaceId: SPACE, password: loginInput.value }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    loginErr.textContent = err.error || '密码不对，再试一次';
    loginInput.select();
    return;
  }
  const data = await res.json().catch(() => ({}));
  if (data.name) state.spaceName = data.name;
  loginOverlay.hidden = true;
  await loadState();
});

async function loadState() {
  const res = await fetch(api('/api/state'), { cache: 'no-store' });
  if (res.status === 401) return showLogin();
  const data = await res.json();
  state.role = data.role === 'viewer' ? 'viewer' : 'owner';
  applyRole();
  state.explorer = data.explorer;
  state.docs = data.docs;
  state.settings = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
  state.version = data.version;
  state.dirty = false;
  state.closed = false;

  const hash = location.hash.replace(/^#/, '');
  const params = new URLSearchParams(hash);
  const docParam = params.get('d');
  const nodeParam = params.get('z');
  if (docParam && state.docs[docParam]) state.docId = docParam;
  else state.docId = firstDocId();
  if (nodeParam && state.docs[state.docId] && find(state.docs[state.docId].tree, nodeParam)) {
    state.zoom = pathOf(state.docs[state.docId].tree, nodeParam);
  }

  render();
  setSave('已同步 ' + new Date().toTimeString().slice(0, 5));
}

(async function init() {
  try {
    if (!SPACE) { location.replace('/'); return; }
    const info = await fetch('/api/space?space=' + encodeURIComponent(SPACE), { cache: 'no-store' }).then((r) => r.json());
    if (!info || info.error) {
      document.body.innerHTML = '<p style="padding:40px;font-family:sans-serif">空间不存在</p>';
      return;
    }
    state.spaceName = info.name;
    const s = await fetch('/api/session?space=' + encodeURIComponent(SPACE), { cache: 'no-store' }).then((r) => r.json());
    if (!s.authed) return showLogin(info.name);
    await loadState();
  } catch {
    setSave('连接失败', true);
  }
})();
