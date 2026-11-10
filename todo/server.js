#!/usr/bin/env node
/**
 * todo.junhangc.cn — 多空间大纲式 todo 的后端。
 *
 * 三个概念（也是这个产品对「自用 + 分享」的回答）：
 *   space      一个独立空间：自己的 explorer/docs/settings，互不可见
 *   密码       空间身份：可读写，可改密码；给朋友 = 给同一空间的写权限
 *   分享 token 只读链接：免登录、可随时关闭/轮换，改密码不影响它
 *
 * 路由：
 *   /            落地页（介绍 + 创建入口）
 *   /me          跳转到 owner 空间
 *   /s/<id>      某个空间的 app
 *
 * 数据：
 *   data/spaces/index.json      {ownerId, spaces:{id:{name,salt,passHash,shareToken...}}}
 *   data/spaces/<id>.json       {version, updatedAt, explorer, docs, settings}
 *   data/history/               每次保存的快照
 *
 * 环境变量：
 *   PORT / DATA_DIR
 *   TODO_PASSWORD  仅用于**首次**迁移出 owner 空间；之后以空间内密码为准（可在 UI 改）
 *   TODO_INVITE    非空时，创建新空间必须填这个邀请码
 */

'use strict';

const http = require('http');
const fs = require('fs');
const fsp = fs.promises;
const path = require('path');
const crypto = require('crypto');

const PORT = Number(process.env.PORT || 3020);
const HOST = process.env.HOST || '0.0.0.0';
const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(__dirname, 'data'));
const PUBLIC_DIR = path.join(__dirname, 'public');
const SPACES_DIR = path.join(DATA_DIR, 'spaces');
const INDEX_FILE = path.join(SPACES_DIR, 'index.json');
const HISTORY_DIR = path.join(DATA_DIR, 'history');
const LEGACY_STORE = path.join(DATA_DIR, 'todo.json');
const MAX_BODY = 8 * 1024 * 1024;
const COOKIE = 'todo_session';
const SESSION_TTL = 365 * 24 * 3600;
const HISTORY_KEEP = 200;
const INVITE = process.env.TODO_INVITE || '';

fs.mkdirSync(SPACES_DIR, { recursive: true });
fs.mkdirSync(HISTORY_DIR, { recursive: true });

const SECRET = (() => {
  if (process.env.TODO_SECRET) return process.env.TODO_SECRET;
  const f = path.join(DATA_DIR, 'secret');
  if (fs.existsSync(f)) return fs.readFileSync(f, 'utf8').trim();
  const s = crypto.randomBytes(32).toString('hex');
  fs.writeFileSync(f, s, { mode: 0o600 });
  return s;
})();

// ---------------------------------------------------------------- 清洗（workspace）

const DEFAULT_SETTINGS = {
  theme: 'auto', density: 'cozy', fontSize: 15, narrow: false,
  showNotes: true, showDone: true,
};

const clean = (v, max = 2000) => String(v == null ? '' : v)
  .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
  .slice(0, max);

function emptyTree() {
  return { id: 'root', text: '', note: '', open: true, children: [] };
}

function sanitizeTree(input) {
  let count = 0;
  function walk(node, depth) {
    if (!node || typeof node !== 'object' || depth > 24) return null;
    if (++count > 8000) return null;
    const due = /^\d{4}-\d{2}-\d{2}$/.test(String(node.due || '')) ? String(node.due) : null;
    const color = ['red', 'orange', 'yellow', 'green', 'blue', 'purple'].includes(node.color) ? node.color : null;
    const heading = [0, 1, 2, 3].includes(Number(node.heading)) ? Number(node.heading) : 0;
    const out = {
      id: clean(node.id || crypto.randomUUID(), 64),
      text: clean(node.text),
      note: clean(node.note),
      done: !!node.done,
      open: node.open !== false,
      due,
      color,
      heading,
      numbered: !!node.numbered,
      children: [],
    };
    const kids = Array.isArray(node.children) ? node.children.slice(0, 500) : [];
    for (const k of kids) {
      const c = walk(k, depth + 1);
      if (c) out.children.push(c);
    }
    return out;
  }
  const tree = walk(input, 0) || emptyTree();
  tree.id = 'root';
  tree.text = '';
  return tree;
}

