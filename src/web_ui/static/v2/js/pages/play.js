/** UI v2 · 공연 · 「무엇을 · 어디서(이 PC / 매장 전체) · 어떻게 돌리고 · 멈추나」 (설계안 2026-10-09)
 *
 * 범위가 늘 보인다 · 버튼 글자에도 범위를 쓴다(「지금 멈춤 · 매장 전체」).
 * 시작이 막히면 버튼만 끄지 않고 이유와 해결 버튼을 바로 아래에 쓴다.
 */
import { h, dot } from '../dom.js';
import { runSummary } from '../model.js';
import {
  INITIAL_MOVE_OPTIONS, PLAYLIST_MAX, REPEAT_MODES,
  axisRows, defaultScope, fileInfo, formatDuration, groupRows, groupRuntime, groupScopeBlocker, groupStopCommand,
  isRunning, phaseSteps, playHeadline, playlistAdd, playlistMove, playlistRemove, registeredPlaylist, runStatus, startBlocker,
} from '../play_model.js';
import { api } from '../net.js';
import * as act from '../actions.js';

/** 이 화면에서 고른 것 · 페이지를 떠나도 남는다(새로고침하면 서버 값으로) */
const ui = {
  scope: null,
  repeatMode: null,
  dwellSec: 0,
  syncMode: null,
  initialMove: null,
  targetCycles: 0,
  addPick: '',
  busy: false,
};

