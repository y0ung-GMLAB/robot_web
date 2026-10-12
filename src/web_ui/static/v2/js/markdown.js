/** UI v2 · 문서(.md) → 화면 · HTML 글자를 만들지 않고 노드를 바로 만든다 (설계안 2026-10-09 · 사용법)
 *
 * 문서는 저장소 안 것이지만 그래도 글은 늘 textContent · 링크는 http(s) · # · 같은 문서 안만.
 * 쓰는 것만 받는다 · 제목 # ~ #### · 문단 · 목록(- * 1.) 들여쓰기 · 표 · ``` 코드 · > 인용 · --- · 그림.
 *
 * parseMarkdown(text) → 블록 배열 (시험용) · renderMarkdown(text, { imageBase }) → 노드 배열
 */
import { h } from './dom.js';

/** 제목 → 앵커 id · 한글 그대로 · 공백은 - */
export function slug(text) {
  return String(text).trim().toLowerCase()
    .replace(/[`*_~[\]()]/g, '')
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .replace(/\s+/g, '-');
}

const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function splitRow(line) {
  let body = line.trim();
  if (body.startsWith('|')) body = body.slice(1);
  if (body.endsWith('|') && !body.endsWith('\\|')) body = body.slice(0, -1);
  const cells = [];
  let cell = '';
  let code = false;
  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (ch === '`') code = !code;
    if (ch === '\\' && body[i + 1] === '|') { cell += '|'; i += 1; continue; }
    if (ch === '|' && !code) { cells.push(cell.trim()); cell = ''; continue; }
    cell += ch;
  }
  cells.push(cell.trim());
  return cells;
}

const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

/** 블록 나누기 · [{type, ...}] */
export function parseMarkdown(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const fence = /^\s*(```|~~~)\s*(\S*)/.exec(line);
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) { body.push(lines[i]); i += 1; }
      i += 1;
      blocks.push({ type: 'code', lang: fence[2], text: body.join('\n') });
      continue;
    }
    const heading = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] });
      i += 1;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { blocks.push({ type: 'hr' }); i += 1; continue; }
    if (line.includes('|') && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1])) {
      const head = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { rows.push(splitRow(lines[i])); i += 1; }
      blocks.push({ type: 'table', head, rows });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { body.push(lines[i].replace(/^\s*>\s?/, '')); i += 1; }
      blocks.push({ type: 'quote', blocks: parseMarkdown(body.join('\n')) });
      continue;
    }
    if (LIST_ITEM.test(line)) {
      const items = [];
      while (i < lines.length) {
        const match = LIST_ITEM.exec(lines[i]);
        if (match) {
          items.push({ indent: match[1].replace(/\t/g, '    ').length, ordered: /\d/.test(match[2]), text: match[3] });
          i += 1;
        } else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) {
          items[items.length - 1].text += ` ${lines[i].trim()}`;
          i += 1;
        } else {
          break;
        }
      }
      blocks.push({ type: 'list', tree: nestItems(items) });
      continue;
    }
    const body = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*```|\s*~~~|\s*>)/.test(lines[i]) && !LIST_ITEM.test(lines[i])
      && !(lines[i].includes('|') && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1]))) {
      body.push(lines[i].trim());
      i += 1;
    }
    blocks.push({ type: 'paragraph', text: body.join(' ') });
  }
  return blocks;
}

/** 들여쓰기로 목록 나무 · [{ordered, items:[{text, children:[...]}]}] */
function nestItems(items) {
  const root = { children: [], indent: -1 };
  const stack = [root];
  for (const item of items) {
    while (stack.length > 1 && item.indent <= stack[stack.length - 1].indent) stack.pop();
    const node = { text: item.text, ordered: item.ordered, indent: item.indent, children: [] };
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  }
  return root.children;
}

/* ---------- 글줄 안 ---------- */

const INLINE = /(`+)([\s\S]*?)\1|!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*\s][^*]*)\*|<(https?:\/\/[^>\s]+)>/g;

/** 안전한 링크만 · 바깥은 새 탭 */
export function safeHref(href) {
  const text = String(href || '').trim();
  if (/^https?:\/\//i.test(text)) return { href: text, external: true };
  if (text.startsWith('#')) return { href: `#doc-${slug(decodeURIComponent(text.slice(1)))}`, external: false, anchor: true };
  return null;
}