function sanitizeSettings(input) {
  const s = { ...DEFAULT_SETTINGS };
  if (input && typeof input === 'object') {
    if (['auto', 'light', 'dark'].includes(input.theme)) s.theme = input.theme;
    if (['cozy', 'compact'].includes(input.density)) s.density = input.density;
    if (Number(input.fontSize) >= 13 && Number(input.fontSize) <= 20) s.fontSize = Number(input.fontSize);
    s.narrow = !!input.narrow;
    s.showNotes = input.showNotes !== false;
    s.showDone = input.showDone !== false;
  }
  return s;
}

function sanitizeEntry(input, docs, depth = 0) {
  if (!input || typeof input !== 'object' || depth > 10) return null;
  const type = input.type === 'folder' ? 'folder' : 'doc';
  const id = clean(input.id, 64);
  if (!id) return null;
  if (type === 'doc') {
    if (!docs[id]) return null;
    docs[id].title = clean(docs[id].title, 200) || '未命名文档';
    return { id, type: 'doc', title: docs[id].title };
  }
  const out = {
    id,
    type: 'folder',
    title: clean(input.title, 200) || '未命名文件夹',
    open: input.open !== false,
    children: [],
  };
  for (const child of (Array.isArray(input.children) ? input.children.slice(0, 800) : [])) {
    const c = sanitizeEntry(child, docs, depth + 1);
    if (c) out.children.push(c);
  }
  return out;
}

function normalizeWorkspace(raw) {
  const now = new Date().toISOString();
  const docs = {};

  if (raw && raw.docs && typeof raw.docs === 'object') {
    for (const [id, d] of Object.entries(raw.docs)) {
      const docId = clean(id, 64);
      if (!docId) continue;
      docs[docId] = {
        id: docId,
        title: clean(d && d.title, 200) || '未命名文档',
        created: (d && d.created) || now,
        updated: (d && d.updated) || now,
        tree: sanitizeTree(d && d.tree),
      };
    }
  } else if (raw && raw.tree) {
    docs['d_default'] = {
      id: 'd_default',
      title: 'Todo',
      created: raw.updatedAt || now,
      updated: raw.updatedAt || now,
      tree: sanitizeTree(raw.tree),
    };
  }

  if (!Object.keys(docs).length) return seedWorkspace();

  let explorer;
  if (raw && raw.explorer) {
    explorer = { id: 'root', type: 'folder', title: '', open: true, children: [] };
    for (const child of (Array.isArray(raw.explorer.children) ? raw.explorer.children : [])) {
      const c = sanitizeEntry(child, docs);
      if (c) explorer.children.push(c);
    }
  } else {
    explorer = {
      id: 'root', type: 'folder', title: '', open: true,
      children: Object.values(docs).map((d) => ({ id: d.id, type: 'doc', title: d.title })),
    };
  }
  const placed = new Set();
  (function walk(entry) {
    if (entry.type === 'doc') placed.add(entry.id);
    (entry.children || []).forEach(walk);
  })(explorer);
  for (const d of Object.values(docs)) {
    if (!placed.has(d.id)) explorer.children.push({ id: d.id, type: 'doc', title: d.title });
  }

  return {
    version: Number(raw && raw.version) || 1,
    updatedAt: (raw && raw.updatedAt) || now,
    settings: sanitizeSettings(raw && raw.settings),
    explorer,
    docs,
  };
}

function seedTree() {
  const n = (id, text, children = [], extra = {}) => ({
    id, text, note: '', done: false, open: true, due: null, color: null,
    heading: 0, numbered: false, children, ...extra,
  });
  return {
    id: 'root', text: '', note: '', open: true,
    children: [
      n('n_welcome', '欢迎使用 todo.junhangc.cn', [
        n('n_w1', '左侧 My files 管理多个文档 / 文件夹；点 ＋ 新建'),
        n('n_w2', 'Enter 新建同级，Tab 缩进，⇧Tab 提升'),
        n('n_w3', '点圆点折叠；悬停放大镜或双击 zoom 进去'),
        n('n_w4', '⌘/Ctrl + Enter 勾选完成；Shift+Enter 写备注'),
        n('n_w5', '输入「井号 + 词」自动归为标签；⌘/Ctrl + Shift + D 设日期'),
        n('n_w6', '⌘/Ctrl + / 看全部快捷键；⌘/Ctrl + , 打开设置'),
      ]),
      n('n_try', '试一条新的任务', [], { due: new Date().toISOString().slice(0, 10) }),
    ],
  };
}

