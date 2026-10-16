/** UI v2 · 공연 · 「무엇을 · 어디서(이 PC / 매장 전체) · 어떻게 돌리고 · 멈추나」 (설계안 2026-10-09)
 *
 * 범위가 늘 보인다 · 버튼 글자에도 범위를 쓴다(「지금 멈춤 · 매장 전체」).
 * 시작이 막히면 버튼만 끄지 않고 이유와 해결 버튼을 바로 아래에 쓴다.
 */
import { h, dot } from '../dom.js';
import { runSummary } from '../model.js';
import {
  initialMoveChoices, REPEAT_MODES,
  axisRows, defaultScope, excludedText, fileInfo, groupRows, groupRuntime, groupScopeBlocker, groupStartPreview, groupStopCommand,
  isRunning, phaseSteps, playHeadline, registeredPlaylist, repeatChoice, runStatus, startBlocker,
} from '../play_model.js';
import { segmentCheck, segmentClock, segmentLabel } from '../segment_model.js';
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
  show3d: null,   // 처음 그릴 때 브라우저 기억에서 읽는다
  // 구간 재생 · 입력 칸 글 그대로 · 화면을 열 때마다 비어 있다(통째로) · 지난 구간은 버튼으로 다시 · 2026-10-16
  segStart: '',
  segEnd: '',
};

/** 지난 구간 · 브라우저마다 기억 · 칸은 비워 두고 「지난 구간」 버튼으로만 다시 넣는다(모르고 구간 재생하지 않게) */
const SEGMENT_KEY = 'robot_web.v2.play_segment';
function readLastSegment() {
  try {
    const saved = JSON.parse(localStorage.getItem(SEGMENT_KEY) || 'null');
    return saved && (Number(saved.start_sec) > 0 || Number(saved.end_sec) > 0) ? saved : null;
  } catch { return null; }
}
function writeLastSegment(payload) {
  try { localStorage.setItem(SEGMENT_KEY, JSON.stringify(payload)); } catch { /* 기억 못 해도 된다 */ }
}

/** 3D 동시 재생 켬·끔 · 브라우저마다 기억 · 처음엔 끔
 *  3D 는 보는 쪽 브라우저가 계속 그린다(그래픽·CPU) · 로봇 PC 에서 화면을 띄워 둘 때 부담이 없게 */
const SHOW3D_KEY = 'robot_web.v2.play3d';
function readShow3d() {
  try { return localStorage.getItem(SHOW3D_KEY) === 'on'; } catch { return false; }
}
function writeShow3d(on) {
  try { localStorage.setItem(SHOW3D_KEY, on ? 'on' : 'off'); } catch { /* 기억 못 해도 된다 */ }
}

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
  // 늘 둘 중 하나가 골라져 있게 · 모르는 값이면 「초기 위치로 돌아간 뒤」 · 수정 목록 120 (다)
  if (ui.repeatMode === null || !REPEAT_MODES.some((m) => m.id === ui.repeatMode)) {
    ui.repeatMode = repeatChoice(automation.repeat_mode);
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

/** 매장 전체 · 화면에 골라져 보이는 값을 그대로 보낸다 · 다른 PC 매핑 값과 섞이지 않게 · 「조인트마다 다름」이면 null */
function groupMoveTime(state) {
  return initialMoveChoices(state.play?.mapping?.mappings, ui.initialMove).selected ?? null;
}

function localPayload(state, run_mode, segment) {
  const play = state.play || {};
  return {
    motion_file_id: registeredPlaylist(play.mapping)[0] || '',
    mapping_file_id: play.mappingId || '',
    initial_move_time_sec: ui.initialMove,
    ...runSettings(run_mode),
    ...(segment ? { segment } : {}),
  };
}

/** 구간 재생 · 재생 목록 1번 길이 · 검사 · 단독은 길이까지 보고 막는다 · 그룹은 PC 마다 1번이 달라 모양만(짧은 PC 는 빠짐) */
function segmentState(state) {
  const play = state.play || {};
  const playlist = registeredPlaylist(play.mapping);
  const first = playlist[0] || '';
  const file = (play.files || []).find((item) => fileInfo(item).id === first);
  const length = file ? fileInfo(file).duration : null;
  const group = ui.scope === 'group';
  const check = segmentCheck({ startText: ui.segStart, endText: ui.segEnd, length: group ? null : length });
  // 그룹 · 이 PC 1번보다 길면 이 PC 만 빠진다 · 막지 않고 알린다
  const localNote = group && check.active && !check.error && length !== null && check.start >= length
    ? `이 PC 재생 목록 1번(${segmentClock(length)})보다 길어 이 PC는 빠집니다` : '';
  return { playlist, first, length, check, localNote };
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
    'mode-manual': ['수동 모드로 전환', () => act.setRunMode('manual')],
    'restart-program': ['프로그램 다시 시작', act.restartProgram],
    'ack-group-error': ['그룹 오류 해제', act.ackGroupError],
    'open-mapping': ['조인트 매핑 열기', () => navigate('mapping')],
  };
  // 「open:화면」 · 그 화면으로 · 다회전 클리어 뒤 기준점 지정(#/manual?axis=N) · 수정 목록 140
  if (String(fix || '').startsWith('open:')) map[fix] = ['기준점 지정 열기', () => navigate(fix.slice(5))];
  const entry = map[fix];
  return entry ? h('button', { class: 'btn btn-warn', type: 'button', onclick: entry[1] }, entry[0]) : null;
}

