/** UI v2 · DOM 만들기 · 글은 늘 textContent (서버·파일 이름이 HTML 로 읽히지 않게) */

export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = String(value);
    else if (key === 'style' && typeof value === 'object') {
      // CSS 변수(--이름)는 setProperty 로만 들어간다 · Object.assign 은 조용히 버린다
      for (const [name, styleValue] of Object.entries(value)) {
        if (name.startsWith('--')) node.style.setProperty(name, String(styleValue));
        else node.style[name] = styleValue;
      }
    }
    else if (key.startsWith('on') && typeof value === 'function') listen(node, key.slice(2).toLowerCase(), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** 이벤트 · 노드마다 종류별 리스너 하나 · 실제 함수는 node.__on 표에서 찾는다(다시 그릴 때 표만 바꾼다) */
function listen(node, type, fn) {
  if (!node.__on) node.__on = {};
  if (!node.__on[type]) node.addEventListener(type, (event) => node.__on?.[type]?.(event));
  node.__on[type] = fn;
}

/**
 * 지금 화면(old)을 새로 만든 화면(fresh)과 같게 · 바뀐 곳만 고친다 (2026-10-12)
 * 전에는 0.5초마다 통째로 갈아 끼워 스크롤바가 깜빡이고 펼친 칸이 접히고 스크롤이 처음으로 돌아갔다.
 * 사람이 바꾸는 상태(details 의 open · 스크롤)는 건드리지 않는다.
 */
function morph(old, fresh) {
  if (old === fresh) return;
  if (old.nodeType !== fresh.nodeType || old.nodeName !== fresh.nodeName
    || (old.nodeType === 1 && old.getAttribute('type') !== fresh.getAttribute('type'))) {
    old.replaceWith(fresh);
    return;
  }
  if (old.nodeType === 3 || old.nodeType === 8) {
    if (old.nodeValue !== fresh.nodeValue) old.nodeValue = fresh.nodeValue;
    return;
  }
  if (old.nodeType !== 1) return;
  // 속성
  for (const { name } of [...old.attributes]) {
    if (name === 'open' && old.nodeName === 'DETAILS') continue;
    if (!fresh.hasAttribute(name)) old.removeAttribute(name);
  }
  for (const { name, value } of [...fresh.attributes]) {
    if (old.getAttribute(name) !== value) old.setAttribute(name, value);
  }
  // 값 · 체크 · 선택은 속성이 아니라 성질로 · 글 넣는 중인 칸은 그대로
  if (old.nodeName === 'INPUT' || old.nodeName === 'TEXTAREA') {
    if (old !== document.activeElement) {
      const value = fresh.getAttribute('value') ?? fresh.textContent ?? '';
      if (old.type === 'checkbox' || old.type === 'radio') old.checked = fresh.hasAttribute('checked');
      else if (old.value !== value) old.value = value;
    }
  } else if (old.nodeName === 'OPTION') {
    old.selected = fresh.hasAttribute('selected');
  }
  // 이벤트
  if (fresh.__on) {
    for (const [type, fn] of Object.entries(fresh.__on)) listen(old, type, fn);
  }
  if (old.__on) {
    for (const type of Object.keys(old.__on)) if (!fresh.__on?.[type]) old.__on[type] = null;
  }
  morphChildren(old, [...fresh.childNodes]);
}

/** 계속 같은 칸을 다시 쓰는 노드(3D 화면 · 사용법 본문) · 새 내용을 만들 때 지금 자리에서 빠져나와 있다 */
function isPersistent(node) {
  return node.nodeType === 1 && node.dataset?.persistent !== undefined;
}

function morphChildren(parent, freshChildren) {
  const oldChildren = [...parent.childNodes];
  let j = 0;
  for (const next of freshChildren) {
    const before = oldChildren[j];
    if (isPersistent(next)) {
      // 같은 노드면 그대로 · 아니면 이 자리에 넣는다(지금 자리 순서는 건드리지 않는다)
      if (before === next) j += 1;
      else parent.insertBefore(next, before || null);
      continue;
    }
    if (!before) { parent.append(next); continue; }
    morph(before, next);
    j += 1;
  }
  for (; j < oldChildren.length; j += 1) {
    if (oldChildren[j].parentNode === parent) oldChildren[j].remove();
  }
}

/** 안을 새 내용과 같게 · 바뀐 곳만 고친다 · 입력 중인 칸이 있으면 그대로 둔다(덮어써서 글이 날아가지 않게) */
export function replace(container, ...children) {
  if (!container) return;
  // 스위치·체크칸은 누른 뒤에도 초점이 남는다 · 그것까지 막으면 화면이 통째로 멈춘다 → 글 넣는 칸만
  // 페이더(range)도 놓은 뒤 초점이 남아 화면이 멈췄다(안내 문구가 안 바뀜 · 수정 목록 126) · 끄는 중은 pointerDown 이 막고 값은 morph 가 안 건드린다
  if (container.contains(document.activeElement)
    && document.activeElement.matches('textarea, select, input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=range])')) return;
  const fresh = children.flat(Infinity).filter(Boolean).map((child) => (child instanceof Node ? child : document.createTextNode(String(child))));
  morphChildren(container, fresh);
}

export function dot(tone) {
  return h('span', { class: `dot dot-${tone}`, 'aria-hidden': 'true' });
}
