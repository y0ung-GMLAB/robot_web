/** UI v2 · 공연 화면이 보는 값 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 공연)
 *
 * 서버 값은 rad · 화면에 낼 때만 deg (기존 화면 규칙 그대로 · 수정 목록 6).
 */
import { pcName } from './model.js';

const DEG = 180 / Math.PI;

/** 움직이는 중 · 이때는 시작 버튼이 꺼지고 재생 목록을 못 바꾼다 */
export const RUNNING_STATES = new Set([
  'preparing', 'initializing', 'countdown', 'running', 'verifying', 'waiting', 'recovering', 'stopping',
]);

/** 그룹 실행이 아직 출발 전 · 이때 「회차 끝나면 멈춤」은 지금 멈춤과 같다 (기존 화면 규칙) */
const GROUP_NOT_STARTED = new Set(['preparing', 'initializing', 'armed', 'start_scheduled']);

export const REPEAT_MODES = [
  { id: 'reinitialize', label: '초기 위치로 돌아간 뒤 다음 회차', short: '초기 위치 → 다음' },
  { id: 'direct', label: '바로 다음 회차', short: '바로 다음' },
  { id: 'dwell', label: '기다렸다 다음 회차', short: '기다렸다 다음' },
  { id: 'dwell_reinitialize', label: '기다렸다 초기 위치 → 다음', short: '기다렸다 초기 위치' },
];

export const INITIAL_MOVE_OPTIONS = [null, 5, 7, 10];

export function runStatus(snap) {
  return snap?.motion_run_status || snap?.motion_state?.motion_run_status || {};
}

export function isRunning(status) {
  return RUNNING_STATES.has(String(status?.state || ''));
}

export function groupRuntime(snap) {
  const coord = snap?.coordination || {};
  const runtime = coord.runtime || {};
  const execution = runtime.execution || {};
  return {
    configured: coord.config?.enabled === true,
    joined: runtime.joined === true,
    master: coord.config?.is_master === true,
    execution,
    active: Boolean(execution.execution_id),
    error: runtime.coordination_error?.active ? String(runtime.coordination_error.message || '그룹 오류') : '',
    peers: Array.isArray(runtime.peers) ? runtime.peers : [],
    local: runtime.local || null,
  };
}

/** 범위 고르기 · 그룹에 들어가 있는 마스터면 매장 전체가 기본 */
export function defaultScope(snap) {
  const group = groupRuntime(snap);
  return group.joined && group.master ? 'group' : 'local';
}

/** 매장 전체를 못 고르는 이유 · 빈 글이면 고를 수 있다 */
export function groupScopeBlocker(snap) {
  const group = groupRuntime(snap);
  if (!group.joined) return '이 PC 가 그룹에 들어가 있지 않습니다';
  if (!group.master) return '매장 전체는 마스터에서만 · 각 PC 는 자기 재생 목록을 돌립니다';
  return '';
}

/** 단계 셋 · 초기 위치 → 재생 → 도착 확인 · 다음 회차 기다림은 재생 뒤로 친다 */
export function phaseSteps(status) {
  const state = String(status?.state || '');
  const order = { initializing: 0, countdown: 0, running: 1, verifying: 2, waiting: 2, recovering: 2 };
  const at = order[state];
  const summary = status?.summary || {};
  const labels = [
    `초기 위치${summary.initialization_duration_sec ? ` · ${Number(summary.initialization_duration_sec).toFixed(1)} s` : ''}`,
    '재생',
    state === 'waiting' ? '다음 회차 기다림' : '도착 확인',
  ];
  return labels.map((label, index) => ({
    label,
    state: at === undefined ? 'todo' : index < at ? 'done' : index === at ? 'now' : 'todo',
  }));
}

/** 재생 목록 · 매핑 파일에 적힌 것 · 없으면 한 개 등록 */
export function registeredPlaylist(mapping) {
  const list = Array.isArray(mapping?.motion_playlist) ? mapping.motion_playlist.filter(Boolean).map(String) : [];
  if (list.length) return list;
  return mapping?.motion_file_id ? [String(mapping.motion_file_id)] : [];
}