/* ---------- 머리 · 범위 ---------- */

function scopeHeader(state, changed) {
  const group = groupRuntime(state.snap);
  const blocker = groupScopeBlocker(state.snap);
  const groupBusy = group.active;
  // N = 실제로 들어갈 PC 수 · 도는 중이면 이번 참가 PC 수 · 서버 미리 보기가 없으면 옛 방식 · 수정 목록 122 (다)
  const preview = groupStartPreview(state.snap);
  const running = Array.isArray(group.execution.participants) ? group.execution.participants.length : 0;
  const count = groupBusy ? running : (preview.count ?? (group.peers.length + (group.joined ? 1 : 0)));
  const leftOut = groupBusy ? '' : excludedText(preview.excluded);
  return h('div', { class: 'page-head' },
    h('h1', { text: '재생' }),
    segmented('재생 대상', [['local', '단독'], ['group', `그룹 전체${count ? ` · ${count}대` : ''}`, groupBusy ? '' : blocker]], ui.scope, (value) => {
      ui.scope = value;
      changed();
    }),
    h('p', { class: 'muted small', text: ui.scope === 'group'
      ? (groupBusy ? '그룹 전체 재생 중입니다. 정지 버튼을 누르면 이번 재생에 참가한 PC가 모두 정지합니다.' : '각 PC는 자기 재생 목록을 재생하고 함께 시작합니다. 수동 모드 PC도 함께 시작하고, 끔 모드 PC는 빠집니다. 회차를 맞출지는 아래 「PC 간 동기화」에서 정합니다.')
      : (blocker && group.joined ? blocker : '다른 PC와 상관없이 단독으로 재생합니다. 다른 PC는 영향을 받지 않습니다.') }),
    ui.scope === 'group' && leftOut ? h('p', { class: 'small tone-text-warn', text: `${leftOut} · 시작하면 이 PC들은 빼고 재생합니다` }) : null);
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
  const seg = segmentState(state);
  const disabled = Boolean(blocker) || ui.busy || Boolean(seg.check.error);
  const scopeText = group ? '그룹 전체' : '단독';
  // 구간 · 보내는 값 · 틀리면 버튼이 꺼져 있다 · 보낸 구간은 브라우저에 기억(다음에 「지난 구간」 버튼)
  const segment = seg.check.payload;
  const remember = (result) => { if (result && segment) writeLastSegment(segment); return result; };
  const withSegment = segment ? { segment } : {};

  const start = (runMode) => busy(() => (group
    ? act.startGroup({ ...runSettings(runMode), sync_mode: ui.syncMode || 'lockstep', initial_move_time_sec: groupMoveTime(state), ...withSegment })
    : act.startLocal(localPayload(state, runMode, segment))).then(remember), state, changed);
  const initialize = () => busy(() => (group
    ? act.initializeGroup({ initial_move_time_sec: groupMoveTime(state), ...withSegment })
    : act.initializeLocal(localPayload(state, 'once', segment))).then(remember), state, changed);
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
          title: seg.check.active ? '재생 목록 1번 애니메이션의 구간 시작 자세로 천천히 이동합니다' : '재생 목록 첫 애니메이션의 초기 위치로 천천히 이동합니다' }, '초기 위치로'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running, onclick: () => start('once') }, '1회 시작'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running, onclick: () => start('continuous') }, '연속 시작')),
      h('span', { class: 'spacer' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', disabled: !running, onclick: stopAfter }, '이번 회차 후 정지'),
        h('button', { class: 'btn btn-danger', type: 'button', disabled: !running, onclick: () => act.stopNow(group) }, `즉시 정지 · ${scopeText}`))),
    segmentRow(seg, group, running, changed),
    blocker && !running ? h('div', { class: 'blocker' },
      dot('warn'),
      h('span', { class: 'grow', text: `시작할 수 없는 이유: ${blocker.text}` }),
      fixButton(blocker.fix, navigate)) : null);
}

