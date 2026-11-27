/** UI v2 · 스케줄 · 「자동 모드일 때 언제 켜고 끄나」 (설계안 2026-10-09)
 *
 * 이번 주를 한눈에 · 목록 · 바로 옆 편집 칸 · 운영시간이 끝나면 무엇을.
 * 슬레이브 PC 는 읽기만 · 마스터 화면으로 가는 길을 준다(서버도 저장을 거절한다 · §6-69).
 */
import { h, dot } from '../dom.js';
import { RUN_MODE_LABEL } from '../model.js';
import { tip } from '../tip.js';
import {
  KINDS, WEEK, dateText, datedNote, draftFrom, draftPayload, draftProblem, masterLink, repeatText, scheduleGroups,
  timeText, timezoneDrift, weekRows,
} from '../schedule_model.js';
import { api } from '../net.js';
import * as act from '../actions.js';

const ui = { draft: null, busy: false };

/** 이 화면만 쓰는 값 · 운영시간 끝 동작 · 지난번 결과 · 목록은 바로 새로 */
export async function loadSchedule(state, changed) {
  const page = state.schedulePage || (state.schedulePage = { endAction: '', endMessage: '' });
  try {
    const list = await api('GET', '/api/schedule/list');
    state.schedules = Array.isArray(list) ? list : (list?.schedules || []);
  } catch { /* 홈과 같은 30초 갱신이 다시 받는다 */ }
  try {
    const run = await api('GET', '/api/motion-run/status');
    const action = run?.status?.automation?.schedule_end_action;
    page.endAction = action === 'hold' ? 'hold' : action === 'park_servo_off' ? 'park_servo_off' : (page.endAction || 'park_servo_off');
    page.endMessage = String(run?.schedule_end?.message || '');
  } catch { /* 못 읽으면 기본값 */ }
  changed();
}

async function busy(work, state, changed) {
  if (ui.busy) return;
  ui.busy = true;
  changed();
  try { await work(); } finally {
    ui.busy = false;
    await loadSchedule(state, changed);
  }
}

