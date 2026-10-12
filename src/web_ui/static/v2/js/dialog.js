/** UI v2 · 확인 창 · 알림 한 줄 (브라우저 기본 confirm 대신 · 화면과 같은 모양) */
import { h } from './dom.js';

/** 확인 · true/false · tone = primary | warning | danger */
export function confirmBox({ title, body, confirmLabel = '확인', cancelLabel = '취소', tone = 'primary' }) {
  return new Promise((resolve) => {
    const dialog = h('dialog', { class: 'confirm' },
      h('h2', { text: title }),
      h('p', { class: 'confirm-body', text: body }),
      h('div', { class: 'confirm-actions' },
        h('button', { class: 'btn', value: 'cancel', type: 'button', onclick: () => dialog.close('cancel') }, cancelLabel),
        h('button', { class: `btn btn-${tone}`, value: 'ok', type: 'button', onclick: () => dialog.close('ok') }, confirmLabel)));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(dialog.returnValue === 'ok'); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

/**
 * 글자를 쳐서 확인 · 지우기처럼 되돌릴 수 없는 일 · must 와 같아야 확인 버튼이 켜진다
 * 또는 이름 받기(must 없음) · 돌려주는 값 = 친 글자 | null(취소)
 */
export function promptBox({ title, body = '', label = '', must = '', value = '', confirmLabel = '확인', tone = 'primary' }) {
  return new Promise((resolve) => {
    const input = h('input', { class: 'input', type: 'text', value, 'aria-label': label || title, autocomplete: 'off' });
    const ok = h('button', { class: `btn btn-${tone}`, type: 'button', onclick: () => dialog.close('ok') }, confirmLabel);
    const sync = () => { ok.disabled = must ? input.value.trim() !== must : !input.value.trim(); };
    input.addEventListener('input', sync);
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !ok.disabled) dialog.close('ok'); });
    const dialog = h('dialog', { class: 'confirm' },
      h('h2', { text: title }),
      body ? h('p', { class: 'confirm-body', text: body }) : null,
      label ? h('p', { class: 'muted small', text: label }) : null,
      input,
      h('div', { class: 'confirm-actions' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.close('cancel') }, '취소'),
        ok));
    sync();
    dialog.addEventListener('close', () => { dialog.remove(); resolve(dialog.returnValue === 'ok' ? input.value.trim() : null); });
    document.body.append(dialog);
    dialog.showModal();
    input.focus();
  });
}

let toastTimer = null;

/** 화면 아래 한 줄 · 몇 초 뒤 사라짐 · tone = ok | warn | bad */
export function toast(text, tone = 'ok') {
  let node = document.getElementById('toast');
  if (!node) {
    node = h('div', { id: 'toast', role: 'status', 'aria-live': 'polite' });
    document.body.append(node);
  }
  node.className = `toast toast-${tone} show`;
  node.textContent = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('show'), tone === 'bad' ? 6000 : 3000);
}