/** 구간 재생 줄 · 시작 · 끝(비우면 끝까지) · 처음부터 · 1번 길이 · 막는 이유 · 2026-10-16 */
function segmentRow(seg, group, running, changed) {
  const { check } = seg;
  const last = readLastSegment();
  const lastText = last ? segmentLabel(last.start_sec, last.end_sec) : '';
  const typed = (key) => (event) => { ui[key] = event.target.value; changed(); };
  const clear = () => { ui.segStart = ''; ui.segEnd = ''; changed(); };
  const restore = () => {
    ui.segStart = Number(last.start_sec) > 0 ? segmentClock(last.start_sec) : '';
    ui.segEnd = Number(last.end_sec) > 0 ? segmentClock(last.end_sec) : '';
    changed();
  };
  const notes = [];
  if (check.active && !check.error) {
    const what = segmentLabel(check.start, check.end);
    notes.push(seg.playlist.length > 1
      ? `재생 목록 1번 ${seg.first.replace(/[.]json$/i, '')}의 ${what}만 재생합니다 · 2번부터는 이번에 재생하지 않습니다`
      : `${what}만 재생합니다`);
    if (group) notes.push('모든 PC · 스피커가 같은 시각부터 · PC마다 자기 재생 목록 1번');
    if (check.note) notes.push(check.note);
    if (seg.localNote) notes.push(seg.localNote);
  }
  return h('div', { class: 'segment-row', role: 'group', 'aria-label': '구간 재생' },
    h('span', { class: 'field-label', text: '구간' }),
    h('label', { class: 'inline' }, '시작',
      h('input', { class: 'input mono', type: 'text', inputmode: 'decimal', placeholder: '0:00', value: ui.segStart, disabled: running,
        'aria-label': '구간 시작 (분:초)', oninput: typed('segStart') })),
    h('label', { class: 'inline' }, '끝',
      h('input', { class: 'input mono', type: 'text', inputmode: 'decimal', placeholder: '끝까지', value: ui.segEnd, disabled: running,
        'aria-label': '구간 끝 (분:초 · 비우면 끝까지)', oninput: typed('segEnd') })),
    h('button', { class: 'btn btn-mini', type: 'button', disabled: running || (!ui.segStart && !ui.segEnd), onclick: clear,
      title: '구간을 비우고 처음부터 끝까지 재생합니다' }, '처음부터'),
    lastText && !ui.segStart && !ui.segEnd ? h('button', { class: 'btn btn-mini', type: 'button', disabled: running, onclick: restore,
      title: '이 브라우저에서 마지막으로 보낸 구간을 다시 넣습니다' }, `지난 ${lastText}`) : null,
    seg.length !== null ? h('span', { class: 'muted small mono', text: `1번 길이 ${segmentClock(seg.length)}` }) : null,
    check.error
      ? h('span', { class: 'segment-note small tone-text-bad', text: `시작할 수 없는 이유: ${check.error}` })
      : h('span', { class: 'segment-note small muted', text: notes.join(' · ') || '비우면 처음부터 끝까지 재생합니다 (m:ss · 예 1:20)' }));
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
      segmented('초기 위치 이동 시간', moveTime.options, moveTime.selected, (value) => { ui.initialMove = moveTime.pick(value); changed(); }),
      group ? h('span', { class: 'muted small', text: '그룹 재생에 참가한 모든 PC에 이 이동 시간을 적용합니다' }) : null),
    h('div', { class: 'field' },
      h('label', { class: 'inline' }, h('span', { class: 'field-label', text: '정지할 회차' }),
        h('input', { class: 'input num-input', type: 'number', min: '0', step: '1', value: String(ui.targetCycles),
          onchange: (event) => { ui.targetCycles = Math.max(0, Math.floor(Number(event.target.value) || 0)); changed(); } }),
        h('span', { class: 'muted small', text: '0 = 계속 반복' }))),
    group ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: 'PC 간 동기화' }),
      segmented('PC 간 동기화', [['lockstep', '회차 맞춤 (먼저 끝난 PC가 기다림)'], ['independent', '각자 재생 (시작만 함께)']], ui.syncMode || 'lockstep', (value) => {
        ui.syncMode = value;
        changed();
        act.saveAutomation({ group_sync_mode: value });
      })) : null);
}

