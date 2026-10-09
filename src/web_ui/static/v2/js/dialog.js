/** UI v2 · 확인 창 · 알림 한 줄 (브라우저 기본 confirm 대신 · 화면과 같은 모양) */
import { h } from './dom.js';

/** 확인 · true/false · tone = primary | warning | danger */
export function confirmBox({ title, body, confirmLabel = '확인', tone = 'primary' }) {
  return new Promise((resolve) => {
    const dialog = h('dialog', { class: 'confirm' },
      h('h2', { text: title }),
      h('p', { class: 'confirm-body', text: body }),
      h('div', { class: 'confirm-actions' },
        h('button', { class: 'btn', value: 'cancel', type: 'button', onclick: () => dialog.close('cancel') }, '취소'),
        h('button', { class: `btn btn-${tone}`, value: 'ok', type: 'button', onclick: () => dialog.close('ok') }, confirmLabel)));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(dialog.returnValue === 'ok'); });
    document.body.append(dialog);
    dialog.showModal();
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
