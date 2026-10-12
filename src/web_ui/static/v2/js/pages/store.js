/** UI v2 · 매장 PC · 「같은 망에 누가 있고 · 같이 도나 · 버전이 같나」 (설계안 2026-10-09)
 *
 * 이 PC 그룹 참여 스위치 · PC 마다 상태와 화면·터미널 열기 · 모든 PC 업데이트 결과 · 필수 명단.
 */
import { h, dot } from '../dom.js';
import { rosterCandidates, storeRows, updateRows, versionSummary } from '../store_model.js';
import { api } from '../net.js';
import * as act from '../actions.js';

const ui = { busy: false };

/** 업데이트 표는 PC 마다 물어보는 것이라 이 화면에서만 받는다 */
export async function loadStore(state, changed) {
  const page = state.storePage || (state.storePage = { update: null, error: '' });
  try {
    page.update = await api('GET', '/api/system/update-all', { timeoutMs: 20000 });
    page.error = '';
  } catch (error) {
    page.error = error.message || String(error);
  }
  changed();
}

async function busy(work, state, changed) {
  if (ui.busy) return;
  ui.busy = true;
  changed();
  try { await work(); } finally {
    ui.busy = false;
    changed();
  }
}

function joinCard(state, changed) {
  const coord = state.snap?.coordination || {};
  const config = coord.config || {};
  const runtime = coord.runtime || {};
  const joined = runtime.joined === true;
  const groupActive = Boolean(runtime.execution?.execution_id);
  const locked = ui.busy || (joined && groupActive);
  return h('section', { class: 'card join-card', 'aria-label': '그룹 참여' },
    h('div', { class: 'join-row' },
      h('label', { class: 'switch switch-lg' },
        h('input', { type: 'checkbox', role: 'switch', checked: joined, disabled: locked, 'aria-label': '그룹 참여',
          onchange: (event) => {
            const want = event.target.checked;
            event.target.checked = joined;
            busy(() => (want ? act.joinGroup(config) : act.leaveGroup()), state, changed);
          } }),
        h('span', { class: 'switch-track', 'aria-hidden': 'true' })),
      h('div', { class: 'grow' },
        h('strong', { text: `그룹 참여 · ${joined ? 'ON' : 'OFF'}` }),
        h('p', { class: 'muted small', text: joined
          ? '같은 그룹의 PC와 함께 재생합니다. 끄면 스케줄을 포함해 단독으로 재생합니다.'
          : '단독으로 재생합니다. 켜면 같은 그룹의 PC와 함께 재생합니다.' }),
        joined && groupActive ? h('p', { class: 'tone-text-warn small', text: '그룹 재생 중에는 끌 수 없습니다. 재생을 정지한 뒤 끄세요.' }) : null)),
    coord.node_connected === false ? h('p', { class: 'tone-text-warn small', text: '연동 서비스가 응답하지 않습니다. 프로그램을 다시 시작해 보세요.' }) : null);
}

function pcCard(row) {
  return h('li', { class: `pc-card${row.local ? ' local' : ''}` },
    h('div', { class: 'pc-card-head' },
      h('strong', { class: 'pc-card-name' }, row.name, row.local ? h('small', { class: 'muted', text: ' · 현재 접속' }) : null),
      h('span', { class: `chip chip-${row.tone === 'ok' ? 'ok' : row.tone}` }, dot(row.tone), ` ${row.status}`)),
    h('span', { class: 'mono muted small', text: row.meta || '-' }),
    h('span', { class: 'small', text: row.role }),
    row.note ? h('span', { class: `small tone-text-${row.tone}`, text: row.note }) : null,
    h('div', { class: 'row pc-links' },
      row.local
        ? h('span', { class: 'muted small', text: '현재 화면' })
        : [
          row.links.web && row.online ? h('a', { class: 'btn btn-mini', href: row.links.web, target: '_blank', rel: 'noopener' }, '화면 열기 ↗') : null,
          row.links.terminal && row.online ? h('a', { class: 'btn btn-mini', href: row.links.terminal, target: '_blank', rel: 'noopener' }, '터미널 ↗') : null,
        ]));
}