/** 서버에서 따로 받아 오는 것 · 매핑(재생 목록 · 축) · 애니메이션 파일 목록 */
export async function loadPlay(state, changed) {
  const play = state.play || (state.play = { mappingId: '', mapping: null, files: [], error: '' });
  try {
    const list = await api('GET', '/api/motion-mappings');
    play.mappingId = String(list?.active_file_id || '');
    play.mapping = play.mappingId
      ? (await api('GET', `/api/motion-mappings/${encodeURIComponent(play.mappingId)}`))?.mapping || null
      : null;
    const files = await api('GET', '/api/motion-files');
    play.files = Array.isArray(files?.files) ? files.files : [];
    play.error = '';
  } catch (error) {
    play.error = error.message || String(error);
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

function syncFromServer(status) {
  const automation = status.automation || {};
  if (ui.repeatMode === null) {
    ui.repeatMode = automation.repeat_mode || 'reinitialize';
    ui.dwellSec = Number(automation.dwell_sec || 0);
  }
  if (ui.syncMode === null && automation.group_sync_mode) ui.syncMode = automation.group_sync_mode;
}

function runSettings(run_mode) {
  return {
    run_mode,
    repeat_mode: ui.repeatMode || 'reinitialize',
    dwell_sec: ui.repeatMode?.startsWith('dwell') ? Math.max(0, Number(ui.dwellSec) || 0) : 0,
    target_cycle_count: Math.max(0, Math.floor(Number(ui.targetCycles) || 0)),
  };
}

function localPayload(state, run_mode) {
  const play = state.play || {};
  return {
    motion_file_id: registeredPlaylist(play.mapping)[0] || '',
    mapping_file_id: play.mappingId || '',
    initial_move_time_sec: ui.initialMove,
    ...runSettings(run_mode),
  };
}

/** 고르기 칸 · 못 고르는 칸은 [값, 글, 이유] 로 · 이유가 툴팁 */
function segmented(label, options, current, onPick) {
  return h('div', { class: 'segmented', role: 'group', 'aria-label': label },
    options.map(([value, text, blocked]) => h('button', {
      class: 'seg', type: 'button', 'aria-pressed': String(value === current), disabled: Boolean(blocked), title: blocked || '',
      onclick: () => onPick(value),
    }, text)));
}

function fixButton(fix, navigate) {
  const map = {
    'mode-manual': ['수동으로 바꾸기', () => act.setRunMode('manual')],
    'restart-program': ['프로그램 다시 시작', act.restartProgram],
    'ack-group-error': ['그룹 오류 풀기', act.ackGroupError],
    'open-mapping': ['조인트 매핑 열기', () => navigate('mapping')],
  };
  const entry = map[fix];
  return entry ? h('button', { class: 'btn btn-warn', type: 'button', onclick: entry[1] }, entry[0]) : null;
}

/* ---------- 머리 · 범위 ---------- */

function scopeHeader(state, changed) {
  const group = groupRuntime(state.snap);
  const blocker = groupScopeBlocker(state.snap);
  const count = group.peers.length || (group.joined ? 1 : 0);
  const groupBusy = group.active;
  return h('div', { class: 'page-head' },
    h('h1', { text: '공연' }),
    segmented('범위', [['local', '이 PC 만'], ['group', `매장 전체${count ? ` · ${count}대` : ''}`, groupBusy ? '' : blocker]], ui.scope, (value) => {
      ui.scope = value;
      changed();
    }),
    h('p', { class: 'muted small', text: ui.scope === 'group'
      ? (groupBusy ? '매장 전체 재생이 도는 중 · 멈춤 버튼은 매장 전체에 갑니다' : '각 PC 는 자기 재생 목록을 돌립니다 · 시작만 같이')
      : (blocker && group.joined ? blocker : '이 PC 만 돌립니다 · 다른 PC 는 그대로') }));
}

/* ---------- 지금 · 버튼 ---------- */

function nowCard(state, changed, navigate) {
  const status = runStatus(state.snap);
  const head = playHeadline(state.snap);
  const run = runSummary(state.snap);
  const group = ui.scope === 'group';
  const groupActive = groupRuntime(state.snap).active;
  const running = group ? groupActive || isRunning(status) : isRunning(status);
  const play = state.play || {};
  const playlist = registeredPlaylist(play.mapping);
  const blocker = startBlocker(state.snap, state.sched, { scope: ui.scope, playlist, mappingId: play.mappingId });
  const loopBlocked = status.capabilities?.continuous_run?.available === false
    && (ui.repeatMode === 'direct' || ui.repeatMode === 'dwell');
  const disabled = Boolean(blocker) || ui.busy;
  const scopeText = group ? '매장 전체' : '이 PC';

  const start = (runMode) => busy(() => (group
    ? act.startGroup({ ...runSettings(runMode), sync_mode: ui.syncMode || 'lockstep' })
    : act.startLocal(localPayload(state, runMode))), state, changed);
  const initialize = () => busy(() => (group ? act.initializeGroup() : act.initializeLocal(localPayload(state, 'once'))), state, changed);
  const stopAfter = () => (group ? act.stopGroupAfterCycle(groupStopCommand(state.snap)) : act.stopAfterCycle(false));

  return h('section', { class: `card card-now tone-${head.tone}`, 'aria-label': '지금' },
    h('div', { class: 'now-title' },
      h('h2', { class: 'now-h', text: head.title }),
      head.file ? h('strong', { class: 'mono', text: head.file }) : null,
      head.detail ? h('span', { class: 'muted', text: head.detail }) : null),
    head.message ? h('p', { class: 'tone-text-bad', text: head.message }) : null,
    head.moving ? h('ol', { class: 'steps', 'aria-label': '단계' },
      phaseSteps(status).map((step) => h('li', { class: `step step-${step.state}` },
        step.state === 'done' ? '✓ ' : '', step.label))) : null,
    head.moving ? h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(run.ratio * 100)) },
      h('div', { class: 'progress-fill', style: { width: `${(run.ratio * 100).toFixed(1)}%` } })) : null,
    head.moving ? h('div', { class: 'now-meta' }, h('span', { class: 'mono', text: run.timeText }),
      h('span', { text: status.summary?.target_cycle_count ? `${status.summary.target_cycle_count}회차 뒤 멈춤` : '' })) : null,
    h('div', { class: 'controls' },
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', disabled: disabled || running, onclick: initialize,
          title: '재생 목록 첫 애니메이션의 첫 자세로 천천히 갑니다' }, '초기 위치로'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running, onclick: () => start('once') }, '1회 시작'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running || loopBlocked, onclick: () => start('continuous'),
          title: loopBlocked ? '시작·끝 자세가 달라 「바로 다음」 으로는 못 이어 돕니다' : '' }, '연속 시작')),
      h('span', { class: 'spacer' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', disabled: !running, onclick: stopAfter }, '이 회차 끝나면 멈춤'),
        h('button', { class: 'btn btn-danger', type: 'button', disabled: !running, onclick: () => act.stopNow(group) }, `지금 멈춤 · ${scopeText}`))),
    blocker && !running ? h('div', { class: 'blocker' },
      dot('warn'),
      h('span', { class: 'grow', text: `시작 버튼이 꺼진 이유 · ${blocker.text}` }),
      fixButton(blocker.fix, navigate)) : null,
    loopBlocked && !blocker ? h('p', { class: 'muted small', text: '연속 시작이 꺼진 이유 · 시작·끝 자세가 달라 「바로 다음」 으로 이어 돌 수 없습니다 · 반복을 「초기 위치 → 다음」 으로 바꾸세요' }) : null);
}

