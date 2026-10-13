/**
 * UI v2 · 모터 설정 ① · 드라이브 공통 설정 · 수정 목록 114 (사용자 2026-10-13)
 * 계속 맞춰 보는 값(브레이크 지연 · 알람 때 멈추는 방법 · 과부하 알람 기준)을 화면에서 · 평소엔 잠김 ·
 * 「잠금 해제」 확인 뒤에만 고친다 · 값은 모터 프로그램이 시작할 때마다 드라이브에 써 넣는다(드라이브 안 영구 저장 아님).
 * 서버 · GET/PUT /api/motor-config/minas-base · 범위 · 보기 · 바꿀 수 있는 항목은 서버가 정한다(minas_params).
 * 이름은 쉬운 말 · 매뉴얼 번호(Pr)는 작게 (사용자 「용어 이상하고 헷갈리는 것 고려」 2026-10-13)
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
    title: '공통 설정 잠금 해제',
    body: '모든 MINAS 드라이브(AC 서보)에 똑같이 들어가는 설정입니다.\n'
      + '잘못 넣으면 서보를 끌 때 축이 처지거나(브레이크 지연), 알람 때 세우는 방법이 바뀌거나, 과부하 알람이 너무 일찍 납니다.\n'
      + '바꾼 값은 「저장 후 장비에 적용」 으로 모터 프로그램을 다시 시작해야 드라이브에 들어갑니다.',
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

/** 바뀐 칸 · { key: 값 | '' (기본으로) } */
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

/** 칸 값 검사 · 문제 글 목록 · 보기 항목은 보기만 */
export function minasBaseProblems(rows, draft) {
  const problems = [];
  for (const row of rows || []) {
    const text = String((draft || {})[row.key] ?? '').trim();
    if (!text) continue;
    const value = Number(text);
    if (Array.isArray(row.choices)) {
      if (!row.choices.some((choice) => choice.value === value)) problems.push(`${row.label} · 보기 중에서 고르세요`);
      continue;
    }
    if (!Number.isInteger(value) || value < row.min || value > row.max) {
      problems.push(`${row.label} · ${row.min}~${row.max} ${row.unit} 사이 정수로 넣으세요`);
    }
  }
  return problems;
}

/** 보이는 값 글 · 드라이브에 들어가는 숫자 그대로(사용자 2026-10-13 「4 뭐 이렇게 원래값대로」) */
export function valueText(row, value) {
  return `${value}${row.unit ? ` ${row.unit}` : ''}`;
}

/** 마우스를 올리면 뜨는 뜻 · 보기 항목은 그 값의 뜻 · 나머지는 항목 설명 */
export function valueHint(row, value) {
  if (Array.isArray(row.choices)) {
    const choice = row.choices.find((c) => c.value === Number(value));
    const others = row.choices.map((c) => `${c.value} = ${c.label}`).join(' · ');
    return choice ? `${value} = ${choice.label} (고를 수 있는 값 · ${others})` : others;
  }
  return row.note || '';
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
    if (result?.needs_apply && await act.confirmApplyMotorConfig('공통 설정을 드라이브에 넣으려면 장비에 적용하고 모터 프로그램을 다시 시작해야 합니다.')) {
      await act.applyMotorConfig();
    }
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = false;
    changed();
  }
}

function editor(row, changed) {
  const draftValue = ui.draft[row.key];
  const shown = draftValue !== undefined ? draftValue : (row.local ?? '');
  if (Array.isArray(row.choices)) {
    const current = String(shown === '' ? row.default : shown);
    return h('select', { class: 'input mono', 'aria-label': row.label, title: valueHint(row, current),
      onchange: (e) => { ui.draft[row.key] = e.target.value === String(row.default) ? '' : e.target.value; changed(); } },
    row.choices.map((choice) => h('option', { value: String(choice.value), title: `${choice.value} = ${choice.label}`,
      selected: String(choice.value) === current ? '' : null },
    `${choice.value}${choice.value === row.default ? ' (기본값)' : ''}`)));
  }
  return h('input', { class: 'input mono', type: 'number', step: '1', min: row.min, max: row.max, value: shown,
    placeholder: `기본값 ${row.default}`, 'aria-label': row.label, title: row.note || '',
    oninput: (e) => { ui.draft[row.key] = e.target.value; },
    onchange: () => changed() });
}