function seedWorkspace() {
  const now = new Date().toISOString();
  const mk = (id, title, tree) => ({ id, title, created: now, updated: now, tree });
  const docs = {
    d_todo: mk('d_todo', 'Todo', seedTree()),
    d_week: mk('d_week', '周计划', emptyTree()),
    d_life: mk('d_life', '杂事', emptyTree()),
  };
  const explorer = {
    id: 'root', type: 'folder', title: '', open: true,
    children: [
      { id: 'd_todo', type: 'doc', title: 'Todo' },
      {
        id: 'f_work', type: 'folder', title: '工作', open: true,
        children: [{ id: 'd_week', type: 'doc', title: '周计划' }],
      },
      {
        id: 'f_life', type: 'folder', title: '生活', open: true,
        children: [{ id: 'd_life', type: 'doc', title: '杂事' }],
      },
    ],
  };
  return { version: 1, updatedAt: now, settings: { ...DEFAULT_SETTINGS }, explorer, docs };
}

// ---------------------------------------------------------------- 空间

function hashPassword(password, salt) {
  return crypto.scryptSync(String(password), salt, 64).toString('hex');
}

function makeSpace({ id, name, password }) {
  const salt = crypto.randomBytes(16).toString('hex');
  return {
    id,
    name: clean(name, 60) || '我的空间',
    salt,
    passHash: hashPassword(password, salt),
    createdAt: new Date().toISOString(),
    shareMode: 'off',
    shareToken: null,
    sessionVersion: 0,
  };
}

function verifyPassword(space, password) {
  const got = Buffer.from(hashPassword(password, space.salt), 'hex');
  const want = Buffer.from(space.passHash, 'hex');
  return got.length === want.length && crypto.timingSafeEqual(got, want);
}

let index = null;

function loadIndex() {
  try {
    const raw = JSON.parse(fs.readFileSync(INDEX_FILE, 'utf8'));
    if (raw && raw.spaces && raw.ownerId) return raw;
    throw new Error('bad index');
  } catch (err) {
    if (err.code !== 'ENOENT') console.error('✗ 空间索引损坏，重建：', err.message);
    return migrateLegacy();
  }
}

/** 第一次跑：把旧单用户数据变成 owner 空间；密码取 TODO_PASSWORD */
function migrateLegacy() {
  const now = new Date().toISOString();
  let workspace = null;
  try {
    if (fs.existsSync(LEGACY_STORE)) {
      workspace = normalizeWorkspace(JSON.parse(fs.readFileSync(LEGACY_STORE, 'utf8')));
    }
  } catch (err) {
    console.error('旧数据迁移失败，使用种子：', err.message);
  }
  if (!workspace) workspace = seedWorkspace();

  const password = process.env.TODO_PASSWORD || crypto.randomBytes(9).toString('base64url');
  const owner = makeSpace({ id: 'me', name: '我的待办', password });
  const idx = { schema: 3, ownerId: owner.id, spaces: { [owner.id]: owner } };
  fs.writeFileSync(INDEX_FILE, JSON.stringify(idx, null, 2), { mode: 0o600 });
  fs.writeFileSync(path.join(SPACES_DIR, owner.id + '.json'), JSON.stringify(workspace), { mode: 0o600 });
  console.log(`✓ 已迁移出 owner 空间 /s/${owner.id}` + (process.env.TODO_PASSWORD ? '（密码来自 TODO_PASSWORD）' : `（随机密码：${password}）`));
  return idx;
}

function saveIndex() {
  const tmp = INDEX_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(index, null, 2), { mode: 0o600 });
  fs.renameSync(tmp, INDEX_FILE);
}

const workspaceCache = new Map();

function workspacePath(id) { return path.join(SPACES_DIR, id + '.json'); }