export function inline(text, options = {}) {
  const out = [];
  let last = 0;
  const source = String(text || '');
  for (const match of source.matchAll(INLINE)) {
    if (match.index > last) out.push(source.slice(last, match.index));
    if (match[1]) out.push(h('code', { text: match[2].trim() }));
    else if (match[4] !== undefined) {
      const src = match[4].replace(/^\.?\/?(docs\/)?images\//, '');
      out.push(options.imageBase && !/^[a-z]+:/i.test(src)
        ? h('img', { src: `${options.imageBase}${encodeURI(src)}`, alt: match[3], loading: 'lazy' })
        : h('span', { class: 'muted', text: `[그림 · ${match[3]}]` }));
    } else if (match[5] !== undefined) {
      const link = safeHref(match[6]);
      out.push(link
        ? h('a', { href: link.href, ...(link.external ? { target: '_blank', rel: 'noopener' } : {}), 'data-anchor': link.anchor ? 'true' : null }, inline(match[5], options))
        : h('span', {}, inline(match[5], options)));
    } else if (match[7] !== undefined || match[8] !== undefined) out.push(h('strong', {}, inline(match[7] ?? match[8], options)));
    else if (match[9] !== undefined) out.push(h('em', {}, inline(match[9], options)));
    else if (match[10]) out.push(h('a', { href: match[10], target: '_blank', rel: 'noopener', text: match[10] }));
    last = match.index + match[0].length;
  }
  if (last < source.length) out.push(source.slice(last));
  return out;
}

function listNode(nodes, options) {
  const ordered = nodes[0]?.ordered;
  return h(ordered ? 'ol' : 'ul', {}, nodes.map((node) => h('li', {}, inline(node.text, options),
    node.children.length ? listNode(node.children, options) : null)));
}

function blockNode(block, options) {
  switch (block.type) {
    case 'heading': {
      const tag = `h${Math.min(block.level + 1, 6)}`;
      return h(tag, { id: `doc-${slug(block.text)}`, class: `doc-h doc-h${block.level}` }, inline(block.text, options));
    }
    case 'code': return h('pre', { class: 'doc-code' }, h('code', { text: block.text }));
    case 'hr': return h('hr', {});
    case 'quote': return h('blockquote', {}, block.blocks.map((inner) => blockNode(inner, options)));
    case 'list': return listNode(block.tree, options);
    case 'table': return h('div', { class: 'table-wrap' }, h('table', { class: 'table doc-table' },
      h('thead', {}, h('tr', {}, block.head.map((cell) => h('th', { scope: 'col' }, inline(cell, options))))),
      h('tbody', {}, block.rows.map((row) => h('tr', {}, block.head.map((_, index) => h('td', {}, inline(row[index] || '', options))))))));
    default: return h('p', {}, inline(block.text, options));
  }
}

export function renderMarkdown(text, options = {}) {
  return parseMarkdown(text).map((block) => blockNode(block, options));
}

/** 차례 · ## · ### 만 (# 은 문서 제목 하나) */
export function outline(text) {
  return parseMarkdown(text).filter((block) => block.type === 'heading' && (block.level === 2 || block.level === 3))
    .map((block) => ({ level: block.level, text: block.text.replace(/[`*_]/g, ''), id: `doc-${slug(block.text)}` }));
}

/** 찾기 · 그 말이 든 절의 제목 · [{id, text, count}] */
export function searchSections(text, query) {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return [];
  const out = [];
  let current = { id: '', text: '처음', count: 0 };
  for (const block of parseMarkdown(text)) {
    if (block.type === 'heading' && block.level <= 3) {
      if (current.count) out.push(current);
      current = { id: `doc-${slug(block.text)}`, text: block.text.replace(/[`*_]/g, ''), count: 0 };
    }
    const body = JSON.stringify(block).toLowerCase();
    let at = body.indexOf(needle);
    while (at !== -1) { current.count += 1; at = body.indexOf(needle, at + needle.length); }
  }
  if (current.count) out.push(current);
  return out;
}