function updateCard(state, changed) {
  const page = state.storePage || {};
  const summary = versionSummary(state.snap);
  const rows = updateRows(page.update);
  const running = rows.some((row) => row.tone === 'info');
  return h('section', { class: 'card', 'aria-label': '업데이트' },
    h('div', { class: 'card-head' },
      h('h2', { text: '업데이트' }),
      h('button', { class: `btn ${summary.differ ? 'btn-warn' : ''}`, type: 'button', disabled: ui.busy || running,
        onclick: () => busy(async () => { if (await act.updateAll()) await loadStore(state, changed); }, state, changed) }, '모든 PC 업데이트')),
    h('p', { class: summary.differ ? 'tone-text-warn' : 'muted', text: summary.differ
      ? `${summary.total}대 중 ${summary.differ}대 버전이 다릅니다`
      : `${summary.total}대 모두 같은 버전입니다` }),
    h('p', { class: 'muted small', text: 'PC마다 코드 받기 → 빌드 → 다시 시작 순서로 진행합니다(몇 분). 재생 중인 PC는 업데이트하지 않으며, 실패한 PC는 이전 버전으로 되돌아가 계속 동작합니다. 운영 시간이 아닐 때 진행하세요.' }),
    page.error ? h('p', { class: 'tone-text-bad small', text: page.error }) : null,
    rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['PC', '지난 업데이트', '버전', '메모'].map((text) => h('th', { scope: 'col', text })))),
      h('tbody', {}, rows.map((row) => h('tr', {},
        h('td', { text: row.name }),
        h('td', {}, h('span', { class: `chip chip-${row.tone}`, text: row.state })),
        h('td', { class: 'mono', text: row.version }),
        h('td', { class: 'wrap muted', text: row.note })))))) : h('p', { class: 'muted small', text: page.update ? 'PC가 보이지 않습니다' : '불러오는 중…' }));
}

function rosterCard(state, changed) {
  const config = state.snap?.coordination?.config || {};
  const roster = Array.isArray(config.required_peers) ? config.required_peers.map(String) : [];
  const candidates = rosterCandidates(state.snap);
  const same = roster.length === candidates.length && roster.every((id) => candidates.includes(id));
  return h('section', { class: 'card', 'aria-label': '필수 명단' },
    h('div', { class: 'card-head' }, h('h2', { text: `필수 명단 · ${roster.length}대` })),
    h('p', { class: roster.length ? 'mono' : 'muted', text: roster.length ? roster.join(' · ') : '없음 · 그룹을 시작할 때 연결된 PC로 시작합니다' }),
    h('p', { class: 'muted small', text: '그룹을 시작할 때 이 중 빠진 PC는 「미접속」으로 기록하고 나머지 PC로 시작합니다' }),
    config.is_master ? h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', disabled: ui.busy || !candidates.length || same,
        title: same ? '현재 연결된 PC와 같습니다' : '',
        onclick: () => busy(() => act.saveRoster(candidates), state, changed) }, `현재 연결된 ${candidates.length}대로 다시 지정`)) : h('p', { class: 'muted small', text: '필수 명단은 마스터 PC에서 지정합니다' }));
}

export function renderStore(state, { changed }) {
  const config = state.snap?.coordination?.config || {};
  const rows = storeRows(state.snap);
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: 'PC 현황' }),
      h('p', { class: 'muted small', text: `같은 네트워크의 PC · 그룹 ${config.group_id || '-'} · Domain ${config.dds_domain_id ?? '-'}` })),
    joinCard(state, changed),
    rows.length
      ? h('ul', { class: 'pc-grid', 'aria-label': 'PC 목록' }, rows.map(pcCard))
      : h('section', { class: 'card' }, h('p', { class: 'muted', text: '같은 네트워크의 다른 PC를 기다리는 중입니다. Wi-Fi와 그룹 ID를 확인하세요.' })),
    updateCard(state, changed),
    h('div', { class: 'grid-2' },
      rosterCard(state, changed),
      h('section', { class: 'card', 'aria-label': '모든 PC 일괄 작업' },
        h('div', { class: 'card-head' }, h('h2', { text: '모든 PC 일괄 작업' })),
        h('div', { class: 'row' },
          h('a', { class: 'btn', href: '#/network' }, '시간대 맞추기 (스피커 포함) ›'),
          h('a', { class: 'btn', href: '#/play' }, '그룹 재생 ›')))),
  ];
}