function getWorkspace(id) {
  if (workspaceCache.has(id)) return workspaceCache.get(id);
  let ws;
  try {
    ws = normalizeWorkspace(JSON.parse(fs.readFileSync(workspacePath(id), 'utf8')));
  } catch {
    ws = seedWorkspace();
  }
  workspaceCache.set(id, ws);
  return ws;
}

let writeChain = Promise.resolve();
function saveWorkspace(id, ws) {
  writeChain = writeChain.then(async () => {
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const payload = JSON.stringify(ws);
    try {
      await fsp.writeFile(path.join(HISTORY_DIR, `${id}-${ts}.json`), payload);
      const files = (await fsp.readdir(HISTORY_DIR)).filter((f) => f.endsWith('.json')).sort();
      for (const f of files.slice(0, Math.max(0, files.length - HISTORY_KEEP))) {
        await fsp.unlink(path.join(HISTORY_DIR, f));
      }
    } catch (e) {
      console.error('历史快照写入失败：', e.message);
    }
    const tmp = workspacePath(id) + '.tmp';
    await fsp.writeFile(tmp, payload, { mode: 0o600 });
    await fsp.rename(tmp, workspacePath(id));
  });
  return writeChain;
}

// ---------------------------------------------------------------- 会话

function sign(payload) {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const mac = crypto.createHmac('sha256', SECRET).update(body).digest('base64url');
  return `${body}.${mac}`;
}

function verify(token) {
  if (!token || typeof token !== 'string') return null;
  const [body, mac] = token.split('.');
  if (!body || !mac) return null;
  const want = crypto.createHmac('sha256', SECRET).update(body).digest('base64url');
  const a = Buffer.from(mac);
  const b = Buffer.from(want);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    if (!payload || payload.e < Date.now() / 1000) return null;
    return payload;
  } catch {
    return null;
  }
}

function parseCookies(header) {
  const out = {};
  for (const part of String(header || '').split(';')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

function sessionOf(req) {
  return verify(parseCookies(req.headers.cookie)[COOKIE]);
}

/** 返回当前请求对某空间的权限：owner / viewer / null */
function roleFor(req, spaceId) {
  const sess = sessionOf(req);
  if (!sess || sess.s !== spaceId) return null;
  const space = index.spaces[spaceId];
  if (!space) return null;
  if ((sess.v || 0) !== (space.sessionVersion || 0)) return null;
  return sess.r === 'viewer' ? 'viewer' : 'owner';
}

function cookieHeader(value, maxAge) {
  return `${COOKIE}=${value}; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=${maxAge}`;
}

function issueSession(res, spaceId, role) {
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL;
  const token = sign({ s: spaceId, r: role, e: exp, v: index.spaces[spaceId]?.sessionVersion || 0 });
  res.setHeader('Set-Cookie', cookieHeader(token, SESSION_TTL));
}

// ---------------------------------------------------------------- 限流

const buckets = new Map();
function rateOk(key, limit, windowMs) {
  const now = Date.now();
  const b = buckets.get(key);
  if (!b || b.reset < now) {
    buckets.set(key, { count: 1, reset: now + windowMs });
    return true;
  }
  b.count += 1;
  return b.count <= limit;
}
function clientIp(req) {
  const xff = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim();
  return xff || req.socket.remoteAddress || 'unknown';
}

// ---------------------------------------------------------------- HTTP 工具

function json(res, code, data, extraHeaders = {}) {
  const body = JSON.stringify(data);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    ...extraHeaders,
  });
  res.end(body);
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

async function serveFile(res, file, noCache) {
  try {
    const stat = await fsp.stat(file);
    if (!stat.isFile()) return false;
    const ext = path.extname(file).toLowerCase();
    res.writeHead(200, {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': noCache ? 'no-cache' : 'public, max-age=86400',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Content-Security-Policy':
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
    });
    fs.createReadStream(file).pipe(res);
    return true;
  } catch {
    return false;
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(Object.assign(new Error('body too large'), { status: 413 }));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf8');
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(Object.assign(new Error('invalid json'), { status: 400 }));
      }
    });
    req.on('error', reject);
  });
}

function newSpaceId() {
  let id;
  do { id = crypto.randomBytes(6).toString('base64url'); } while (index.spaces[id] || id === 'me');
  return id;
}

// ---------------------------------------------------------------- 路由