/* ---------- PC 별 (매장 전체) ---------- */

function groupCard(state) {
  const rows = groupRows(state.snap);
  const execution = groupRuntime(state.snap).execution;
  const spread = Number(execution.start_spread_ms);
  return h('section', { class: 'card', 'aria-label': 'PC 별' },
    h('div', { class: 'card-head' }, h('h2', { text: 'PC 별' }),
      Number.isFinite(spread) && execution.execution_id ? h('span', { class: 'muted small mono', text: `시작 편차 ${spread.toFixed(0)} ms` }) : null),
    rows.length
      ? h('ul', { class: 'list' }, rows.map((row) => h('li', { class: 'list-row' },
        dot(row.tone),
        h('span', { class: 'pc-cell' }, row.name, row.local ? h('small', { class: 'muted', text: ' · 이 PC' }) : null),
        h('span', { class: 'mono muted cycle-cell', text: row.cycle }),
        h('span', { class: `grow tone-text-${row.tone}`, text: row.note }),
        row.progress ? h('span', { class: 'mono muted small', text: row.progress }) : null)))
      : h('p', { class: 'muted', text: '같은 그룹의 다른 PC 가 아직 안 보입니다' }));
}

/* ---------- 재생 목록 ---------- */

function playlistCard(state, changed) {
  const play = state.play || {};
  const status = runStatus(state.snap);
  const list = registeredPlaylist(play.mapping);
  const files = new Map((play.files || []).map((file) => [String(file.id || file.filename), fileInfo(file)]));
  const locked = isRunning(status) || ui.busy || !play.mappingId;
  const playingIndex = isRunning(status) && Number.isInteger(Number(status.playlist_index)) ? Number(status.playlist_index) : (isRunning(status) ? 0 : -1);
  const save = (next) => busy(async () => {
    if (await act.savePlaylist(play.mappingId, next)) await loadPlay(state, changed);
  }, state, changed);

  const choices = [...files.values()].filter((file) => file.check !== 'bad');
  if (!choices.some((file) => file.id === ui.addPick)) ui.addPick = choices[0]?.id || '';

  return h('section', { class: 'card', 'aria-label': '재생 목록' },
    h('div', { class: 'card-head' }, h('h2', { text: `이 PC 재생 목록 · ${list.length}` }), h('a', { href: '#/animations', text: '애니메이션' })),
    h('p', { class: 'muted small', text: '차례로 돌고 끝나면 1번부터 · 사이마다 다음 애니메이션의 첫 자세로 천천히 갑니다' }),
    play.error ? h('p', { class: 'tone-text-bad', text: play.error }) : null,
    list.length
      ? h('ol', { class: 'playlist' }, list.map((id, index) => {
        const info = files.get(id) || { name: id, duration: null, check: 'unknown', checkText: '목록에 없는 파일' };
        return h('li', { class: `playlist-row${index === playingIndex ? ' playing' : ''}` },
          h('span', { class: 'mono muted num', text: String(index + 1) }),
          h('span', { class: 'grow name', title: info.name, text: info.name }),
          h('span', { class: 'mono muted', text: formatDuration(info.duration) }),
          h('span', { class: `small tone-text-${info.check === 'bad' ? 'bad' : info.check === 'ok' ? 'ok' : 'warn'}`, text: index === playingIndex ? '지금' : info.checkText }),
          h('span', { class: 'row-actions' },
            h('button', { class: 'btn btn-mini', type: 'button', disabled: locked || index === 0, 'aria-label': `${info.name} 위로`, onclick: () => save(playlistMove(list, index, -1)) }, '↑'),
            h('button', { class: 'btn btn-mini', type: 'button', disabled: locked || index === list.length - 1, 'aria-label': `${info.name} 아래로`, onclick: () => save(playlistMove(list, index, 1)) }, '↓'),
            h('button', { class: 'btn btn-mini', type: 'button', disabled: locked, onclick: () => save(playlistRemove(list, index)) }, '빼기')));
      }))
      : h('p', { class: 'muted', text: '비었습니다 · 아래에서 애니메이션을 넣으세요' }),
    h('div', { class: 'row add-row' },
      h('select', { class: 'select grow', 'aria-label': '넣을 애니메이션', disabled: locked || !choices.length,
        onchange: (event) => { ui.addPick = event.target.value; } },
      choices.map((file) => h('option', { value: file.id, selected: file.id === ui.addPick }, `${file.name} · ${formatDuration(file.duration)}`))),
      h('button', { class: 'btn', type: 'button', disabled: locked || !ui.addPick || list.length >= PLAYLIST_MAX,
        onclick: () => save(playlistAdd(list, ui.addPick)) }, '넣기')),
    locked && isRunning(status) ? h('p', { class: 'muted small', text: '재생 중에는 목록을 못 바꿉니다 · 멈춘 뒤에' } ) : null);
}

