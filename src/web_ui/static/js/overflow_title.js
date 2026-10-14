/** 잘린 글(…)에 마우스를 올리면 전체 글 · 수정 목록 99 (2026-10-12)
 *
 * 자리마다 title 을 다는 대신 화면 전체에 한 번 · 마우스가 올라간 칸(또는 그 위 몇 칸)이
 * 실제로 잘려 있을 때만(`text-overflow: ellipsis` 이고 글이 칸보다 넓음) 그 칸의 글을 title 로.
 * 코드가 일부러 단 title 은 덮지 않는다 · 스크롤되는 칸(표 감싸개 등)은 건드리지 않는다.
 * 선택 칸(select)·입력 칸은 보이는 값이 잘릴 수 있어 그 값을 단다.
 */

const MAX_DEPTH = 4;

/** 「…」 로 잘렸나 · 칸이 그려져 있고 글이 칸보다 넓다 */
export function isClipped(node, style = getComputedStyle(node)) {
  if (!node.clientWidth) return false;
  if (style.textOverflow !== 'ellipsis') return false;
  return node.scrollWidth > node.clientWidth + 1;
}

/** 붙일 글 · 공백 하나로 · 비면 '' */
export function overflowText(node) {
  if (node.tagName === 'SELECT') return [...(node.selectedOptions || [])].map((option) => option.textContent).join(', ').trim();
  if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') return String(node.value || '').trim();
  return String(node.textContent || '').replace(/\s+/g, ' ').trim();
}

function fieldClipped(node) {
  if (node.tagName === 'SELECT') return overflowText(node).length > 0 && node.scrollWidth >= node.clientWidth;
  if (node.tagName === 'INPUT') return node.scrollWidth > node.clientWidth + 1;
  return false;
}

function apply(node) {
  // 코드가 단 title 은 그대로 · 이 도우미가 단 것만 새 글로 바꾼다
  if (node.title && node.dataset.autoTitle !== 'true') return;
  const text = overflowText(node);
  if (!text) return;
  node.title = text;
  node.dataset.autoTitle = 'true';
}

export function installOverflowTitles(root = document) {
  root.addEventListener('mouseover', (event) => {
    let node = event.target;
    for (let depth = 0; node && depth < MAX_DEPTH; depth += 1, node = node.parentElement) {
      if (!(node instanceof HTMLElement)) continue;
      if (node.tagName === 'SELECT' || node.tagName === 'INPUT') {
        if (fieldClipped(node)) apply(node);
        return;
      }
      if (isClipped(node)) {
        apply(node);
        return;
      }
    }
  }, { passive: true });
}
