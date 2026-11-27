/** UI v2 · 홈 · 운영자 첫 화면 · 「지금 무엇이 · 무엇을 확인할지 · 매장 PC · 오늘 · 모터 · 최근 일」 */
import { h, dot } from '../dom.js';
import { headline, motorChips, pcRows, runSummary, scheduleDay, todayWindows } from '../model.js';
import { eventTarget } from '../records_model.js';
import { masterLink } from '../schedule_model.js';
import { issueRow } from '../shell.js';
import * as act from '../actions.js';

function card(label, title, ...body) {
  return h('section', { class: 'card', 'aria-label': label },
    title ? h('div', { class: 'card-head' }, ...[].concat(title)) : null,
    ...body);
}

function nowCard(state, navigate) {
  const run = runSummary(state.snap);
  const body = [
    h('div', { class: 'now-title' },
      h('h1', { text: run.title }),
      h('span', { class: 'muted', text: run.subtitle })),
  ];
  if (run.moving) {
    body.push(h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(run.ratio * 100)) },
      h('div', { class: 'progress-fill', style: { width: `${(run.ratio * 100).toFixed(1)}%` } })));
    body.push(h('div', { class: 'now-meta' }, h('span', { class: 'mono', text: run.timeText }), h('span', { text: endHint(state) })));
  } else {
    body.push(h('p', { class: 'muted', text: endHint(state) }));
  }
  body.push(h('div', { class: 'row' },
    h('a', { class: 'btn btn-primary', href: '#/play' }, '재생 화면 열기'),
    run.moving ? h('button', { class: 'btn', type: 'button', onclick: () => act.stopAfterCycle(run.group) }, '이번 회차 후 정지') : null));
  return h('section', { class: 'card card-now', 'aria-label': '현재' }, ...body);
}

/**
 * 오늘 운영시간을 정하는 스케줄 · 슬레이브는 제 스케줄이 아니라 마스터 것을 따른다(수정 목록 182) ·
 * 제 목록(빈 목록)으로 그리면 운영 중에도 「오늘 운영 종료」 가 떴다 · 2026-11-18
 * items = null 이면 마스터 시간표를 아직 받지 못함
 */
function todaySource(state) {
  if (state.sched?.is_master !== false) return { items: state.schedules, basis: '' };
  const master = masterLink(state.snap);
  const items = state.snap?.coordination?.runtime?.timetable?.master_schedules;
  return { items: Array.isArray(items) ? items : null, basis: `마스터${master ? `(${master.name})` : ''} 시간표 기준` };
}

const MASTER_PENDING = '마스터 시간표 수신 대기 중';

/** 오늘 남은 운영시간 한 줄 */
function endHint(state) {
  const sched = state.sched;
  if (!sched) return '';
  if (sched.run_mode !== 'schedule') return sched.run_mode === 'manual' ? '수동 모드에서는 스케줄이 동작하지 않습니다' : '끔 모드이므로 동작 명령을 차단 중입니다';
  const { items, basis } = todaySource(state);
  if (!items) return MASTER_PENDING;
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const windows = todayWindows(items, now);
  const current = windows.find((w) => w.start <= minutes && minutes < w.end);
  const next = windows.find((w) => w.start > minutes);
  const text = current ? `오늘 ${hhmm(current.end)} 운영 종료`
    : next ? `다음 시작 ${hhmm(next.start)}`
      : scheduleDay(items, now).kind === 'holiday' ? '오늘 휴무일' : '오늘 운영 종료';
  return basis ? `${text} · ${basis}` : text;
}

