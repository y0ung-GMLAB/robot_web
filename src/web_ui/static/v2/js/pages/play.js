/** UI v2 · 공연 · 「무엇을 · 어디서(이 PC / 매장 전체) · 어떻게 돌리고 · 멈추나」 (설계안 2026-10-09)
 *
 * 범위가 늘 보인다 · 버튼 글자에도 범위를 쓴다(「지금 멈춤 · 매장 전체」).
 * 시작이 막히면 버튼만 끄지 않고 이유와 해결 버튼을 바로 아래에 쓴다.
 */
import { h, dot } from '../dom.js';
import { runSummary } from '../model.js';
import {
  initialMoveChoices, REPEAT_MODES,
  axisRows, defaultScope, groupRows, groupRuntime, groupScopeBlocker, groupStopCommand,
  isRunning, phaseSteps, playHeadline, registeredPlaylist, runStatus, startBlocker,
} from '../play_model.js';
import { api } from '../net.js';
import * as act from '../actions.js';
import { playlistCard } from './playlist_card.js';
import { getViewer3d } from '../viewer3d.js';

/** 이 화면에서 고른 것 · 페이지를 떠나도 남는다(새로고침하면 서버 값으로) */
const ui = {
  scope: null,
  repeatMode: null,
  dwellSec: 0,
  syncMode: null,
  initialMove: null,
  targetCycles: 0,
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
    // 올리기·내려받기 주소에 쓰는 프로젝트 번호 · 목록 응답이 실어 온다(기존 화면과 같은 출처)
    play.projectId = String(files?.project_id || play.projectId || '');
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
    'ack-group-error': ['그룹 오류 해제', act.ackGroupError],
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
    h('h1', { text: '재생' }),
    segmented('범위', [['local', '단독'], ['group', `매장 전체${count ? ` · ${count}대` : ''}`, groupBusy ? '' : blocker]], ui.scope, (value) => {
      ui.scope = value;
      changed();
    }),
    h('p', { class: 'muted small', text: ui.scope === 'group'
      ? (groupBusy ? '매장 전체 재생 중입니다. 정지 버튼을 누르면 매장 전체가 멈춥니다.' : '각 PC는 자기 재생 목록을 재생하고, 시작만 함께 합니다.')
      : (blocker && group.joined ? blocker : '다른 PC와 상관없이 단독으로 재생합니다. 다른 PC는 영향을 받지 않습니다.') }));
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
  const scopeText = group ? '매장 전체' : '단독';

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
      h('span', { text: status.summary?.target_cycle_count ? `${status.summary.target_cycle_count}회차 후 정지` : '' })) : null,
    h('div', { class: 'controls' },
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', disabled: disabled || running, onclick: initialize,
          title: '재생 목록 첫 애니메이션의 첫 자세로 천천히 이동합니다' }, '초기 위치로'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running, onclick: () => start('once') }, '1회 시작'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running || loopBlocked, onclick: () => start('continuous'),
          title: loopBlocked ? '시작 자세와 끝 자세가 달라 「바로 다음 회차」로 이어서 재생할 수 없습니다' : '' }, '연속 시작')),
      h('span', { class: 'spacer' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', disabled: !running, onclick: stopAfter }, '이번 회차 후 정지'),
        h('button', { class: 'btn btn-danger', type: 'button', disabled: !running, onclick: () => act.stopNow(group) }, `즉시 정지 · ${scopeText}`))),
    blocker && !running ? h('div', { class: 'blocker' },
      dot('warn'),
      h('span', { class: 'grow', text: `시작할 수 없는 이유: ${blocker.text}` }),
      fixButton(blocker.fix, navigate)) : null,
    loopBlocked && !blocker ? h('p', { class: 'muted small', text: '연속 시작을 할 수 없습니다. 시작 자세와 끝 자세가 달라 「바로 다음 회차」로 이어서 재생할 수 없습니다. 반복을 「초기 위치로 돌아간 뒤 다음 회차」로 바꾸세요.' }) : null);
}

/* ---------- PC 별 (매장 전체) ---------- */

