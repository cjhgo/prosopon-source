/* 行内 Markdown 渲染：**粗** __斜__ ~~删~~ ==高亮== `码` [文](url) #标签。
 * 只用 DOM 构造，never innerHTML —— 文本永远当文本处理。 */

const TOKEN =
  /(\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|==[^=\n]+==|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)|https?:\/\/[^\s<>()]+|(^|[\s(（])#[^\s#，。；、（）()]+)/gu;

export function renderInline(text) {
  const frag = document.createDocumentFragment();
  const src = String(text || '');
  // 每次调用独立的正则实例：递归渲染时不能共用 lastIndex，否则外层 exec 会被重置成死循环
  const re = new RegExp(TOKEN.source, TOKEN.flags);
  let last = 0;
  let m;
  while ((m = re.exec(src))) {
    const raw = m[0];
    if (m.index > last) frag.append(document.createTextNode(src.slice(last, m.index)));
    last = m.index + raw.length;

    if (raw.startsWith('**') && raw.endsWith('**')) {
      frag.append(wrap('strong', inner(raw.slice(2, -2))));
    } else if (raw.startsWith('__') && raw.endsWith('__')) {
      frag.append(wrap('em', inner(raw.slice(2, -2))));
    } else if (raw.startsWith('~~') && raw.endsWith('~~')) {
      frag.append(wrap('s', inner(raw.slice(2, -2))));
    } else if (raw.startsWith('==') && raw.endsWith('==')) {
      frag.append(wrap('mark', inner(raw.slice(2, -2))));
    } else if (raw.startsWith('`') && raw.endsWith('`')) {
      frag.append(wrap('code', raw.slice(1, -1)));
    } else if (raw.startsWith('[')) {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(raw);
      const a = document.createElement('a');
      a.textContent = mm[1];
      a.href = mm[2];
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      frag.append(a);
    } else if (/^https?:/.test(raw)) {
      const a = document.createElement('a');
      a.textContent = raw;
      a.href = raw;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      frag.append(a);
    } else {
      const prefix = /^[\s(（]/.test(raw) ? raw[0] : '';
      const tag = raw.replace(/^[\s(（]#/, '');
      if (prefix) frag.append(document.createTextNode(prefix));
      const span = document.createElement('span');
      span.className = 'tag';
      span.dataset.tag = tag;
      span.textContent = '#' + tag;
      span.title = '按标签筛选';
      frag.append(span);
    }
  }
  if (last < src.length) frag.append(document.createTextNode(src.slice(last)));
  return frag;
}

function wrap(tag, content) {
  const el = document.createElement(tag);
  if (typeof content === 'string') el.textContent = content;
  else el.append(content);
  return el;
}

function inner(text) {
  return renderInline(text);
}