export function playlistMove(list, index, delta) {
  const next = [...list];
  const target = index + delta;
  if (index < 0 || index >= next.length || target < 0 || target >= next.length) return next;
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function playlistRemove(list, index) {
  return list.filter((_, i) => i !== index);
}

export const PLAYLIST_MAX = 50;

export function playlistAdd(list, fileId) {
  if (!fileId || list.length >= PLAYLIST_MAX) return [...list];
  return [...list, String(fileId)];
}

/** 애니메이션 파일 한 줄 · 길이 · 검사 · 서버(analysis)와 프리뷰(최상위 valid) 둘 다 읽는다 */
export function fileInfo(file) {
  const analysis = file?.analysis || {};
  const valid = analysis.valid ?? file?.valid;
  const duration = Number(analysis.time?.duration_sec ?? file?.duration_sec);
  return {
    id: String(file?.id || file?.filename || ''),
    name: String(file?.filename || file?.id || ''),
    duration: Number.isFinite(duration) && duration > 0 ? duration : null,
    check: valid === false ? 'bad' : valid === true ? 'ok' : 'unknown',
    checkText: valid === false ? (analysis.message || file?.message || '검사 실패') : valid === true ? '검사 정상' : '검사 전',
  };
}

export function formatDuration(sec) {
  if (sec === null || sec === undefined || !Number.isFinite(Number(sec))) return '-';
  const total = Math.round(Number(sec));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/**
 * 시작 버튼을 막는 이유 · 버튼 아래에 그대로 쓴다 · 해결 버튼이 붙을 수 있으면 `fix`
 * 서버도 같은 것을 거절한다 · 화면은 먼저 알려 줄 뿐 (자동 모드 막기는 서버 run_mode_gate)
 */
export function startBlocker(snap, sched, { scope, playlist, mappingId }) {
  const status = runStatus(snap);
  const safety = snap?.safety_status || {};
  const mode = sched?.run_mode;
  if (safety.emergency_latched) return { text: '긴급 정지가 걸려 있습니다 · 프로그램을 다시 시작해야 풀립니다', fix: 'restart-program' };
  if (mode === 'off') return { text: '끔 모드라 움직임 명령이 막혀 있습니다', fix: 'mode-manual' };
  if (mode === 'schedule') return { text: '자동 모드라 스케줄이 돌립니다 · 지금 멈춰도 스케줄이 곧 다시 시작합니다 · 사람이 직접 돌리려면', fix: 'mode-manual' };
  if (scope === 'group') {
    const blocker = groupScopeBlocker(snap);
    if (blocker) return { text: blocker };
    const group = groupRuntime(snap);
    if (group.error) return { text: `그룹 오류 · ${group.error}`, fix: 'ack-group-error' };
    if (group.active) return { text: '그룹 재생이 이미 돌고 있습니다' };
  } else if (isRunning(status)) {
    return { text: '재생 중입니다' };
  }
  if (snap?.execution_context && snap.execution_context.ready === false) {
    return { text: String(snap.execution_context.message || '실행 준비가 안 됐습니다') };
  }
  if (!mappingId) return { text: '조인트 매핑이 없습니다', fix: 'open-mapping' };
  if (!playlist.length) return { text: '재생 목록이 비었습니다 · 아래에서 애니메이션을 넣으세요' };
  return null;
}

/** 지금 무엇을 · 공연 카드 머리 */
export function playHeadline(snap) {
  const status = runStatus(snap);
  const state = String(status.state || 'idle');
  const file = String(status.motion_file_id || '').replace(/\.json$/i, '');
  const cycle = Number(status.current_cycle || status.display_cycle || 0);
  const index = Number(status.playlist_index);
  const length = Number(status.playlist_length || 0);
  const parts = [];
  if (length > 1 && Number.isInteger(index)) parts.push(`목록 ${index + 1}/${length}`);
  if (status.run_mode === 'continuous' || status.automation_run) parts.push('연속');
  else if (status.run_mode === 'once') parts.push('1회');
  if (status.group_execution) parts.push(status.automation?.group_sync_mode === 'independent' ? '각자 재생' : '회차 맞춤');
  const STATE_TEXT = {
    initializing: '첫 자세로 천천히 가는 중', countdown: '곧 시작', running: '재생 중', verifying: '도착 확인 중',
    waiting: '다음 회차 기다리는 중', recovering: '자동 복구 중', stopping: '멈추는 중', preparing: '준비 중',
    completed: '끝남', stopped: '멈춤', error: '오류로 멈춤', initialized: '첫 자세에 섬',
  };
  const moving = isRunning(status);
  return {
    moving,
    tone: state === 'error' ? 'bad' : moving ? 'ok' : 'idle',
    title: moving && cycle ? `${cycle}회차 ${STATE_TEXT[state] || state}` : (STATE_TEXT[state] || '서 있음'),
    file: moving || state === 'initialized' ? file : '',
    detail: parts.join(' · '),
    message: state === 'error' ? String(status.message || '') : '',
  };
}

/** 그룹 PC 줄 · 이번 실행에서 뺀 PC 는 이유 · 돌아오는 PC 는 「다음 회차부터」 */
export function groupRows(snap) {
  const group = groupRuntime(snap);
  const excluded = group.execution.excluded || {};
  const joining = group.execution.joining || {};
  const peers = [...group.peers];
  if (group.local && !peers.some((peer) => peer.pc_id === group.local.pc_id)) peers.unshift({ ...group.local, is_local: true });
  return peers.map((peer) => {
    const id = String(peer.pc_id || '');
    const offline = peer.state && peer.state !== 'online';
    const alarm = Number(peer.servo_alarm_grade || 0) > 0;
    let note = String(peer.motion_step || '그룹 대기');
    let tone = 'ok';
    if (excluded[id]) { note = `빠짐 · ${excluded[id]}`; tone = 'warn'; }
    else if (joining[id]) { note = joining[id] === 'ready' ? '다음 회차부터 들어옴' : '들어올 준비 중'; tone = 'info'; }
    if (alarm) { note = `알람 · ${note}`; tone = 'bad'; }
    if (offline) { note = '연결 안 됨'; tone = 'bad'; }
    return {
      id,
      name: pcName(peer),
      local: peer.is_local === true || (group.local && id === group.local.pc_id),
      cycle: String(peer.motion_cycle_text || '-'),
      progress: String(peer.motion_progress || ''),
      note,
      tone,
    };
  });
}

/** 그룹 「회차 끝나면 멈춤」 · 출발 전이면 지금 멈춤 */
export function groupStopCommand(snap) {
  const state = String(groupRuntime(snap).execution.state || '');
  return GROUP_NOT_STARTED.has(state) ? 'stop_now' : 'stop_after_cycle';
}

function deg(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number * DEG : null;
}

export function signedDeg(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  const text = Math.abs(value).toFixed(digits);
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

/**
 * 실행 축 줄 · 매핑 줄이 바탕(시작 전에도 보인다) · 계획(status.axes)이 있으면 자름 정보를 얹는다
 * 상태 · 끔 = 그 자리에 섬 · 다시 켰는데 회차 중 = 다음 회차부터 · 아니면 재생 중 도는 중
 */
export function axisRows(snap, mapping) {
  const status = runStatus(snap);
  const overrides = status.live_overrides || {};
  const held = new Set(Array.isArray(status.held_motion_ids) ? status.held_motion_ids.map(String) : []);
  const planned = new Map((Array.isArray(status.axes) ? status.axes : []).map((axis) => [String(axis.motion_id), axis]));
  const motors = new Map((snap?.motion_state?.motors || []).map((motor) => [Number(motor.controller_index), motor]));
  const base = Array.isArray(mapping?.mappings) && mapping.mappings.length
    ? mapping.mappings.filter((row) => row.enabled !== false)
    : [...planned.values()];
  const moving = isRunning(status);
  return base.map((row) => {
    const id = String(row.motion_id);
    const plan = planned.get(id) || {};
    const axis = Number(row.motor_axis ?? plan.motor_axis);
    const motor = motors.get(axis) || {};
    const lower = deg(row.motion_lower_rad ?? plan.motion_limit_lower_rad);
    const upper = deg(row.motion_upper_rad ?? plan.motion_limit_upper_rad);
    const muted = overrides[id]?.muted === true;
    let state = moving ? '도는 중' : '대기';
    let tone = moving ? 'ok' : 'idle';
    if (muted) { state = '꺼짐 · 그 자리에 섬'; tone = 'warn'; }
    else if (held.has(id)) { state = '다음 회차부터'; tone = 'info'; }
    return {
      id,
      axis: Number.isFinite(axis) ? axis : null,
      motorType: String(row.motor_type || plan.motor_type || motor.motor_type || '') === 'dynamixel' ? 'DXL' : 'AC',
      range: lower === null || upper === null ? '-' : `${signedDeg(lower)} ~ ${signedDeg(upper)}°`,
      now: signedDeg(deg(motor.motion_actual_rad), 2),
      clamped: plan.motion_clamped === true ? '범위로 자름' : plan.motion_id ? '없음' : '-',
      muted,
      state,
      tone,
    };
  });
}
