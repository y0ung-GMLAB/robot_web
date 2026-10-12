/** UI v2 · DOM 만들기 · 글은 늘 textContent (서버·파일 이름이 HTML 로 읽히지 않게) */

export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = String(value);
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** 안을 통째로 바꾼다 · 입력 중인 칸이 있으면 그대로 둔다(덮어써서 글이 날아가지 않게) */
export function replace(container, ...children) {
  if (!container) return;
  // 스위치·체크칸은 누른 뒤에도 초점이 남는다 · 그것까지 막으면 화면이 통째로 멈춘다 → 글 넣는 칸만
  if (container.contains(document.activeElement)
    && document.activeElement.matches('textarea, select, input:not([type=checkbox]):not([type=radio]):not([type=button])')) return;
  const scrolled = scrollPositions(container);
  // 펼쳐 둔 칸(details)도 다시 그리면 접혔다 · 제목 글로 같은 칸을 찾아 다시 펼친다 (원본 파일 보기 · 2026-10-12)
  const opened = new Set([...container.querySelectorAll('details[open] > summary')].map((s) => s.textContent));
  container.replaceChildren(...children.flat(Infinity).filter(Boolean));
  if (opened.size) {
    for (const summary of container.querySelectorAll('details > summary')) {
      if (opened.has(summary.textContent)) summary.parentElement.open = true;
    }
  }
  restoreScroll(container, scrolled);
}

/** 다시 그려도 표의 가로 스크롤 등이 맨 왼쪽으로 돌아가지 않게 · 칸 이름(aria-label)·클래스·순서로 같은 칸을 찾는다 */
function scrollKey(el, container) {
  const section = el.closest('[aria-label]');
  return `${section && container.contains(section) ? section.getAttribute('aria-label') : ''}|${el.tagName}.${el.className}`;
}

function scrollPositions(container) {
  const seen = new Map();
  const out = [];
  for (const el of container.querySelectorAll('*')) {
    if (el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight) continue;
    const key = scrollKey(el, container);
    const index = seen.get(key) || 0;
    seen.set(key, index + 1);
    if (el.scrollLeft || el.scrollTop) out.push({ key, index, left: el.scrollLeft, top: el.scrollTop });
  }
  return out;
}

function restoreScroll(container, saved) {
  if (!saved.length) return;
  const seen = new Map();
  const found = new Map();
  for (const el of container.querySelectorAll('*')) {
    if (el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight) continue;
    const key = scrollKey(el, container);
    const index = seen.get(key) || 0;
    seen.set(key, index + 1);
    found.set(`${key}#${index}`, el);
  }
  for (const item of saved) {
    const el = found.get(`${item.key}#${item.index}`);
    if (el) { el.scrollLeft = item.left; el.scrollTop = item.top; }
  }
}

export function dot(tone) {
  return h('span', { class: `dot dot-${tone}`, 'aria-hidden': 'true' });
}
