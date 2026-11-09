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
  isRunning, phaseSteps, playHeadline, registeredPlaylist, repeatChoice, runStatus, startBlocker, timetableView,
} from '../play_model.js';
import { segmentCheck, segmentClock, segmentLabel } from '../segment_model.js';
import { api } from '../net.js';
import * as act from '../actions.js';
import { playlistCard } from './playlist_card.js';
import { getViewer3d } from '../viewer3d.js';
import { tip } from '../tip.js';

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
    ? `현재 PC는 재생 목록 1번(${segmentClock(length)})이 구간보다 짧아 제외` : '';
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
    ui.scope === 'group'
      ? tip(['그룹에 참여한 PC가 각자의 재생 목록을 동시에 시작', '수동 모드 PC는 참여, 끔 모드 PC는 제외', '회차를 맞출지는 「반복 → PC 간 동기화」에서 설정', '정지하면 참여한 PC 모두 정지'], '그룹 전체 설명')
      : tip(['현재 PC만 재생하며 다른 PC에는 영향 없음'], '단독 설명'),
    // 경고 자리는 늘 둔다(레이아웃 고정) · 그룹 = 빠질 PC · 단독 = 그룹을 못 쓰는 이유
    h('p', { class: 'small tone-text-warn msg-slot', text: ui.scope === 'group'
      ? (leftOut ? `시작 시 제외되는 PC: ${leftOut}` : '')
      : (blocker && group.joined ? blocker : '') }));
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

  // 구간 · 누르는 순간의 칸 값으로 다시 검사해 보낸다 · 칸에 커서가 있으면 화면을 다시 그리지 않아(dom.js)
  // 그린 때 값은 낡았다 · 적자마자 누르면 구간 없이 통째로 재생됐다 · 틀리면 보내지 않고 이유를 보인다
  // 보낸 구간은 브라우저에 기억(다음에 「지난 구간」 버튼)
  const withSegmentNow = (send) => {
    const check = segmentState(state).check;
    if (check.error) {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
      changed();
      return;
    }
    const segment = check.payload;
    return busy(() => send(segment).then((result) => {
      if (result && segment) writeLastSegment(segment);
      return result;
    }), state, changed);
  };
  const start = (runMode) => withSegmentNow((segment) => (group
    ? act.startGroup({ ...runSettings(runMode), sync_mode: ui.syncMode || 'lockstep', initial_move_time_sec: groupMoveTime(state), ...(segment ? { segment } : {}) })
    : act.startLocal(localPayload(state, runMode, segment))));
  const initialize = () => withSegmentNow((segment) => (group
    ? act.initializeGroup({ initial_move_time_sec: groupMoveTime(state), ...(segment ? { segment } : {}) })
    : act.initializeLocal(localPayload(state, 'once', segment))));
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
          title: seg.check.active ? '재생 목록 1번의 구간 시작 자세로 천천히 이동' : '재생 목록 1번의 초기 위치로 천천히 이동' }, '초기 위치로'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running, onclick: () => start('once') }, '1회 시작'),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || running, onclick: () => start('continuous') }, '연속 시작')),
      h('span', { class: 'spacer' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', disabled: !running, onclick: stopAfter }, '이번 회차 후 정지'),
        h('button', { class: 'btn btn-danger', type: 'button', disabled: !running, onclick: () => act.stopNow(group) }, `즉시 정지 · ${scopeText}`))),
    segmentRow(seg, group, running, changed),
    blocker && !running ? h('div', { class: 'blocker' },
      dot('warn'),
      h('span', { class: 'grow', text: blocker.text }),
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
      ? `재생 목록 1번 ${seg.first.replace(/[.]json$/i, '')}의 ${what}만 재생 (2번부터는 재생 안 함)`
      : `${what}만 재생`);
    if (group) notes.push('모든 PC와 스피커가 같은 구간 재생');
    if (check.note) notes.push(check.note);
    if (seg.localNote) notes.push(seg.localNote);
  }
  return h('div', { class: 'segment-row', role: 'group', 'aria-label': '구간 재생' },
    h('span', { class: 'field-label inline' }, '구간', tip(['분:초 형식으로 입력 (예 1:20)', '비워 두면 처음부터 끝까지 재생', '그룹 재생 시 모든 PC와 스피커가 각자 재생 목록 1번의 같은 구간을 재생'], '구간 설명')),
    h('label', { class: 'inline' }, '시작',
      h('input', { class: 'input mono', type: 'text', inputmode: 'decimal', placeholder: '0:00', value: ui.segStart, disabled: running,
        'aria-label': '구간 시작 (분:초)', oninput: typed('segStart') })),
    h('label', { class: 'inline' }, '끝',
      h('input', { class: 'input mono', type: 'text', inputmode: 'decimal', placeholder: '끝까지', value: ui.segEnd, disabled: running,
        'aria-label': '구간 끝 (분:초)', oninput: typed('segEnd') })),
    h('button', { class: 'btn btn-mini', type: 'button', disabled: running || (!ui.segStart && !ui.segEnd), onclick: clear,
      title: '구간 비우기' }, '처음부터'),
    lastText && !ui.segStart && !ui.segEnd ? h('button', { class: 'btn btn-mini', type: 'button', disabled: running, onclick: restore,
      title: '마지막으로 재생한 구간' }, `지난 ${lastText}`) : null,
    seg.length !== null ? h('span', { class: 'muted small mono', text: `1번 길이 ${segmentClock(seg.length)}` }) : null,
    check.error
      ? h('span', { class: 'segment-note small tone-text-bad', text: check.error })
      : h('span', { class: 'segment-note small muted', text: notes.join(' · ') }));
}

