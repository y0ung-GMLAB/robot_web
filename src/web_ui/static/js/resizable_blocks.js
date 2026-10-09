/** 블록 크기 · 아래 모서리를 끌어 위아래로 늘리고 줄이기 · 수정 목록 96 (2026-10-09 사용자)
 *
 * 「재생 목록이 위아래로 너무 좁다 · 드래그해서 넓히면 좋겠다 · 애니메이션 쪽 블록들」 ·
 * `data-resize-key` 가 붙은 칸은 CSS `resize: vertical` 로 오른쪽 아래 모서리를 끌 수 있다 ·
 * 끈 크기는 브라우저마다 기억한다(편의값 · 못 읽어도 기본 크기로 그대로 돈다) ·
 * 내용이 늘거나 줄어서 바뀐 크기는 적지 않는다 · 사람이 끈 것(인라인 height)만.
 */

const PREFIX = 'robot_web.size.';

function read(key) {
  try {
    return window.localStorage?.getItem(PREFIX + key) || '';
  } catch {
    return '';
  }
}

function write(key, value) {
  try {
    if (value) window.localStorage?.setItem(PREFIX + key, value);
    else window.localStorage?.removeItem(PREFIX + key);
  } catch {
    // 기억 못 해도 지금 화면에서는 된다
  }
}

/** 저장해 둔 높이가 쓸 만한가 · 40 ~ 3000 px 만 */
export function savedHeight(text) {
  const match = /^(\d+(?:\.\d+)?)px$/.exec(String(text || '').trim());
  if (!match) return '';
  const px = Number(match[1]);
  return px >= 40 && px <= 3000 ? `${Math.round(px)}px` : '';
}

export function initResizableBlocks(root = document) {
  const blocks = [...(root?.querySelectorAll?.('[data-resize-key]') || [])];
  const Observer = globalThis.ResizeObserver;
  for (const block of blocks) {
    const key = block.dataset.resizeKey;
    const saved = savedHeight(read(key));
    if (saved) block.style.height = saved;
    // 모서리를 두 번 누르면 기본 크기로 (기억도 지움)
    block.addEventListener('dblclick', (event) => {
      const rect = block.getBoundingClientRect();
      if (event.clientY < rect.bottom - 16 || event.clientX < rect.right - 16) return;
      block.style.height = '';
      write(key, '');
    });
    if (!Observer) continue;
    let timer = 0;
    new Observer(() => {
      if (!block.style.height) return;
      clearTimeout(timer);
      timer = setTimeout(() => write(key, savedHeight(block.style.height)), 300);
    }).observe(block);
  }
  return blocks.length;
}