function hhmm(minutes) {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

function clockLine(sched) {
  const clock = sched?.clock || {};
  const time = String(clock.local_time || '').slice(11, 19);
  const synced = clock.ntp_synced;
  return h('p', { class: 'muted small' },
    'PC 시각 ', h('span', { class: 'mono', text: time || '-' }),
    ` · ${clock.timezone || '시간대 알 수 없음'}`,
    synced === true ? ' · 시계 동기화' : synced === false ? h('span', { class: 'tone-text-warn', text: ' · 시계 동기화 X' }) : null);
}

/* ---------- 이번 주 ---------- */

function weekCard(state) {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const rows = weekRows(state.schedules, now);
  const selected = ui.draft?.id || '';
  return h('section', { class: 'card', 'aria-label': '이번 주' },
    h('div', { class: 'card-head' }, h('h2', { text: '이번 주' })),
    clockLine(state.sched),
    h('div', { class: 'week' },
      h('div', { class: 'week-row week-scale', 'aria-hidden': 'true' }, h('span', {}),
        h('div', { class: 'timeline-scale mono' }, ['00', '06', '12', '18', '24'].map((t) => h('span', { text: t })))),
      rows.map((row) => h('div', { class: `week-row${row.today ? ' today' : ''}` },
        h('span', { class: 'week-day', text: row.today ? `${row.label} · 오늘` : row.label }),
        h('div', { class: 'timeline', role: 'img', 'aria-label': `${row.label}${row.tag ? ` ${row.tag}` : ''} ${row.windows.map((w) => `${w.name} ${hhmm(w.start)}–${hhmm(w.end)}`).join(', ') || '없음'}` },
          row.windows.map((w) => h('div', {
            class: `timeline-window${w.id && w.id === selected ? ' selected' : ''}`,
            title: `${w.name} ${hhmm(w.start)} – ${hhmm(w.end)}`,
            style: { left: `${(w.start / 1440) * 100}%`, width: `${((w.end - w.start) / 1440) * 100}%` },
          }, w.end - w.start >= 150 && !w.carried ? h('span', { class: 'window-label', text: w.name }) : null)),
          // 특정일 · 휴무일 표시 · 오른쪽 끝에 겹쳐 띄움(레이아웃 고정)
          row.tag ? h('span', { class: `timeline-tag${row.tag === '휴무일' ? ' holiday' : ''}`, text: row.tag }) : null,
          row.today ? h('div', { class: 'timeline-now', style: { left: `${(minutes / 1440) * 100}%` } }) : null)))));
}

/* ---------- 목록 ---------- */

function scheduleRow(item, ctx) {
  const { state, changed, canEdit, items, active, unreadable, now } = ctx;
  const id = String(item.schedule_id || '');
  const on = item.enabled !== false;
  const name = String(item.schedule_name || '스케줄');
  const holiday = item.repeat_type === 'holiday';
  const note = datedNote(item, items, now);
  const past = note === '지난 날짜';
  const tone = unreadable.has(id) ? 'bad' : !on || past ? 'idle' : id === active ? 'ok' : 'info';
  // 정기 운영 · 「10:00 – 18:00 · 월 · 화」 · 특정일 운영 · 「09:00 – 18:00 · 2026-11-18 (수)」 · 휴무일 · 「2026-11-26 (목) · 휴무일」
  const when = holiday
    ? [dateText(item.run_date), ' · 휴무일']
    : [h('span', { class: 'mono', text: timeText(item) }), ` · ${item.repeat_type === 'once' ? dateText(item.run_date) : repeatText(item)}`];
  return h('li', { class: `sched-row${ui.draft?.id === id ? ' editing' : ''}${on && !past ? '' : ' off'}` },
    dot(tone),
    h('div', { class: 'grow sched-text' },
      h('strong', { text: name }),
      h('span', { class: 'muted small' },
        ...when,
        id === active ? h('span', { class: 'tone-text-ok', text: ' · 운영 중' }) : null,
        note ? h('span', { class: note === '같은 날짜의 휴무일 우선 적용' ? 'tone-text-warn' : '', text: ` · ${note}` }) : null,
        unreadable.has(id) ? h('span', { class: 'tone-text-bad', text: ' · 시각 오류로 실행되지 않음' }) : null,
        !on ? ' · 꺼짐' : null)),
    canEdit ? h('span', { class: 'row-actions' },
      h('label', { class: 'switch', title: on ? '끄기' : '켜기' },
        h('input', { type: 'checkbox', role: 'switch', checked: on, 'aria-label': `${name} 켜기`, disabled: ui.busy,
          onchange: (event) => busy(() => act.setScheduleEnabled(id, event.target.checked), state, changed) }),
        h('span', { class: 'switch-track', 'aria-hidden': 'true' })),
      h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy, onclick: () => { ui.draft = draftFrom(item); changed(); } }, '편집'),
      h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy, onclick: () => busy(async () => {
        if (await act.deleteSchedule(id, name) && ui.draft?.id === id) ui.draft = null;
      }, state, changed) }, '삭제')) : null);
}

function listCard(state, changed, canEdit) {
  const items = Array.isArray(state.schedules) ? state.schedules : [];
  const now = new Date();
  const ctx = {
    state, changed, canEdit, items, now,
    active: String(state.sched?.active_schedule_id || ''),
    unreadable: new Set((state.sched?.unreadable_schedules || []).map((item) => String(item?.schedule_id ?? item))),
  };
  const groups = scheduleGroups(items, now);
  const group = (title, hint, rows) => (rows.length ? h('div', { class: 'sched-group' },
    h('h3', { class: 'sched-group-title' }, title, hint ? tip(hint) : null),
    h('ul', { class: 'list sched-list' }, rows.map((item) => scheduleRow(item, ctx)))) : null);
  return h('section', { class: 'card', 'aria-label': '스케줄 목록' },
    h('div', { class: 'card-head' }, h('h2', { text: `스케줄 ${items.length}` })),
    items.length
      ? [
        group('특정일', ['특정일 운영 · 휴무일로 지정한 날짜에는 정기 운영 대신 해당 설정을 적용', '같은 날짜에 특정일 운영과 휴무일이 함께 있는 경우 휴무일 우선 적용'], groups.dated),
        group('정기 운영', null, groups.regular),
      ]
      : h('p', { class: 'muted', text: '스케줄이 없습니다. 스케줄 모드여도 재생이 시작되지 않습니다.' }),
    endActionBlock(state, changed, canEdit));
}