/* ---------- PC 별 (매장 전체) ---------- */

function groupCard(state) {
  const rows = groupRows(state.snap);
  const execution = groupRuntime(state.snap).execution;
  const timetable = timetableView(state.snap);
  const spread = Number(execution.start_spread_ms);
  // 머리 오른쪽 · 신호 재생 = 시작 편차 · 시간표 재생 = 다음 회차 시각(없으면 이유) · 자리는 늘 둔다 ·
  // 시간표 방식이어도 사람이 누른 그룹 재생(신호 재생)이 도는 중이면 시작 편차
  const headText = timetable.clock && !timetable.signalRun
    ? (timetable.nextText || timetable.reason)
    : (Number.isFinite(spread) && execution.execution_id ? `시작 편차 ${spread.toFixed(0)} ms` : '');
  return h('section', { class: 'card', 'aria-label': 'PC별 재생 상태' },
    h('div', { class: 'card-head' }, h('h2', { text: 'PC별 재생 상태' }),
      h('span', { class: 'muted small mono msg-slot', text: headText })),
    rows.length
      ? h('ul', { class: 'list' }, rows.map((row) => h('li', { class: 'list-row' },
        dot(row.tone),
        h('span', { class: 'pc-cell' }, row.name, row.local ? h('small', { class: 'muted', text: ' · 현재 접속' }) : null),
        h('span', { class: 'mono muted cycle-cell', text: row.cycle }),
        h('span', { class: `grow tone-text-${row.tone}`, text: row.note }),
        h('span', { class: `mono small clock-cell ${row.clockWarn ? 'tone-text-warn' : 'muted'}`, text: row.clock }),
        row.progress ? h('span', { class: 'mono muted small', text: row.progress }) : null)))
      : h('p', { class: 'muted', text: '같은 그룹의 다른 PC가 아직 연결되지 않았습니다' }));
}