export function minasBaseCard(changed, { hasAc = true, acAxes = [], onSaveAll = null } = {}) {
  if (!hasAc) return null;
  const label = '드라이브 공통 설정';
  if (!ui.rows && !ui.error) { load(changed); return h('section', { class: 'card', 'aria-label': label }, h('p', { class: 'muted', text: '공통 설정 불러오는 중…' })); }
  const problems = minasBaseProblems(ui.rows, ui.draft);
  const pending = minasBaseChanges(ui.rows, ui.draft);
  const head = h('div', { class: 'part-head' },
    h('h3', { text: label }),
    h('span', { class: `chip chip-${ui.unlocked ? 'warn' : 'idle'}`, text: ui.unlocked ? '고치는 중' : '잠김' }),
    h('span', { class: 'grow' }),
    ui.unlocked
      ? h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy, onclick: () => lock(changed) }, '취소')
      : h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy || !ui.rows?.length, onclick: () => unlock(changed) }, '잠금 해제'));
  if (ui.error) return h('section', { class: 'card', 'aria-label': label }, head, h('p', { class: 'tone-text-bad', text: ui.error }));
  const rows = (ui.rows || []).map((row) => {
    const changedHere = row.local !== null && row.local !== undefined;
    return h('tr', {},
      h('td', {},
        h('strong', { text: row.label }), h('span', { class: 'muted small mono', text: `  ${row.number || ''}` }),
        h('div', { class: 'muted small', text: row.note })),
      h('td', { class: 'common-value' }, ui.unlocked ? editor(row, changed)
        : h('span', { class: 'mono hint', text: valueText(row, row.value), title: valueHint(row, row.value) })),
      h('td', { class: 'muted small mono common-default', text: valueText(row, row.default), title: valueHint(row, row.default) }),
      h('td', { class: 'common-state' }, h('span', { class: `chip chip-${changedHere ? 'info' : 'idle'}`, text: changedHere ? '변경됨' : '기본값' })));
  });
  return h('section', { class: 'card', 'aria-label': label },
    head,
    h('p', { class: 'muted small', text: '모든 MINAS 드라이브(AC 서보)에 똑같이 들어가는 설정입니다. 모터 프로그램이 시작할 때마다 드라이브에 써 넣습니다. 브레이크 지연은 브레이크 보드에 연결된 모터에만 해당하고, 위 모터별 칸에 따로 적은 모터는 그 값을 씁니다. 저장하면 장비에 적용할지 묻습니다.' }),
    h('div', { class: 'table-wrap' }, h('table', { class: 'table common-table' },
      h('thead', {}, h('tr', {}, ['항목', '지금 값', '기본값', ''].map((text) => h('th', { scope: 'col', text })))),
      h('tbody', {}, rows))),
    problems.map((text) => h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text }))),
    // 모든 축 EEPROM 저장 · 공통 설정 · 게인 등 지금 드라이브 값이 전원을 꺼도 남게 · 재시작 한 번 · 108 (다)
    !ui.unlocked && onSaveAll && acAxes.length ? h('div', { class: 'pick-row-actions' },
      h('span', { class: 'muted small', text: '적용 뒤 한 번 눌러 두면 프로그램 없이 드라이브만 켜질 때도 같은 값이 쓰입니다' }),
      h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy, onclick: onSaveAll }, `모든 축 드라이브에 저장 (EEPROM) · ${acAxes.length}대`)) : null,
    ui.unlocked ? h('div', { class: 'pick-row-actions' },
      h('span', { class: 'muted small', text: Object.keys(pending).length ? `바꾼 칸 ${Object.keys(pending).length}개` : '바꾼 칸 없음' }),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: ui.busy || problems.length > 0 || !Object.keys(pending).length,
        onclick: () => save(changed) }, ui.busy ? '저장 중' : '공통 설정 저장')) : null);
}
