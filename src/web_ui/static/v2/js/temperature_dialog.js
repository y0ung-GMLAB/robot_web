/**
 * UI v2 · 모터 온도 창 · 누를 때만 뜬다 · 열려 있는 동안 1초마다 새로 그림 · 수정 목록 191
 *
 * 기록(CSV)은 이 창과 상관없이 웹 서비스가 1분마다 늘 적는다(`motor_temperature_log.py` · 7일 보관) ·
 * 창 아래에서 날짜별로 내려받는다.
 * 칸 너비는 고정 · 값이 바뀌어도 표가 움직이지 않게(화면 규칙 · 칸 밀림 없음)
 */
import { h, replace } from './dom.js';
import { api } from './net.js';
import { motorTemperatures, TEMP_WARN_MARGIN_C } from './model.js';

let snapSource = () => null;

/** main.js 가 한 번 · 지금 상태를 읽는 함수 */
export function bindTemperatureSource(getSnap) {
  snapSource = typeof getSnap === 'function' ? getSnap : () => null;
}

function tableBody(rows) {
  if (!rows.length) {
    return [h('tr', {}, h('td', { colspan: '5', class: 'muted', text: '온도를 읽는 모터가 없습니다. 직렬 서보(Dynamixel · Feetech)만 온도를 읽습니다.' }))];
  }
  return rows.map((row) => h('tr', {},
    h('td', { class: 'mono', text: `${row.index}번` }),
    h('td', { class: 'temp-name', text: row.name, title: row.kind }),
    h('td', { class: `mono tone-text-${row.tone}`, text: row.tempText }),
    h('td', { class: 'mono muted', text: row.limitText }),
    h('td', { class: `mono tone-text-${row.tone}`, text: row.marginText })));
}

function kb(bytes) {
  const n = Number(bytes) || 0;
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

async function fillDownloads(box) {
  try {
    const data = await api('GET', '/api/motor-temperature/days');
    const days = Array.isArray(data?.days) ? data.days : [];
    replace(box, days.length
      ? h('ul', { class: 'list' }, days.map((day) => h('li', { class: 'list-row' },
        h('span', { class: 'mono grow', text: day.date }),
        h('span', { class: 'muted small', text: kb(day.size_bytes) }),
        h('a', { href: `/api/motor-temperature/download?date=${encodeURIComponent(day.date)}`, download: '', text: 'CSV 내려받기' }))))
      : h('p', { class: 'muted small', text: '아직 기록이 없습니다. 온도를 읽는 모터가 켜져 있으면 1분마다 기록됩니다.' }));
  } catch (error) {
    replace(box, h('p', { class: 'muted small', text: `기록 목록을 읽지 못했습니다. ${error?.message || ''}` }));
  }
}

export function openTemperatureDialog() {
  const body = h('tbody');
  const draw = () => replace(body, ...tableBody(motorTemperatures(snapSource())));
  const downloads = h('div', { class: 'temp-downloads' }, h('p', { class: 'muted small', text: '불러오는 중…' }));
  const dialog = h('dialog', { class: 'confirm temp-dialog', 'aria-label': '모터 온도' },
    h('h2', { text: '모터 온도' }),
    h('p', { class: 'muted small', text: `한계는 서보에 설정된 값입니다. 한계까지 ${TEMP_WARN_MARGIN_C} °C 안으로 오르면 노란색으로 표시하고, 넘으면 서보가 스스로 토크를 끕니다.` }),
    h('div', { class: 'table-wrap' }, h('table', { class: 'table temp-table' },
      h('colgroup', {}, ['56px', '', '72px', '72px', '72px'].map((width) => h('col', width ? { style: { width } } : {}))),
      h('thead', {}, h('tr', {}, ['번호', '조인트', '온도', '한계', '여유'].map((text) => h('th', { scope: 'col', text })))),
      body)),
    h('h3', { class: 'temp-sub', text: '기록 (1분마다 · 7일 보관)' }),
    downloads,
    h('div', { class: 'confirm-actions' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, '닫기')));
  draw();
  const timer = setInterval(draw, 1000);
  dialog.addEventListener('close', () => { clearInterval(timer); dialog.remove(); });
  document.body.append(dialog);
  dialog.showModal();
  fillDownloads(downloads);
}
