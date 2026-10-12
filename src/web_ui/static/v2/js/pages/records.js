/** UI v2 · 기록 · 재생 기록(회차마다 목표·실제) · 운영 로그 (설계안 2026-10-09)
 *
 * 재생 기록은 런타임이 회차마다 남기는 CSV 와 index.jsonl (motion_trace) · 그래프는 서버가 줄여 보낸 값.
 * 운영 로그는 모터 이벤트(파일 하루 하나) · 카테고리로 거른다.
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import { CATEGORY_LABELS, eventTime, runRows, traceGeometry } from '../records_model.js';

const ui = { tab: 'runs', day: '', run: '', trace: null, traceFor: '', category: 'all', file: 'all', busy: false };

export async function loadRecords(state, changed) {
  const page = state.recordsPage || (state.recordsPage = { days: [], runs: [], events: null });
  try {
    if (ui.tab === 'runs') {
      const days = await api('GET', '/api/motion-trace/days');
      page.days = Array.isArray(days?.days) ? days.days : [];
      if (!ui.day || !page.days.some((d) => d.date === ui.day)) ui.day = page.days[0]?.date || '';
      if (ui.day) {
        const runs = await api('GET', `/api/motion-trace/runs?${new URLSearchParams({ date: ui.day })}`);
        page.runs = Array.isArray(runs?.runs) ? runs.runs : [];
      } else {
        page.runs = [];
      }
      if (!ui.run && page.runs.length) ui.run = runRows(page.runs)[0].file;
      if (ui.run && ui.traceFor !== `${ui.day}/${ui.run}`) await loadTrace(changed);
    } else {
      const query = new URLSearchParams({ category: ui.category, limit: '300', file_name: ui.file });
      page.events = await api('GET', `/api/motor-events?${query}`);
    }
    page.error = '';
  } catch (error) {
    page.error = error.message || String(error);
  }
  changed();
}

async function loadTrace(changed) {
  const key = `${ui.day}/${ui.run}`;
  try {
    ui.trace = await api('GET', `/api/motion-trace/trace?${new URLSearchParams({ date: ui.day, file: ui.run })}`, { timeoutMs: 30000 });
  } catch (error) {
    ui.trace = { error: error.message || String(error) };
  }
  ui.traceFor = key;
  changed();
}

function svg(tag, attrs, ...children) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value));
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

/* ---------- 재생 기록 ---------- */

function runsView(state, changed) {
  const page = state.recordsPage || {};
  const rows = runRows(page.runs);
  const trace = ui.traceFor === `${ui.day}/${ui.run}` ? ui.trace : null;
  const pickDay = (day) => { ui.day = day; ui.run = ''; ui.trace = null; ui.traceFor = ''; loadRecords(state, changed); };
  const pickRun = (file) => { ui.run = file; ui.trace = null; changed(); loadTrace(changed); };
  const removeDay = async () => {
    const ok = await confirmBox({ title: `${ui.day} 재생 기록 삭제`, body: '이날의 회차별 CSV 기록을 모두 삭제합니다. 되돌릴 수 없습니다.', confirmLabel: '삭제', tone: 'danger' });
    if (!ok) return;
    try {
      await api('DELETE', `/api/motion-trace/days/${encodeURIComponent(ui.day)}`);
      toast('삭제했습니다', 'ok');
      ui.day = '';
      ui.run = '';
    } catch (error) { toast(error.message || String(error), 'bad'); }
    loadRecords(state, changed);
  };
  const run = rows.find((row) => row.file === ui.run);
  const record = (page.runs || []).find((r) => r.file === ui.run) || {};
  const axisInfo = new Map((record.axes || []).map((axis) => [String(axis.motion_id), axis]));
  return [
    h('div', { class: 'row' },
      h('select', { class: 'select', 'aria-label': '날짜', onchange: (e) => pickDay(e.target.value) },
        (page.days || []).map((d) => h('option', { value: d.date, selected: d.date === ui.day }, `${d.date} · ${d.cycle_count}회차`))),
      h('span', { class: 'spacer' }),
      ui.day ? h('button', { class: 'btn btn-mini', type: 'button', onclick: removeDay }, '이날 기록 삭제…') : null),
    h('section', { class: 'card', 'aria-label': '회차' },
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table files-table' },
        h('thead', {}, h('tr', {}, ['시작', '회차', '애니메이션', '결과', '최대 오차'].map((text) => h('th', { scope: 'col', text })))),
        h('tbody', {}, rows.map((row) => h('tr', { class: row.file === ui.run ? 'selected' : '' },
          h('td', {}, h('button', { class: 'link-button mono', type: 'button', 'aria-pressed': String(row.file === ui.run), onclick: () => pickRun(row.file) }, row.time)),
          h('td', { class: 'mono', text: `${row.cycle}${row.group ? ' · 그룹' : ''}` }),
          h('td', { class: 'wrap', text: row.motion }),
          h('td', {}, h('span', { class: `chip chip-${row.tone}`, title: row.message, text: row.result })),
          h('td', { class: 'mono', text: row.worst }))))))
        : h('p', { class: 'muted', text: page.days?.length ? '이날 기록 없음' : '아직 재생 기록이 없습니다. 재생하면 회차마다 기록이 남습니다.' })),
    run ? h('section', { class: 'card', 'aria-label': '목표와 실제' },
      h('div', { class: 'card-head' },
        h('h2', { text: `${run.cycle}회차 · 목표와 실제` }),
        h('a', { class: 'btn btn-mini', href: `/api/motion-trace/download?${new URLSearchParams({ date: ui.day, file: ui.run })}`, download: ui.run }, 'CSV 다운로드')),
      h('p', { class: 'muted small' }, h('span', { class: 'legend legend-target' }), ' 목표  ', h('span', { class: 'legend legend-actual' }), ' 실제 · 조인트 deg'),
      !trace ? h('p', { class: 'muted', text: '불러오는 중…' })
        : trace.error ? h('p', { class: 'tone-text-bad', text: trace.error })
          : h('div', { class: 'charts trace-charts' }, (trace.axes || []).map((axis) => {
            const geo = traceGeometry(trace.time, axis.target, axis.actual);
            const info = axisInfo.get(String(axis.motion_id)) || {};
            return h('figure', { class: 'chart' },
              h('figcaption', {},
                h('span', { class: 'mono', text: axis.motion_id }),
                Number.isFinite(Number(info.max_abs_error_deg))
                  ? h('span', { class: 'muted small' }, '최대 오차 ', h('span', { class: 'mono', text: `${Number(info.max_abs_error_deg).toFixed(3)}° · ${Number(info.max_abs_error_at_sec ?? 0).toFixed(1)} s` })) : null),
              geo ? svg('svg', { viewBox: '0 0 600 120', preserveAspectRatio: 'none', role: 'img', 'aria-label': `${axis.motion_id} 목표와 실제` },
                svg('path', { d: geo.target, class: 'trace' }),
                svg('path', { d: geo.actual, class: 'trace-actual' })) : h('p', { class: 'muted small', text: '값 없음' }));
          }))) : null,
  ];
}