function hhmm(minutes) {
  const m = Math.min(minutes, 24 * 60);
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

function issuesSection(state, navigate) {
  const { issues } = headline(state.snap, state.sched, { connected: state.connected });
  if (!issues.length) return null;
  return h('section', { class: 'issues', 'aria-label': '확인할 일' },
    h('h2', { text: `확인할 일 ${issues.length}` }),
    issues.map((issue) => issueRow(issue, navigate)));
}

function storeCard(state) {
  const rows = pcRows(state.snap);
  return card('PC 현황', [h('h2', { text: `PC 현황 ${rows.length || ''}`.trim() }), h('a', { href: '#/store', text: '자세히' })],
    rows.length
      ? h('ul', { class: 'list' }, rows.map((row) => h('li', { class: 'list-row' },
        dot(row.tone),
        h('span', { class: 'grow' }, row.name, row.local ? h('small', { class: 'muted', text: ' · 현재 접속' }) : null),
        h('span', { class: `note tone-text-${row.tone}`, text: row.note }))))
      : h('p', { class: 'muted', text: '같은 네트워크의 다른 PC가 아직 연결되지 않았습니다' }));
}

function scheduleCard(state) {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const { items, basis } = todaySource(state);
  const windows = items ? todayWindows(items, now) : [];
  const bar = h('div', { class: 'timeline', 'aria-hidden': 'true' },
    windows.map((w) => h('div', { class: 'timeline-window', style: { left: `${(w.start / 1440) * 100}%`, width: `${((w.end - w.start) / 1440) * 100}%` } })),
    h('div', { class: 'timeline-now', style: { left: `${(minutes / 1440) * 100}%` } }));
  const clock = state.sched?.clock || {};
  return card('오늘 스케줄', [h('h2', { text: '오늘 스케줄' }), h('a', { href: '#/schedule', text: basis ? '자세히' : '편집' })],
    bar,
    h('div', { class: 'timeline-scale mono' }, ['00', '06', '12', '18', '24'].map((t) => h('span', { text: t }))),
    windows.length
      ? h('ul', { class: 'list' }, windows.map((w) => h('li', { class: 'list-row' }, h('span', { class: 'grow', text: w.name }), h('span', { class: 'mono muted', text: w.text }))))
      : h('p', { class: 'muted', text: !items ? MASTER_PENDING : scheduleDay(items, now).kind === 'holiday' ? '오늘 휴무일' : '오늘 예정된 스케줄 없음' }),
    h('p', { class: 'muted small mono', text: [`${clock.timezone || ''} ${String(clock.local_time || '').slice(11, 16)}`.trim(), basis].filter(Boolean).join(' · ') }));
}

function motorCard(state) {
  const chips = motorChips(state.snap);
  return card('모터', [h('h2', { text: `모터 ${chips.length || ''}`.trim() }), h('a', { href: '#/maintain-motors', text: '모터 설정' })],
    chips.length
      ? h('ul', { class: 'list' }, chips.map((chip) => h('li', { class: 'list-row' },
        dot(chip.tone),
        h('span', { class: 'grow', text: chip.name }),
        h('span', { class: 'mono', text: chip.value }),
        h('span', { class: `note tone-text-${chip.tone}`, text: chip.note }))))
      : h('p', { class: 'muted', text: '연결된 모터가 없습니다' }));
}

function recentCard(state) {
  const events = Array.isArray(state.events) ? state.events.slice(0, 6) : [];
  return card('최근 기록', [h('h2', { text: '최근 기록' }), h('a', { href: '#/records', text: '전체 기록' })],
    events.length
      ? h('ul', { class: 'list' }, events.map((event) => h('li', { class: 'list-row' },
        h('span', { class: 'mono muted time', text: String(event.timestamp_text || '').slice(11, 19) }),
        eventTarget(event) ? h('span', { class: 'mono', text: eventTarget(event) }) : null,
        h('span', { class: 'grow', text: String(event.content || event.event_type || '') }))))
      : h('p', { class: 'muted', text: '기록 없음' }));
}

export function renderHome(state, { navigate }) {
  return [
    nowCard(state, navigate),
    issuesSection(state, navigate),
    h('div', { class: 'grid-3' }, storeCard(state), scheduleCard(state), motorCard(state)),
    recentCard(state),
  ];
}