function endActionBlock(state, changed, canEdit) {
  const page = state.schedulePage || {};
  const current = page.endAction || 'park_servo_off';
  const options = [
    ['park_servo_off', '기준점 이동 후 정지 (서보 OFF)'],
    ['hold', '최종 위치에서 정지 (서보 ON 유지)'],
  ];
  return h('div', { class: 'field end-action' },
    h('span', { class: 'field-label', text: '운영시간이 끝나면' }),
    h('div', { class: 'choice-list', role: 'radiogroup', 'aria-label': '운영시간이 끝나면' },
      options.map(([value, label]) => h('button', {
        class: 'choice', type: 'button', role: 'radio', 'aria-checked': String(current === value), disabled: ui.busy || !canEdit,
        onclick: () => busy(async () => { if (await act.saveEndAction(value)) page.endAction = value; }, state, changed),
      }, label))),
    page.endMessage ? h('p', { class: 'muted small', text: `최근 결과 · ${page.endMessage}` }) : null);
}

/* ---------- 편집 ---------- */

const NAME_HINT = { regular: '예: 매장 운영', date: '예: 연말 연장 운영', holiday: '예: 추수감사절' };

function editCard(state, changed) {
  const draft = ui.draft;
  const kind = draft.kind || 'regular';
  const problem = draftProblem(draft, state.schedules);
  const set = (key) => (event) => { draft[key] = event.target.value; };
  const toggleDay = (code) => {
    draft.days = draft.days.includes(code) ? draft.days.filter((day) => day !== code) : [...draft.days, code];
    changed();
  };
  const save = () => busy(async () => {
    if (await act.saveSchedule(draftPayload(draft))) ui.draft = null;
  }, state, changed);
  return h('section', { class: 'card edit-card', 'aria-label': '스케줄 편집' },
    h('div', { class: 'card-head' }, h('h2', { text: draft.id ? `편집 · ${draft.name || '스케줄'}` : '새 스케줄' })),
    h('label', { class: 'field' }, h('span', { class: 'field-label', text: '이름' }),
      h('input', { class: 'input', type: 'text', value: draft.name, placeholder: NAME_HINT[kind], maxlength: '40', oninput: set('name') })),
    h('div', { class: 'field' },
      h('span', { class: 'field-label inline' }, '구분',
        tip(['특정일 운영 · 휴무일로 지정한 날짜에는 정기 운영 대신 해당 설정을 적용', '전날 시작해 자정을 넘기는 운영시간은 전날 설정을 따름'])),
      h('div', { class: 'segmented', role: 'group', 'aria-label': '구분' },
        KINDS.map(([value, label]) => h('button', {
          class: 'seg', type: 'button', 'aria-pressed': String(kind === value), onclick: () => { draft.kind = value; changed(); },
        }, label)))),
    // 반복 · 날짜는 같은 자리 · 같은 높이(레이아웃 고정)
    kind === 'regular' ? h('div', { class: 'field kind-slot' },
      h('span', { class: 'field-label', text: '반복' }),
      h('div', { class: 'segmented', role: 'group', 'aria-label': '반복' },
        [['daily', '매일'], ['weekly', '요일 선택']].map(([value, label]) => h('button', {
          class: 'seg', type: 'button', 'aria-pressed': String(draft.repeat === value), onclick: () => { draft.repeat = value; changed(); },
        }, label)))) : h('label', { class: 'field kind-slot' }, h('span', { class: 'field-label', text: '날짜' }),
      h('input', { class: 'input mono', type: 'date', value: draft.date, oninput: set('date'), onchange: () => changed() })),
    kind === 'regular' && draft.repeat === 'weekly' ? h('div', { class: 'day-picks', role: 'group', 'aria-label': '요일' },
      WEEK.map(([code, label]) => h('button', {
        class: 'seg day', type: 'button', 'aria-pressed': String(draft.days.includes(code)), onclick: () => toggleDay(code),
      }, label))) : null,
    // 휴무일은 시각이 없다 · 자리는 그대로 두고 숨김(레이아웃 고정)
    h('div', { class: 'row', style: kind === 'holiday' ? { visibility: 'hidden' } : {}, 'aria-hidden': String(kind === 'holiday') },
      h('label', { class: 'field' }, h('span', { class: 'field-label', text: '시작' }),
        h('input', { class: 'input mono', type: 'time', value: draft.start, disabled: kind === 'holiday', oninput: set('start'), onchange: () => changed() })),
      h('label', { class: 'field' }, h('span', { class: 'field-label inline' }, '종료', tip(['종료 시각이 시작 시각보다 이른 경우 다음 날 해당 시각까지 운영 (예 22:00 – 02:00)'])),
        h('input', { class: 'input mono', type: 'time', value: draft.stop, disabled: kind === 'holiday', oninput: set('stop'), onchange: () => changed() }))),
    problem ? h('p', { class: 'tone-text-warn small', text: problem }) : null,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => { ui.draft = null; changed(); } }, '취소'),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: Boolean(problem) || ui.busy, onclick: save }, '저장')));
}

