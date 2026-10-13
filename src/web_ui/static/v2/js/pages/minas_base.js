/**
 * UI v2 · 모터 설정 ① · 드라이브 공통 값 (MINAS · 모든 축) · 수정 목록 114 (사용자 2026-10-13)
 * 계속 맞춰 보는 값(과부하 레벨 · 브레이크 지연)을 화면에서 · 평소엔 잠김 · 「잠금 해제」 확인 뒤에만 고친다.
 * 값은 부팅 때마다 드라이브 RAM 에 쓰인다(EEPROM 아님) · 저장 = 이 PC 값 파일 · 드라이브에는 「장비에 적용」 때.
 * 서버 · GET/PUT /api/motor-config/minas-base · 범위 · 바꿀 수 있는 항목은 서버가 정한다(minas_params).
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import * as act from '../actions.js';

const ui = { rows: null, draft: {}, unlocked: false, busy: false, error: '', loading: false };

async function load(changed) {
  if (ui.loading) return;
  ui.loading = true;
  try {
    const data = await api('GET', '/api/motor-config/minas-base');
    ui.rows = Array.isArray(data?.items) ? data.items : [];
    ui.error = '';
  } catch (error) {
    ui.error = error.message || String(error);
  } finally {
    ui.loading = false;
    changed();
  }
}

async function unlock(changed) {
  const ok = await confirmBox({
    title: '드라이브 공통 값 잠금 해제',
    body: '모든 MINAS 축에 부팅 때마다 쓰이는 값입니다.\n'
      + '잘못 넣으면 서보를 끌 때 축이 처지거나(브레이크 지연), 과부하 알람이 너무 일찍 납니다(과부하 레벨).\n'
      + '바꾼 값은 「장비에 적용」 을 해야 드라이브에 들어갑니다.',
    confirmLabel: '잠금 해제', tone: 'warning',
  });
  if (!ok) return;
  ui.unlocked = true;
  ui.draft = {};
  changed();
}

function lock(changed) {
  ui.unlocked = false;
  ui.draft = {};
  changed();
}

/** 바뀐 칸 · { key: 값 | '' (기본값으로) } */
export function minasBaseChanges(rows, draft) {
  const out = {};
  for (const row of rows || []) {
    if (!(row.key in (draft || {}))) continue;
    const text = String(draft[row.key] ?? '').trim();
    const current = row.local === null || row.local === undefined ? '' : String(row.local);
    if (text === current) continue;
    out[row.key] = text;
  }
  return out;
}

/** 칸 값 검사 · 문제 글 목록 */
export function minasBaseProblems(rows, draft) {
  const problems = [];
  for (const row of rows || []) {
    const text = String((draft || {})[row.key] ?? '').trim();
    if (!text) continue;
    const value = Number(text);
    if (!Number.isInteger(value) || value < row.min || value > row.max) {
      problems.push(`${row.label} 는 ${row.min}~${row.max} ${row.unit} 사이 정수여야 합니다`);
    }
  }
  return problems;
}

async function save(changed) {
  const values = minasBaseChanges(ui.rows, ui.draft);
  if (!Object.keys(values).length) { lock(changed); return; }
  ui.busy = true;
  changed();
  try {
    const result = await api('PUT', '/api/motor-config/minas-base', { body: { values }, timeoutMs: 20000 });
    if (Array.isArray(result?.items)) ui.rows = result.items;
    if (result?.success === false) { toast(result.message || '저장하지 못했습니다', 'bad'); return; }
    ui.unlocked = false;
    ui.draft = {};
    toast(result?.message || '저장했습니다', 'ok');
    if (result?.needs_apply && await act.confirmApplyMotorConfig('드라이브 공통 값을 드라이브에 넣으려면 장비에 적용하고 모터를 재시작해야 합니다.')) {
      await act.applyMotorConfig();
    }
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = false;
    changed();
  }
}

export function minasBaseCard(changed, { hasAc = true } = {}) {
  if (!hasAc) return null;
  if (!ui.rows && !ui.error) { load(changed); return h('section', { class: 'card', 'aria-label': '드라이브 공통 값' }, h('p', { class: 'muted', text: '드라이브 공통 값 불러오는 중…' })); }
  const problems = minasBaseProblems(ui.rows, ui.draft);
  const pending = minasBaseChanges(ui.rows, ui.draft);
  const head = h('div', { class: 'part-head' },
    h('h3', { text: '드라이브 공통 값 · MINAS 모든 축' }),
    h('span', { class: `chip chip-${ui.unlocked ? 'warn' : 'idle'}`, text: ui.unlocked ? '고치는 중' : '잠김' }),
    h('span', { class: 'grow' }),
    ui.unlocked
      ? h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy, onclick: () => lock(changed) }, '취소 · 잠금')
      : h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy || !ui.rows?.length, onclick: () => unlock(changed) }, '잠금 해제'));
  if (ui.error) return h('section', { class: 'card', 'aria-label': '드라이브 공통 값' }, head, h('p', { class: 'tone-text-bad', text: ui.error }));
  const rows = (ui.rows || []).map((row) => {
    const draftValue = ui.draft[row.key];
    const shown = draftValue !== undefined ? draftValue : (row.local ?? '');
    return h('tr', {},
      h('td', {}, h('strong', { text: row.label }), h('div', { class: 'muted small', text: row.note })),
      h('td', {}, ui.unlocked
        ? h('input', { class: 'input mono', type: 'number', step: '1', min: row.min, max: row.max, value: shown,
          placeholder: `기본 ${row.default}`, 'aria-label': row.label,
          oninput: (e) => { ui.draft[row.key] = e.target.value; },
          onchange: () => changed() })
        : h('span', { class: 'mono', text: `${row.value}` })),
      h('td', { class: 'muted', text: row.unit }),
      h('td', { class: 'muted mono', text: `${row.default}` }),
      h('td', {}, h('span', { class: `chip chip-${row.local === null || row.local === undefined ? 'idle' : 'info'}`,
        text: row.local === null || row.local === undefined ? '기본값' : '이 PC 값' })));
  });
  return h('section', { class: 'card', 'aria-label': '드라이브 공통 값' },
    head,
    h('p', { class: 'muted small', text: '부팅 때마다 모든 MINAS 드라이브에 쓰는 값입니다(드라이브 EEPROM 은 그대로). 모터 설정 칸에 그 모터만 적은 값이 있으면 그게 이깁니다. 비워 두면 기본값.' }),
    h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['항목', '값', '단위', '기본값', ''].map((text) => h('th', { scope: 'col', text })))),
      h('tbody', {}, rows))),
    problems.map((text) => h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text }))),
    ui.unlocked ? h('div', { class: 'row-actions' },
      h('button', { class: 'btn btn-primary', type: 'button', disabled: ui.busy || problems.length > 0 || !Object.keys(pending).length,
        onclick: () => save(changed) }, ui.busy ? '저장 중' : '저장 후 장비에 적용'),
      h('span', { class: 'muted small', text: Object.keys(pending).length ? `바뀐 칸 ${Object.keys(pending).length}개` : '바뀐 칸 없음' })) : null);
}
