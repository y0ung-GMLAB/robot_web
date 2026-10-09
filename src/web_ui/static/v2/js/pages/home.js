/** UI v2 · 홈 · 운영자 첫 화면 · 「지금 무엇이 · 무엇을 확인할지 · 매장 PC · 오늘 · 모터 · 최근 일」 */
import { h, dot } from '../dom.js';
import { headline, motorChips, pcRows, runSummary, todayWindows } from '../model.js';
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
    body.push(h('p', { class: 'muted', text: endHint(state) || '재생하려면 공연 화면에서 · 자동 모드면 스케줄이 시작합니다' }));
  }
  body.push(h('div', { class: 'row' },
    h('a', { class: 'btn btn-primary', href: '#/play' }, '공연 화면 열기'),
    run.moving ? h('button', { class: 'btn', type: 'button', onclick: () => act.stopAfterCycle(run.group) }, '이 회차 끝나면 멈춤') : null));
  return h('section', { class: 'card card-now', 'aria-label': '지금' }, ...body);
}

/** 오늘 남은 운영 시간 한 줄 */
function endHint(state) {
  const sched = state.sched;
  if (!sched) return '';
  if (sched.run_mode !== 'schedule') return sched.run_mode === 'manual' ? '수동 · 스케줄이 손대지 않습니다' : '끔 · 움직임 명령이 막혀 있습니다';
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const windows = todayWindows(state.schedules, now);
  const current = windows.find((w) => w.start <= minutes && minutes < w.end);
  if (current) return `오늘 ${hhmm(current.end)} 에 회차 끝나면 멈춤`;
  const next = windows.find((w) => w.start > minutes);
  return next ? `다음 시작 ${hhmm(next.start)}` : '오늘 운영 끝';
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
  return card('매장 PC', [h('h2', { text: `매장 PC ${rows.length || ''}`.trim() }), h('a', { href: '#/store', text: '자세히' })],
    rows.length
      ? h('ul', { class: 'list' }, rows.map((row) => h('li', { class: 'list-row' },
        dot(row.tone),
        h('span', { class: 'grow' }, row.name, row.local ? h('small', { class: 'muted', text: ' · 이 PC' }) : null),
        h('span', { class: `note tone-text-${row.tone}`, text: row.note }))))
      : h('p', { class: 'muted', text: '같은 망의 다른 PC 를 기다리는 중' }));
}

function scheduleCard(state) {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const windows = todayWindows(state.schedules, now);
  const bar = h('div', { class: 'timeline', 'aria-hidden': 'true' },
    windows.map((w) => h('div', { class: 'timeline-window', style: { left: `${(w.start / 1440) * 100}%`, width: `${((w.end - w.start) / 1440) * 100}%` } })),
    h('div', { class: 'timeline-now', style: { left: `${(minutes / 1440) * 100}%` } }));
  const clock = state.sched?.clock || {};
  return card('오늘 스케줄', [h('h2', { text: '오늘 스케줄' }), h('a', { href: '#/schedule', text: '편집' })],
    bar,
    h('div', { class: 'timeline-scale mono' }, ['00', '06', '12', '18', '24'].map((t) => h('span', { text: t }))),
    windows.length
      ? h('ul', { class: 'list' }, windows.map((w) => h('li', { class: 'list-row' }, h('span', { class: 'grow', text: w.name }), h('span', { class: 'mono muted', text: w.text }))))
      : h('p', { class: 'muted', text: '오늘 도는 스케줄 없음' }),
    h('p', { class: 'muted small mono', text: `${clock.timezone || ''} ${String(clock.local_time || '').slice(11, 16)}`.trim() }));
}

function motorCard(state) {
  const chips = motorChips(state.snap);
  return card('이 PC 모터', [h('h2', { text: `이 PC 모터 ${chips.length || ''}`.trim() }), h('a', { href: '#/maintain-motors', text: '정비' })],
    chips.length
      ? h('ul', { class: 'list' }, chips.map((chip) => h('li', { class: 'list-row' },
        dot(chip.tone),
        h('span', { class: 'grow', text: chip.name }),
        h('span', { class: 'mono', text: chip.value }),
        h('span', { class: `note tone-text-${chip.tone}`, text: chip.note }))))
      : h('p', { class: 'muted', text: '모터 없음 · 이 PC 는 모터가 연결되지 않았습니다' }));
}

function recentCard(state) {
  const events = Array.isArray(state.events) ? state.events.slice(0, 6) : [];
  return card('최근 일', [h('h2', { text: '최근 일' }), h('a', { href: '#/records', text: '기록 전체' })],
    events.length
      ? h('ul', { class: 'list' }, events.map((event) => h('li', { class: 'list-row' },
        h('span', { class: 'mono muted time', text: String(event.timestamp_text || '').slice(11, 19) }),
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