async function handle(req, res) {
  const url = new URL(req.url, 'http://localhost');
  const p = url.pathname;

  // ---- 落地页 / 空间 app / /me
  if (p === '/') return void (await serveFile(res, path.join(PUBLIC_DIR, 'landing.html'), true));
  if (p === '/me') {
    res.writeHead(302, { Location: `/s/${index.ownerId}` });
    return res.end();
  }
  const spaceMatch = /^\/s\/([A-Za-z0-9_-]+)\/?$/.exec(p);
  if (spaceMatch) {
    const spaceId = spaceMatch[1];
    if (!index.spaces[spaceId]) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('空间不存在');
    }
    // 只读分享链接：/s/<id>?share=<token>
    const share = url.searchParams.get('share');
    if (share) {
      const space = index.spaces[spaceId];
      if (space.shareMode === 'view' && space.shareToken === share) {
        // 已经以 owner 登录的浏览器打开只读链接，不要把自己的会话降级
        const existing = sessionOf(req);
        const keepOwner = existing && existing.s === spaceId && existing.r !== 'viewer';
        if (!keepOwner) issueSession(res, spaceId, 'viewer');
        res.writeHead(302, { Location: `/s/${spaceId}` });
        return res.end();
      }
      res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('分享链接无效或已关闭');
    }
    return void (await serveFile(res, path.join(PUBLIC_DIR, 'index.html'), true));
  }

  if (p === '/api/health') return json(res, 200, { ok: true });

  // ---- 会话
  if (p === '/api/session') {
    const spaceId = url.searchParams.get('space') || '';
    const role = roleFor(req, spaceId);
    return json(res, 200, {
      authed: !!role,
      role,
      spaceId: role ? spaceId : null,
      name: role ? index.spaces[spaceId].name : null,
    });
  }

  if (p === '/api/space') {
    const spaceId = url.searchParams.get('space') || '';
    const space = index.spaces[spaceId];
    if (!space) return json(res, 404, { error: 'not found' });
    const role = roleFor(req, spaceId);
    return json(res, 200, { id: space.id, name: space.name, authed: !!role, role });
  }

  if (p === '/api/login' && req.method === 'POST') {
    if (!rateOk('login:' + clientIp(req), 30, 60_000)) return json(res, 429, { error: '太频繁，稍后再试' });
    const body = await readBody(req);
    const space = index.spaces[String(body.spaceId || '')];
    if (!space || !verifyPassword(space, body.password)) {
      await new Promise((r) => setTimeout(r, 400));
      return json(res, 401, { error: '空间或密码不对' });
    }
    issueSession(res, space.id, 'owner');
    return json(res, 200, { ok: true, spaceId: space.id, name: space.name });
  }

  if (p === '/api/logout' && req.method === 'POST') {
    res.setHeader('Set-Cookie', cookieHeader('', 0));
    return json(res, 200, { ok: true });
  }

  // ---- 创建空间
  if (p === '/api/spaces' && req.method === 'POST') {
    if (!rateOk('create:' + clientIp(req), 5, 3600_000)) return json(res, 429, { error: '创建太频繁，稍后再试' });
    const body = await readBody(req);
    if (INVITE && String(body.invite || '') !== INVITE) return json(res, 403, { error: '邀请码不对' });
    const password = String(body.password || '');
    if (password.length < 6) return json(res, 400, { error: '密码至少 6 位' });
    const id = newSpaceId();
    const space = makeSpace({ id, name: body.name || '我的空间', password });
    index.spaces[id] = space;
    saveIndex();
    const ws = seedWorkspace();
    workspaceCache.set(id, ws);
    await saveWorkspace(id, ws);
    issueSession(res, id, 'owner');
    return json(res, 200, { ok: true, spaceId: id, name: space.name });
  }

  // ---- 以下是空间内 API
  if (p.startsWith('/api/')) {
    const spaceId = url.searchParams.get('space') || String(req.headers['x-space'] || '') || null;
    const role = spaceId ? roleFor(req, spaceId) : null;
    if (!role) return json(res, 401, { error: 'unauthorized' });

    if (p === '/api/state' && req.method === 'GET') {
      const ws = getWorkspace(spaceId);
      return json(res, 200, {
        version: ws.version,
        updatedAt: ws.updatedAt,
        explorer: ws.explorer,
        docs: ws.docs,
        settings: ws.settings,
        role,
      });
    }

    if (p === '/api/state' && req.method === 'PUT') {
      if (role !== 'owner') return json(res, 403, { error: '只读分享，不能修改' });
      const body = await readBody(req);
      if (!body.docs || !body.explorer) return json(res, 400, { error: 'docs and explorer required' });
      const ws = getWorkspace(spaceId);
      if (Number(body.version) !== ws.version) {
        return json(res, 409, {
          error: 'conflict',
          version: ws.version,
          updatedAt: ws.updatedAt,
          explorer: ws.explorer,
          docs: ws.docs,
          settings: ws.settings,
        });
      }
      const next = normalizeWorkspace({
        version: ws.version + 1,
        updatedAt: new Date().toISOString(),
        explorer: body.explorer,
        docs: body.docs,
        settings: body.settings,
      });
      next.version = ws.version + 1;
      workspaceCache.set(spaceId, next);
      await saveWorkspace(spaceId, next);
      return json(res, 200, { version: next.version, updatedAt: next.updatedAt });
    }

    // 分享管理（仅 owner）
    if (p === '/api/share' && req.method === 'GET') {
      if (role !== 'owner') return json(res, 403, { error: 'forbidden' });
      const space = index.spaces[spaceId];
      return json(res, 200, {
        mode: space.shareMode || 'off',
        token: space.shareMode === 'view' ? space.shareToken : null,
        url: space.shareMode === 'view' ? `https://${req.headers.host}/s/${spaceId}?share=${space.shareToken}` : null,
      });
    }

    if (p === '/api/share' && req.method === 'POST') {
      if (role !== 'owner') return json(res, 403, { error: 'forbidden' });
      const body = await readBody(req);
      const space = index.spaces[spaceId];
      if (body.mode === 'view') {
        space.shareMode = 'view';
        space.shareToken = crypto.randomBytes(16).toString('base64url');
      } else {
        space.shareMode = 'off';
        space.shareToken = null;
      }
      saveIndex();
      return json(res, 200, {
        mode: space.shareMode,
        token: space.shareToken,
        url: space.shareToken ? `https://${req.headers.host}/s/${spaceId}?share=${space.shareToken}` : null,
      });
    }

    if (p === '/api/password' && req.method === 'POST') {
      if (role !== 'owner') return json(res, 403, { error: 'forbidden' });
      const body = await readBody(req);
      const space = index.spaces[spaceId];
      if (!verifyPassword(space, body.current)) return json(res, 401, { error: '当前密码不对' });
      const next = String(body.next || '');
      if (next.length < 6) return json(res, 400, { error: '新密码至少 6 位' });
      space.salt = crypto.randomBytes(16).toString('hex');
      space.passHash = hashPassword(next, space.salt);
      space.sessionVersion = (space.sessionVersion || 0) + 1;
      saveIndex();
      // 让其它设备的会话失效（当前设备重新签发）
      issueSession(res, spaceId, 'owner');
      return json(res, 200, { ok: true });
    }

    return json(res, 404, { error: 'not found' });
  }

  // ---- 静态资源
  if (req.method === 'GET' || req.method === 'HEAD') {
    const rel = p.replace(/^\/+/, '');
    if (!rel.includes('..') && !rel.startsWith('.')) {
      const file = path.join(PUBLIC_DIR, rel);
      if (file.startsWith(PUBLIC_DIR)) {
        const ext = path.extname(file).toLowerCase();
        const noCache = ['.html', '.js', '.css', '.webmanifest'].includes(ext);
        if (await serveFile(res, file, noCache)) return;
      }
    }
  }

  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('404');
}

index = loadIndex();

const server = http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    const status = err.status || 500;
    if (status === 413 || status === 400) return json(res, status, { error: err.message });
    console.error('请求处理异常：', err);
    json(res, 500, { error: 'internal error' });
  });
});

server.listen(PORT, HOST, () => {
  console.log(`todo listening on ${HOST}:${PORT} · owner=/s/${index.ownerId} · spaces=${Object.keys(index.spaces).length}`);
});
