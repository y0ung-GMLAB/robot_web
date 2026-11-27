/** UI v2 · 설명 툴팁(ⓘ) · 기능 설명은 화면에 늘 띄우지 않고 여기로 (사용자 2026-11-09 · AGENTS.md 「UI 문구 규칙」)
 *
 * 마우스를 올리면 뜨고, 누르면 고정(터치 화면은 누르기만) · 바깥을 누르거나 Esc 로 닫힌다 · 스크롤하면 따라간다.
 * 풍선은 body 에 하나만 두고 겹쳐 띄운다 · 화면을 다시 그려도(morph) 안 닫히고 다른 칸을 밀지 않는다.
 * 글은 줄 배열 또는 문자열 · 줄마다 명사형 한 항목.
 */

import { h } from './dom.js';

/** ⓘ 버튼 · 설명할 말 바로 뒤에 둔다 */
export function tip(lines, label = '설명') {
  const text = (Array.isArray(lines) ? lines : [lines]).filter(Boolean).join('\n');
  if (!text) return null;
  return h('button', { type: 'button', class: 'tip', 'data-tip': text, 'aria-label': label }, 'i');
}

let bubble = null;
let anchor = null;
let pinned = false;

function ensureBubble() {
  if (bubble) return bubble;
  bubble = h('div', { class: 'tip-bubble', role: 'tooltip', hidden: true });
  document.body.append(bubble);
  return bubble;
}

function place() {
  const rect = anchor.getBoundingClientRect();
  const box = bubble.getBoundingClientRect();
  const gap = 8;
  let left = rect.left + rect.width / 2 - box.width / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - box.width - 8));
  // 아래 자리가 모자라면 위로
  let top = rect.bottom + gap;
  if (top + box.height > window.innerHeight - 8 && rect.top - gap - box.height > 8) top = rect.top - gap - box.height;
  bubble.style.left = `${Math.round(left)}px`;
  bubble.style.top = `${Math.round(top)}px`;
}

function show(button, pin) {
  ensureBubble();
  anchor = button;
  pinned = pin;
  bubble.textContent = button.dataset.tip || '';
  bubble.hidden = false;
  place();
  button.setAttribute('aria-describedby', 'tip-bubble');
  bubble.id = 'tip-bubble';
}

function hide() {
  if (!bubble || bubble.hidden) return;
  bubble.hidden = true;
  anchor?.removeAttribute('aria-describedby');
  anchor = null;
  pinned = false;
}

export function installTips(root = document) {
  root.addEventListener('pointerover', (event) => {
    if (event.pointerType !== 'mouse' || pinned) return;
    const button = event.target instanceof Element ? event.target.closest('.tip') : null;
    if (button) show(button, false);
  });
  root.addEventListener('pointerout', (event) => {
    if (event.pointerType !== 'mouse' || pinned || !anchor) return;
    if (event.target instanceof Element && event.target.closest('.tip') === anchor
      && !(event.relatedTarget instanceof Element && event.relatedTarget.closest('.tip') === anchor)) hide();
  });
  root.addEventListener('click', (event) => {
    const button = event.target instanceof Element ? event.target.closest('.tip') : null;
    if (!button) {
      if (pinned && !(event.target instanceof Element && event.target.closest('.tip-bubble'))) hide();
      return;
    }
    // 버튼 안(라벨·요약 줄)에 있어도 그 버튼은 누르지 않게
    event.preventDefault();
    event.stopPropagation();
    if (pinned && anchor === button) hide();
    else show(button, true);
  }, true);
  root.addEventListener('keydown', (event) => { if (event.key === 'Escape') hide(); });
  root.addEventListener('focusin', (event) => {
    if (pinned) return;
    const button = event.target instanceof Element ? event.target.closest('.tip') : null;
    if (button && button.matches(':focus-visible')) show(button, false);
  });
  root.addEventListener('focusout', (event) => {
    if (!pinned && event.target === anchor) hide();
  });
  // 스크롤 · 크기 변경 · 따라간다(표 감싸개 안 ⓘ 는 마우스를 올릴 때도 스크롤된다) · ⓘ 가 화면에서 빠지면 닫는다
  const follow = () => {
    if (!anchor || bubble.hidden) return;
    const rect = anchor.getBoundingClientRect();
    if (!anchor.isConnected || rect.bottom < 0 || rect.top > window.innerHeight) hide();
    else place();
  };
  window.addEventListener('scroll', follow, true);
  window.addEventListener('resize', follow);
}