/* ---------- 운영 로그 ---------- */

function eventsView(state, changed) {
  const data = state.recordsPage?.events || {};
  const events = Array.isArray(data.events) ? data.events : [];
  const files = Array.isArray(data.files) ? data.files : [];
  const reload = () => loadRecords(state, changed);
  const clear = async () => {
    const ok = await confirmBox({ title: '운영 로그 삭제', body: '이 프로젝트의 운영 로그를 모두 삭제합니다. 되돌릴 수 없습니다.', confirmLabel: '삭제', tone: 'danger' });
    if (!ok) return;
    try { await api('DELETE', '/api/motor-events'); toast('삭제했습니다', 'ok'); } catch (error) { toast(error.message || String(error), 'bad'); }
    reload();
  };
  return [
    h('div', { class: 'row' },
      h('div', { class: 'segmented', role: 'group', 'aria-label': '종류' },
        Object.entries(CATEGORY_LABELS).map(([key, label]) => h('button', {
          class: 'seg', type: 'button', 'aria-pressed': String(ui.category === key), onclick: () => { ui.category = key; reload(); },
        }, label))),
      h('span', { class: 'spacer' }),
      h('select', { class: 'select', 'aria-label': '로그 파일', onchange: (e) => { ui.file = e.target.value; reload(); } },
        h('option', { value: 'all', selected: ui.file === 'all' }, '전체 날짜'),
        files.map((file) => h('option', { value: file.name, selected: file.name === ui.file }, `${file.name.replace(/\.jsonl$/, '')} · ${file.record_count}줄`))),
      h('button', { class: 'btn btn-mini', type: 'button', onclick: clear }, '삭제…')),
    h('section', { class: 'card', 'aria-label': '운영 로그' },
      events.length ? h('ul', { class: 'list event-list' }, events.map((event) => h('li', { class: 'list-row' },
        dot(event.category === 'error' ? 'bad' : event.category === 'coordination' ? 'info' : 'ok'),
        h('span', { class: 'mono muted time', text: `${String(event.timestamp_text || '').slice(5, 10)} ${eventTime(event)}` }),
        h('span', { class: 'chip', text: CATEGORY_LABELS[event.category] || event.category || '-' }),
        h('span', { class: 'grow wrap-text', text: String(event.content || event.event_type || '') }))))
        : h('p', { class: 'muted', text: data.events ? '기록 없음' : '불러오는 중…' })),
  ];
}

export function renderRecords(state, { changed }) {
  const page = state.recordsPage || {};
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '기록' }),
      h('div', { class: 'segmented', role: 'tablist', 'aria-label': '기록 종류' },
        [['runs', '재생 기록'], ['events', '운영 로그']].map(([key, label]) => h('button', {
          class: 'seg', type: 'button', role: 'tab', 'aria-selected': String(ui.tab === key), 'aria-pressed': String(ui.tab === key),
          onclick: () => { ui.tab = key; loadRecords(state, changed); },
        }, label)))),
    page.error ? h('p', { class: 'tone-text-bad', text: page.error }) : null,
    ui.tab === 'runs' ? runsView(state, changed) : eventsView(state, changed),
  ];
}
