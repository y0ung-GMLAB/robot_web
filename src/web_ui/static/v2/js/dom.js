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
  container.replaceChildren(...children.flat(Infinity).filter(Boolean));
}

export function dot(tone) {
  return h('span', { class: `dot dot-${tone}`, 'aria-hidden': 'true' });
}