/* ---------- 실행 축 ---------- */

function axesCard(state) {
  const rows = axisRows(state.snap, state.play?.mapping);
  return h('section', { class: 'card', 'aria-label': '실행 조인트' },
    h('div', { class: 'card-head' }, h('h2', { text: '실행 조인트' })),
    h('p', { class: 'muted small', text: '끄면 해당 조인트는 현재 위치에서 정지합니다. 재생 중에 다시 켜면 다음 회차부터 적용됩니다. 이 설정은 저장되지 않으며, 프로그램을 다시 시작하면 모두 켜집니다.' }),
    rows.length
      ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, ['사용', '조인트', '모터', '범위', '현재 값', '범위 초과', '상태'].map((text) => h('th', { scope: 'col', text })))),
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
function previewCard(state, changed) {
  const status = runStatus(state.snap);
  const fileId = String(status.motion_file_id || registeredPlaylist(state.play?.mapping)[0] || '');
  if (ui.show3d === null) ui.show3d = readShow3d();
  // 끄면 칸을 빼기만 한다 · 화면에서 빠진 3D 는 그리기를 멈추고 서버에도 묻지 않는다(viewer3d.js)
  return h('section', { class: 'card', 'aria-label': '3D' },
    h('div', { class: 'card-head' },
      h('label', { class: 'switch' },
        h('input', { type: 'checkbox', role: 'switch', checked: ui.show3d, 'aria-label': '3D 동시 재생',
          onchange: (event) => { ui.show3d = event.target.checked; writeShow3d(ui.show3d); changed(); } }),
        h('span', { class: 'switch-track', 'aria-hidden': 'true' })),
      h('h2', { class: 'grow', text: `3D 동시 재생 · ${ui.show3d ? 'ON' : 'OFF'}` }),
      h('a', { href: '#/pack', text: '로봇 팩·3D' })),
    ui.show3d
      ? getViewer3d().update(state, { fileId })
      : h('p', { class: 'muted small', text: '켜면 로봇 재생에 맞춰 3D 로봇이 함께 움직입니다. 이 화면을 여는 기기의 그래픽을 계속 쓰므로 필요할 때만 켜세요(이 브라우저에 설정이 저장됩니다).' }));
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
    previewCard(state, changed),
    h('div', { class: 'grid-2' },
      playlistCard(state, changed, { link: ['#/animations', '애니메이션'], reload: loadPlay }),
      repeatCard(state, changed)),
    axesCard(state),
  ];
}