/* ---------- 반복 ---------- */

function repeatCard(state, changed) {
  const group = ui.scope === 'group';
  const mappingTime = (state.play?.mapping?.mappings || []).find((row) => row.initial_move_time_sec)?.initial_move_time_sec;
  const pickRepeat = (value) => {
    ui.repeatMode = value;
    changed();
    act.saveAutomation({ repeat_mode: value, dwell_sec: value.startsWith('dwell') ? Number(ui.dwellSec) || 0 : 0 });
  };
  return h('section', { class: 'card', 'aria-label': '반복' },
    h('div', { class: 'card-head' }, h('h2', { text: '반복' })),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '회차 사이' }),
      h('div', { class: 'choice-list', role: 'radiogroup', 'aria-label': '회차 사이' },
        REPEAT_MODES.map((mode) => h('button', {
          class: 'choice', type: 'button', role: 'radio', 'aria-checked': String(ui.repeatMode === mode.id), onclick: () => pickRepeat(mode.id),
        }, mode.label))),
      ui.repeatMode?.startsWith('dwell') ? h('label', { class: 'inline' }, '기다림',
        h('input', { class: 'input num-input', type: 'number', min: '0', step: '1', value: String(ui.dwellSec),
          onchange: (event) => { ui.dwellSec = Math.max(0, Number(event.target.value) || 0); act.saveAutomation({ dwell_sec: ui.dwellSec }); } }),
        '초') : null),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '첫 자세로 가는 시간' }),
      segmented('첫 자세로 가는 시간', INITIAL_MOVE_OPTIONS.map((value) => [value, value === null
        ? `매핑 설정${mappingTime ? ` (${Number(mappingTime)} s)` : ''}` : `${value} s`]), ui.initialMove, (value) => { ui.initialMove = value; changed(); })),
    h('div', { class: 'field' },
      h('label', { class: 'inline' }, h('span', { class: 'field-label', text: '몇 회차 뒤 멈춤' }),
        h('input', { class: 'input num-input', type: 'number', min: '0', step: '1', value: String(ui.targetCycles),
          onchange: (event) => { ui.targetCycles = Math.max(0, Math.floor(Number(event.target.value) || 0)); changed(); } }),
        h('span', { class: 'muted small', text: '0 = 계속' }))),
    group ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: 'PC 사이' }),
      segmented('PC 사이', [['lockstep', '회차 맞춤 (짧은 PC 가 기다림)'], ['independent', '각자 재생 (처음만 같이)']], ui.syncMode || 'lockstep', (value) => {
        ui.syncMode = value;
        changed();
        act.saveAutomation({ group_sync_mode: value });
      })) : null);
}

