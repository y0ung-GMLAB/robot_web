/** UI v2 · 알람 정책 · 드라이브 알람이 나면 얼마나 세게 멈출지 · 이 프로젝트만 (설계안 2026-10-09)
 *
 * 저장은 Supervisor 가 받아야 끝난다(1초 안에 답이 없으면 서버가 저장하지 않음).
 * 바꾼 것이 없어도 저장할 수 있다 · 적용이 안 맞을 때 다시 밀어 넣는 길 (§6-203).
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import * as act from '../actions.js';

const ui = { draft: null, onlyChanged: false, query: '', busy: false };

export async function loadAlarms(state, changed) {
  const page = state.alarmPage || (state.alarmPage = { data: null, error: '' });
  try {
    const data = await api('GET', '/api/servo-alarm-policy');
    // 고치는 중이면 초안은 그대로 · 아니면 서버 값으로 맞춘다
    if (!ui.draft || !isDirty(page.data)) ui.draft = { ...(data?.overrides || {}) };
    page.data = data;
    page.error = '';
  } catch (error) {
    page.error = error.message || String(error);
  }
  changed();
}

export function isDirtyOverrides(draft, saved) {
  const a = draft || {};
  const b = saved || {};
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].some((key) => Number(a[key] || 0) !== Number(b[key] || 0));
}

function isDirty(data) {
  return Boolean(data) && isDirtyOverrides(ui.draft, data.overrides);
}

const GRADE_TEXT = {
  1: '해당 모터만 정지 · 나머지는 계속 동작',
  2: '재생 전체 정지 · 오류 초기화 후 다시 시작',
  3: '모든 모터 명령 차단 · 프로그램 재시작 필요',
};

function gradeChip(grade) {
  const tone = { 1: 'info', 2: 'warn', 3: 'bad' }[grade] || 'idle';
  return h('span', { class: `chip chip-${tone} mono`, text: String(grade) });
}

export function renderAlarms(state, { changed }) {
  const page = state.alarmPage || {};
  const data = page.data;
  const catalog = Array.isArray(data?.catalog) ? data.catalog : [];
  const draft = ui.draft || {};
  const dirty = isDirty(data);
  const changedCount = Object.keys(draft).length;
  const appliedRevision = state.snap?.safety_status?.servo_alarm_policy_revision;
  const notApplied = data?.policy_revision && appliedRevision && appliedRevision !== data.policy_revision;
  const needle = ui.query.trim().toLowerCase();
  const rows = catalog.filter((row) => (!ui.onlyChanged || draft[row.code])
    && (!needle || `${row.code_label} ${row.name} ${row.guidance}`.toLowerCase().includes(needle)));
  const active = (state.snap?.safety_status?.servo_alarm_active || []).map((item) => String(item?.code));

  const save = async (overrides) => {
    if (ui.busy) return;
    ui.busy = true;
    changed();
    try {
      if (await act.saveAlarmPolicy(overrides)) {
        ui.draft = null;
        await loadAlarms(state, changed);
      }
    } finally {
      ui.busy = false;
      changed();
    }
  };

  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '드라이브 알람' }),
      h('p', { class: 'muted small', text: '드라이브 알람이 발생했을 때 어디까지 정지할지 등급으로 정합니다. 이 프로젝트에만 적용됩니다. 현재 발생한 알람은 상단 상태 표시와 「모터 설정」 화면에서 확인하세요.' })),
    page.error ? h('p', { class: 'tone-text-bad', text: page.error }) : null,
    notApplied ? h('div', { class: 'blocker' }, dot('warn'),
      h('span', { class: 'grow', text: '저장된 알람 등급과 현재 적용된 등급이 다릅니다. 「저장」을 한 번 더 누르면 다시 적용합니다.' })) : null,
    h('section', { class: 'card', 'aria-label': '등급' },
      h('ul', { class: 'list grade-list' }, [1, 2, 3].map((grade) => h('li', { class: 'list-row' },
        gradeChip(grade), h('strong', { text: `${grade}등급` }), h('span', { class: 'muted', text: GRADE_TEXT[grade] }))))),
    h('section', { class: 'card', 'aria-label': '알람 표' },
      h('div', { class: 'row' },
        h('input', { class: 'input grow', type: 'search', placeholder: '코드 또는 이름으로 검색 (Enter)', value: ui.query, 'aria-label': '알람 검색',
          oninput: (event) => { ui.query = event.target.value; }, onchange: () => changed(),
          onkeydown: (event) => { if (event.key === 'Enter') event.target.blur(); } }),
        h('label', { class: 'inline' },
          h('input', { type: 'checkbox', checked: ui.onlyChanged, onchange: (event) => { ui.onlyChanged = event.target.checked; changed(); } }),
          `변경한 항목만 (${changedCount})`)),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table alarm-table' },
        h('thead', {}, h('tr', {}, ['코드', '내용', '기본', '설정', '조치 방법'].map((text) => h('th', { scope: 'col', text })))),
        h('tbody', {}, rows.map((row) => {
          const value = draft[row.code] ? Number(draft[row.code]) : 0;
          const now = active.includes(String(row.code));
          return h('tr', { class: now ? 'alarm-now' : '' },
            h('td', { class: 'mono' }, row.code_label || row.code, row.ethercat_related ? h('small', { class: 'muted', text: ' · EtherCAT' }) : null),
            h('td', { class: 'wrap' }, row.name, now ? h('span', { class: 'chip chip-bad', text: '현재 발생 중' }) : null),
            h('td', {}, gradeChip(row.default_grade)),
            h('td', {}, h('select', { class: 'select select-sm', 'aria-label': `${row.code_label} 등급`, disabled: ui.busy,
              onchange: (event) => {
                const next = Number(event.target.value);
                if (next) draft[row.code] = next; else delete draft[row.code];
                ui.draft = draft;
                event.target.blur();
                changed();
              } },
            h('option', { value: '0', selected: !value }, `기본 (${row.default_grade}등급)`),
            [1, 2, 3].map((grade) => h('option', { value: String(grade), selected: value === grade }, `${grade}등급`)))),
            h('td', { class: 'wrap muted', text: row.guidance || '' }));
        })))) : h('p', { class: 'muted', text: data ? '검색 결과 없음' : '불러오는 중…' })),
    h('div', { class: 'apply-bar' },
      h('span', { class: 'grow', text: dirty ? `저장하지 않은 변경 ${changedCount}개` : `기본값과 다른 항목 ${changedCount}개 · 저장됨` }),
      h('button', { class: 'btn', type: 'button', disabled: ui.busy || !dirty, onclick: () => { ui.draft = { ...(data?.overrides || {}) }; changed(); } }, '되돌리기'),
      h('button', { class: 'btn', type: 'button', disabled: ui.busy || !data, onclick: () => save({}) }, '모두 기본값으로 저장'),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: ui.busy || !data, onclick: () => save({ ...draft }) }, '저장')),
  ];
}