function groupCard(state) {
  const rows = groupRows(state.snap);
  const execution = groupRuntime(state.snap).execution;
  const spread = Number(execution.start_spread_ms);
  return h('section', { class: 'card', 'aria-label': 'PC별 재생 상태' },
    h('div', { class: 'card-head' }, h('h2', { text: 'PC별 재생 상태' }),
      Number.isFinite(spread) && execution.execution_id ? h('span', { class: 'muted small mono', text: `시작 편차 ${spread.toFixed(0)} ms` }) : null),
    rows.length
      ? h('ul', { class: 'list' }, rows.map((row) => h('li', { class: 'list-row' },
        dot(row.tone),
        h('span', { class: 'pc-cell' }, row.name, row.local ? h('small', { class: 'muted', text: ' · 현재 접속' }) : null),
        h('span', { class: 'mono muted cycle-cell', text: row.cycle }),
        h('span', { class: `grow tone-text-${row.tone}`, text: row.note }),
        row.progress ? h('span', { class: 'mono muted small', text: row.progress }) : null)))
      : h('p', { class: 'muted', text: '같은 그룹의 다른 PC가 아직 보이지 않습니다' }));
}

/* ---------- 재생 목록 ---------- */

/* ---------- 반복 ---------- */

function repeatCard(state, changed) {
  const group = ui.scope === 'group';
  const moveTime = initialMoveChoices(state.play?.mapping?.mappings, ui.initialMove);
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
      ui.repeatMode?.startsWith('dwell') ? h('label', { class: 'inline' }, '대기 시간',
        h('input', { class: 'input num-input', type: 'number', min: '0', step: '1', value: String(ui.dwellSec),
          onchange: (event) => { ui.dwellSec = Math.max(0, Number(event.target.value) || 0); act.saveAutomation({ dwell_sec: ui.dwellSec }); } }),
        '초') : null),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '초기 위치 이동 시간' }),
      group
        ? h('span', { class: 'muted small', text: 'PC마다 조인트 매핑에 저장된 시간을 씁니다' })
        : segmented('초기 위치 이동 시간', moveTime.options, moveTime.selected, (value) => { ui.initialMove = moveTime.pick(value); changed(); })),
    h('div', { class: 'field' },
      h('label', { class: 'inline' }, h('span', { class: 'field-label', text: '정지할 회차' }),
        h('input', { class: 'input num-input', type: 'number', min: '0', step: '1', value: String(ui.targetCycles),
          onchange: (event) => { ui.targetCycles = Math.max(0, Math.floor(Number(event.target.value) || 0)); changed(); } }),
        h('span', { class: 'muted small', text: '0 = 계속 반복' }))),
    group ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: 'PC 간 동기화' }),
      segmented('PC 간 동기화', [['lockstep', '회차 맞춤 (짧은 PC가 기다림)'], ['independent', '각자 재생 (시작만 함께)']], ui.syncMode || 'lockstep', (value) => {
        ui.syncMode = value;
        changed();
        act.saveAutomation({ group_sync_mode: value });
      })) : null);
}

/* ---------- 실행 축 ---------- */

function axesCard(state) {
  const rows = axisRows(state.snap, state.play?.mapping);
  return h('section', { class: 'card', 'aria-label': '실행 축' },
    h('div', { class: 'card-head' }, h('h2', { text: '실행 축' })),
    h('p', { class: 'muted small', text: '끄면 그 축은 현재 위치에서 멈춥니다. 재생 중에 다시 켜면 다음 회차부터 적용됩니다. 이 설정은 저장되지 않으며, 프로그램을 다시 시작하면 모두 켜집니다.' }),
    rows.length
      ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, ['사용', '조인트', '모터', '범위', '지금', '범위 제한', '상태'].map((text) => h('th', { scope: 'col', text })))),
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

/** 3D · 실물 재생과 같이 · 도는 애니메이션(없으면 재생 목록 1번 첫 자세) · 칸은 한 번 만들어 계속 쓴다 */
function previewCard(state) {
  const status = runStatus(state.snap);
  const fileId = String(status.motion_file_id || registeredPlaylist(state.play?.mapping)[0] || '');
  return h('section', { class: 'card', 'aria-label': '3D' },
    h('div', { class: 'card-head' }, h('h2', { text: '3D 동시 재생' }), h('a', { href: '#/pack', text: '로봇 팩·3D' })),
    getViewer3d().update(state, { fileId }));
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
    previewCard(state),
    h('div', { class: 'grid-2' },
      playlistCard(state, changed, { link: ['#/animations', '애니메이션'], reload: loadPlay }),
      repeatCard(state, changed)),
    axesCard(state),
  ];
}