/** 그룹 재생 방식 · 회차 간격 · 마스터에서만 바꿈 · 슬레이브는 보기만 · 수정 목록 186 */
function timetableFields(state) {
  const timetable = timetableView(state.snap);
  const master = groupRuntime(state.snap).master;
  const locked = master ? '' : '마스터 PC에서 변경';
  return [
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '그룹 재생 방식', title: [
        '신호 재생 · 마스터가 회차마다 시작 신호',
        '시간표 재생 · 스케줄 운영에만 적용 · 모든 PC가 같은 시간표로 각자 시작',
        '시간표 재생 · 연결이 끊긴 PC도 재생 유지',
        '직접 누른 그룹 재생 · 늘 신호 재생',
        '변경 · 마스터 PC만 · 다음 회차 경계부터 적용',
      ].join(' · ') }),
      segmented('그룹 재생 방식', [['lockstep', '신호 재생', locked], ['clock', '시간표 재생', locked]],
        timetable.clock ? 'clock' : 'lockstep', (value) => act.setTimetable({ mode: value }))),
    h('div', { class: 'field' },
      h('label', { class: 'inline' },
        h('span', { class: 'field-label', text: '회차 간격', title: [
          '0 · 자동(가장 긴 애니메이션 + 초기 위치 이동)',
          '자동보다 짧은 값 · 저장 안 됨',
          '시간표 재생(스케줄 운영)에서만 사용',
        ].join(' · ') }),
        h('input', { class: 'input num-input', type: 'number', min: '0', step: '10', value: String(timetable.period || 0),
          disabled: Boolean(locked) || !timetable.clock, 'aria-label': '회차 간격(초)',
          onchange: (event) => act.setTimetable({ period_sec: Math.max(0, Number(event.target.value) || 0) }) }),
        's',
        h('span', { class: 'muted small mono', text: timetable.autoText }))),
  ];
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
      h('span', { class: 'field-label inline' }, '초기 위치 이동 시간', group ? tip(['그룹 재생 시 참여한 모든 PC에 같은 시간 적용']) : null),
      segmented('초기 위치 이동 시간', moveTime.options, moveTime.selected, (value) => { ui.initialMove = moveTime.pick(value); changed(); })),
    h('div', { class: 'field' },
      h('label', { class: 'inline' }, h('span', { class: 'field-label', text: '정지할 회차' }),
        h('input', { class: 'input num-input', type: 'number', min: '0', step: '1', value: String(ui.targetCycles),
          onchange: (event) => { ui.targetCycles = Math.max(0, Math.floor(Number(event.target.value) || 0)); changed(); } }),
        h('span', { class: 'muted small', text: '0 = 계속 반복' }))),
    group ? h('div', { class: 'field' },
      h('span', { class: 'field-label inline' }, 'PC 간 동기화', tip(['회차 맞춤: 먼저 끝난 PC는 다른 PC를 기다렸다가 다음 회차를 함께 시작', '각자 재생: 시작만 함께 하고 이후에는 PC별로 반복'])),
      segmented('PC 간 동기화', [['lockstep', '회차 맞춤'], ['independent', '각자 재생']], ui.syncMode || 'lockstep', (value) => {
        ui.syncMode = value;
        changed();
        act.saveAutomation({ group_sync_mode: value });
      })) : null,
    ...(group ? timetableFields(state) : []));
}

/* ---------- 실행 축 ---------- */

function axesCard(state) {
  const rows = axisRows(state.snap, state.play?.mapping);
  return h('section', { class: 'card', 'aria-label': '실행 조인트' },
    h('div', { class: 'card-head' }, h('h2', { text: '실행 조인트' })),
    rows.length
      ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {},
          h('th', { scope: 'col' }, '사용', tip(['끄면 해당 모터는 현재 위치에서 정지', '재생 중에 다시 켜면 다음 회차부터 동작', '프로그램을 다시 시작하면 모두 켜짐'], '사용 설명')),
          ['조인트', '모터', '범위', '현재 값', '범위 초과', '상태'].map((text) => h('th', { scope: 'col', text })))),
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
      h('h2', { class: 'grow' }, `3D 동시 재생 · ${ui.show3d ? 'ON' : 'OFF'}`,
        tip(['켜면 로봇 재생에 맞춰 3D 화면에서 동시 재생', '그래픽 부하가 커서 필요할 때만 사용 권장'], '3D 동시 재생 설명')),
      h('a', { href: '#/pack', text: '로봇 팩·3D' })),
    ui.show3d ? getViewer3d().update(state, { fileId }) : null);
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