export function renderSchedule(state, { changed }) {
  const sched = state.sched || {};
  const canEdit = sched.is_master !== false;
  const master = canEdit ? null : masterLink(state.snap);
  const drift = timezoneDrift(state.schedules, sched.clock?.timezone);
  const mode = sched.run_mode;
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '스케줄' }),
      tip([`스케줄 모드에서는 아래 운영시간에 따라 ${sched.coordination_joined ? '그룹 전체' : '로봇'} 재생을 자동으로 시작하고 정지`], '스케줄 설명'),
      // 경고 자리는 늘 둔다(레이아웃 고정)
      h('p', { class: 'small tone-text-warn msg-slot', text: mode && mode !== 'schedule' ? `${RUN_MODE_LABEL[mode] || '-'} 모드에서는 스케줄이 실행되지 않습니다` : '' }),
      canEdit ? h('button', { class: 'btn btn-primary', type: 'button', disabled: ui.busy, onclick: () => { ui.draft = draftFrom(null); changed(); } }, '+ 새 스케줄') : null),
    !canEdit ? h('div', { class: 'blocker' }, dot('info'),
      h('span', { class: 'grow', text: `슬레이브 PC는 마스터${master ? `(${master.name})` : ''}의 스케줄을 따릅니다. 수정은 마스터 화면에서 하세요.` }),
      master?.url ? h('a', { class: 'btn', href: master.url, target: '_blank', rel: 'noopener' }, '마스터 화면 열기') : null) : null,
    drift ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: drift })) : null,
    sched.last_failure?.message ? h('div', { class: 'blocker' }, dot('warn'),
      h('span', { class: 'grow', text: `스케줄 시작 거부${sched.last_failure.count ? ` (${sched.last_failure.count}회)` : ''}: ${sched.last_failure.message}` })) : null,
    // 구간 끝 주차 실패 · 그 자리에서 서보 끔 · 이 PC 것 · 수정 목록 131
    sched.schedule_end_notice?.title ? h('div', { class: 'blocker' }, dot(sched.schedule_end_notice.tone === 'bad' ? 'bad' : 'warn'),
      h('span', { class: 'grow', text: `${sched.schedule_end_notice.title} · ${sched.schedule_end_notice.detail || ''}` })) : null,
    weekCard(state),
    h('div', { class: ui.draft ? 'grid-2' : '' }, listCard(state, changed, canEdit), ui.draft && canEdit ? editCard(state, changed) : null),
  ];
}