/* ---------- 실행 축 ---------- */

function axesCard(state) {
  const rows = axisRows(state.snap, state.play?.mapping);
  return h('section', { class: 'card', 'aria-label': '실행 축' },
    h('div', { class: 'card-head' }, h('h2', { text: '실행 축 · 이 PC' })),
    h('p', { class: 'muted small', text: '끄면 그 자리에 섭니다 · 다시 켜도 돌던 중이면 다음 회차부터 · 저장되지 않습니다(프로그램을 다시 시작하면 다 켜짐)' }),
    rows.length
      ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, ['사용', '조인트', '모터', '범위', '지금', '범위로 자름', '상태'].map((text) => h('th', { scope: 'col', text })))),
        h('tbody', {}, rows.map((row) => h('tr', { class: row.muted ? 'muted-row' : '' },
          h('td', {}, h('label', { class: 'switch' },
            h('input', { type: 'checkbox', role: 'switch', checked: !row.muted, 'aria-label': `${row.id} 사용`,
              onchange: (event) => act.setAxisMuted(row.id, !event.target.checked) }),
            h('span', { class: 'switch-track', 'aria-hidden': 'true' }))),
          h('td', { class: 'mono', text: row.id }),
          h('td', { class: 'mono muted', text: row.axis === null ? '-' : `${row.axis} · ${row.motorType}` }),
          h('td', { class: 'mono', text: row.range }),
          h('td', { class: 'mono', text: row.now }),
          h('td', { class: 'muted', text: row.clamped }),
          h('td', {}, h('span', { class: `chip chip-${row.tone}`, text: row.state })))))))
      : h('p', { class: 'muted', text: '조인트 매핑이 없습니다' }));
}

function previewCard() {
  return h('section', { class: 'card', 'aria-label': '3D' },
    h('div', { class: 'card-head' }, h('h2', { text: '3D' }), h('a', { href: '/', text: '기존 화면에서 보기' })),
    h('p', { class: 'muted', text: '3D 보기는 다음 단계에서 이 화면에 붙입니다 · 지금은 기존 화면 › 애니메이션 › 3D' }));
}

export function renderPlay(state, { navigate, changed }) {
  const status = runStatus(state.snap);
  syncFromServer(status);
  if (ui.scope === null && state.snap) ui.scope = defaultScope(state.snap);
  if (ui.scope === 'group' && groupScopeBlocker(state.snap) && !groupRuntime(state.snap).active) ui.scope = 'local';
  return [
    scopeHeader(state, changed),
    nowCard(state, changed, navigate),
    ui.scope === 'group' ? groupCard(state) : null,
    h('div', { class: 'grid-2' }, playlistCard(state, changed), repeatCard(state, changed)),
    axesCard(state),
    previewCard(),
  ];
}
