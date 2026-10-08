import { createMotionFileManager } from './motion_file_manager.js';
import { motionScheduleResumeNote } from './schedule_scope.js';
import { mappingGain, motorToJoint } from './joint_mapping.js';
import {
  playlistPanelHtml,
  playlistProgressText,
  playlistWithAdded,
  playlistWithMoved,
  playlistWithout,
  registeredPlaylist,
} from './motion_playlist.js';
import {
  checkMotionRun,
  configureMotionAutomation,
  deleteMotionFile,
  fetchMotionFile,
  fetchMotionFiles,
  fetchMotionMapping,
  fetchMotionMappings,
  fetchMotionRunStatus,
  importProjectFile,
  initializeMotionRun,
  precomputeMotionFile,
  projectFileDownloadUrl,
  saveMotionMapping,
  saveRegisteredMotionFile,
  setMotionRunLiveOverride,
  startMotionRun,
  fetchScheduleStatus,
  stopMotionRun,
  stopMotionRunAfterCycle,
  requestMotionSafetyStop,
  validateMotionMapping,
} from './api.js';
import {
  displayText,
  escapeHtml,
  formatInt,
  formatMoment,
  formatNumber,
  normalizeMotorTypeKey,
  maxOf,
  minOf,
} from './format.js';
import {
  showAlert,
  showConfirm,
  showPrompt,
} from './ui_dialogs.js';
import { draggingFiles, droppedEntries, walkEntry } from './drop_files.js';
import { createSim3dViewer } from './sim3d.js';
import { createBusyIndicator } from './motion_busy.js';
import { analysisInDeg } from './unit_view.js';

/** 차트 색 · 화면 테마(CSS 토큰)를 따른다 · 리디자인 2026-10-02
 *
 * 전에는 캔버스가 흰 바탕·회색 격자를 박아 그려, 어두운 화면 한가운데
 * 흰 사각형이 떴다 · 토큰이 없으면(시험 환경) 예전 밝은 값으로 돌아간다.
 */
function chartTheme() {
  const fallback = {
    bg: '#ffffff', muted: '#5d6b78', grid: '#d6dee6', ink: '#111827', faint: '#64748b',
  };
  if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') return fallback;
  const css = getComputedStyle(document.documentElement);
  const read = (name, value) => (css.getPropertyValue(name) || '').trim() || value;
  return {
    bg: read('--panel', fallback.bg),
    muted: read('--muted', fallback.muted),
    grid: read('--line', fallback.grid),
    ink: read('--ink', fallback.ink),
    faint: read('--muted', fallback.faint),
  };
}

/** 계열 색 · 어두운 바탕에서 서로 구별되는 8색 (CVD 고려 순서) */
const CHART_SERIES_COLORS = ['#5aa2ff', '#46c06a', '#e5534b', '#d9a62e', '#b083f0', '#3fb8c5', '#d97a4a', '#9aa7b6'];

const MOTOR_AXIS_ANGLE_ALERT_DEG = 360.0;
const MOTION_RUN_STAGES = [
  { key: 'idle', label: '재생 전' },
  { key: 'ready', label: '준비 완료' },
  { key: 'initializing', label: '초기 위치 이동중' },
  { key: 'initialized', label: '초기 위치 완료' },
  { key: 'running', label: '재생 중' },
  { key: 'verifying', label: '위치 확인중' },
  { key: 'completed', label: '재생 완료' },
];


function numericOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function targetText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${formatNumber(number, 3)} deg` : '-';
}

function degValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/**
 * 실행 대상을 한 곳에서 정한다 · §6-98
 *
 * 전에는 대상의 주인이 둘이었다 · 화면의 라디오(사용자가 고름)와 실제 연동
 * 상태(참가·마스터·PC 수)가 따로 놀았다 · 참가하지도 않은 채 "그룹 전체"를
 * 고를 수 있었고, 그러면 버튼이 전부 회색이 되는데 이유는 작은 힌트 글씨
 * 한 줄에만 나왔다.
 *
 * 이제 고를 수 없는 것은 **화면에 없다** · 참가하지 않았으면 그룹 칸이 아예
 * 없고 참가 버튼만 있다.
 *
 * 버튼 이름에 대상을 박는다 · 3대를 움직이는 버튼과 1대를 움직이는 버튼은
 * 글자가 달라야 한다 · 전에는 툴팁으로만 갈렸다.
 */
const PEER_STATE_LABEL = {
  online: '정상', warning: '경고', offline: '끊김', unknown: '확인 중',
};

/** 참가 PC 를 한 줄로 · 자세한 표는 연동 화면에 있다. */
function peerSummaryText(role = {}) {
  const here = `${role.master && role.isMaster ? role.master : '이 PC'}${role.isMaster ? '(마스터)' : ''}`;
  const others = (Array.isArray(role.peers) ? role.peers : []).map((peer) => {
    const name = peer.display_name || peer.pc_id || '이름 없음';
    const state = PEER_STATE_LABEL[peer.state] || peer.state || '확인 중';
    return `${name}${peer.is_master ? '(마스터)' : ''} ${state}`;
  });
  return [here, ...others].join(' · ');
}

/** 어느 조인트 매핑 파일을 열 것인가 · §6-238
 *
 * 프로젝트는 이 파일을 **하나만** 물고 쓴다 · 그 하나를 서버가
 * `active_file_id` 로 알려준다 · 전에는 그 값이 없어서 화면이 목록의
 * **첫 번째**를 골랐다 · 파일이 하나뿐이면 우연히 맞았고, 그래서 오래
 * 들키지 않았다 · 여럿이면 프로젝트가 쓰는 것과 다른 것을 편집하게 된다.
 *
 * 등록된 것이 목록에 없으면(지워졌거나 아직 등록 전) 첫 번째로 물러선다 ·
 * 목록이 비면 빈 글자를 준다 · 그때는 새로 만들어 저장하는 자리다.
 *
 * **함수로 빼 둔다** · 화면 안에 묻어 두면 시험이 글자만 훑게 되고, 이
 * 판단이 틀려도 통과한다 · 실제로 그런 일이 있었다.
 */
export function mappingFileToOpen({ files = [], activeFileId = '' } = {}) {
  const ids = (Array.isArray(files) ? files : [])
    .map((file) => String(file?.id || '').trim())
    .filter(Boolean);
  const registered = String(activeFileId || '').trim();
  if (registered && ids.includes(registered)) return registered;
  return ids[0] || '';
}

export function motionRunTargetView({ role = {}, chosen = 'local' } = {}) {
  const joined = role.joined === true;
  const isMaster = role.isMaster === true;
  const peerCount = Math.max(1, Number(role.peerCount || 1));
  // **그룹 실행은 마스터만 한다** · §6-100
  //
  // 조정 노드가 이미 거부한다("이 PC 는 연동 슬레이브라 그룹 실행을 시작할 수
  // 없습니다") · 그런데 화면은 참가만 하면 `그룹 전체` 를 보여 줬다 · 골라서
  // 누른 뒤에야 거부당하니, 슬레이브 앞에 앉은 사람은 무엇이 잘못됐는지
  // 모른다 · 아예 고를 수 없게 한다.
  // 실행 화면에는 대상 선택이 없다 · §6-100 · 언제나 이 PC 다
  const groupSelectable = false;
  const scope = 'local';
  const group = scope === 'group';
  return {
    scope,
    joined,
    isMaster,
    peerCount,
    groupSelectable,
    // 연동 조작은 연동 화면 하나다 · 실행 화면에는 그리로 가는 길만 둔다
    needsCoordinationSetup: !joined,
    coordinationLinkLabel: joined ? 'PC 연동 설정 열기' : 'PC 연동 설정에서 참가하기',
    peerSummary: group ? peerSummaryText(role) : '',
    localLabel: '이 PC 만',
    groupLabel: `그룹 ${peerCount}대`,
    summary: group
      ? `참가 PC ${peerCount}대가 같은 시각에 움직입니다`
      : '이 PC 에 연결된 모터만 움직입니다',
    buttons: {
      initialize: group ? `그룹 초기 위치 이동 · ${peerCount}대` : '초기 위치 이동',
      start: group ? `그룹 1회 시작 · ${peerCount}대` : '1회 시작',
      continuous: group ? `그룹 연속 시작 · ${peerCount}대` : '연속 시작',
      stop: group ? `그룹 즉시 정지 · ${peerCount}대` : '즉시 정지',
      stopAfter: group ? `그룹 회차 후 정지 · ${peerCount}대` : '현재 회차 후 정지',
    },
  };
}

/**
 * 왜 지금 시작할 수 없는가 · 대상마다 판정하는 규칙이 다르다 · §6-98
 *
 * 로컬은 실행 설정과 파일이, 그룹은 연동 상태(참가·역할·통신·알람)가 정한다 ·
 * 사유는 **한 자리에** 늘 보인다 · 버튼을 회색으로만 두면 고장처럼 보인다 ·
 * 특히 슬레이브 PC 는 시작이 영원히 불가라 더 그렇다.
 */
export function motionRunBlockView({
  scope = 'local', availability = {}, localReady = true, localReason = '',
} = {}) {
  if (scope === 'group') {
    // 그룹이 이미 도는 중이면 막힌 것이 아니다 · 정지는 누구나 할 수 있다
    const blocked = availability.ok !== true && availability.active !== true;
    return { blocked, reason: blocked ? String(availability.reason || '') : '' };
  }
  return {
    blocked: !localReady,
    reason: localReady ? '' : String(localReason || ''),
  };
}

export function registeredMotionFileId(mapping = {}) {
  return String(mapping?.motion_file_id || '').trim();
}

export function effectiveMotionRunProgress(
  status = {},
  {
    nowSec = Date.now() / 1000,
    initialMoveTimeSec = null,
  } = {},
) {
  const state = String(status?.state || 'idle');
  const progress = status?.progress || {};
  const summaryDuration = Number(status?.summary?.duration_sec);
  let elapsed = Number(progress.elapsed_sec);
  let duration = Number(progress.duration_sec);

  if (!Number.isFinite(elapsed)) elapsed = 0.0;
  if (!Number.isFinite(duration) || duration < 0) duration = 0.0;

  if (state === 'initializing') {
    if (Number.isFinite(initialMoveTimeSec) && initialMoveTimeSec >= 0) {
      duration = initialMoveTimeSec;
    }
  } else if (
    state === 'running'
    || state === 'waiting'
    || state === 'verifying'
    || state === 'completed'
  ) {
    duration = duration > 0
      ? duration
      : (Number.isFinite(summaryDuration) ? summaryDuration : 0.0);
  }

  if (state === 'running' || state === 'initializing') {
    const updatedAt = Number(status?.updated_at);
    if (Number.isFinite(updatedAt) && updatedAt > 0 && nowSec >= updatedAt) {
      elapsed += nowSec - updatedAt;
    }
  } else if (
    state === 'waiting'
    || state === 'verifying'
    || state === 'completed'
  ) {
    elapsed = duration;
  }

  elapsed = Math.max(0.0, elapsed);
  if (duration > 0) elapsed = Math.min(elapsed, duration);
  return {
    elapsed_sec: elapsed,
    duration_sec: duration,
    ratio: duration > 0 ? Math.min(Math.max(elapsed / duration, 0.0), 1.0) : 0.0,
    sample_index: progress.sample_index,
    active_axis_count: progress.active_axis_count,
  };
}

export function motionMotorRef(motor) {
  if (!motor) return '';
  const motorType = normalizeMotorTypeKey(motor.motor_type, motor.motor_type_label);
  if (motorType === 'ac_servo') {
    const alias = motor.alias ?? motor.ethercat_alias;
    const numericAlias = Number(alias);
    const masterIndex = Number(motor.ethercat_master_index ?? 0);
    if (!Number.isInteger(masterIndex) || masterIndex < 0) return '';
    if (
      alias !== null && alias !== undefined && alias !== ''
      && Number.isFinite(numericAlias) && numericAlias > 0
    ) {
      return `ac_servo:master:${masterIndex}:alias:${numericAlias}`;
    }
    const slavePosition = Number(motor.slave_position);
    return Number.isInteger(slavePosition) && slavePosition >= 0
      ? `ac_servo:master:${masterIndex}:slave:${slavePosition}`
      : '';
  }
  if (motorType === 'dynamixel') {
    const busId = motor.bus_id ?? motor.node_id;
    const numericBusId = Number(busId);
    const serialPort = String(motor.serial_port ?? '').trim();
    return busId === null || busId === undefined || busId === ''
      || !Number.isInteger(numericBusId) || numericBusId < 0 || !serialPort
      ? ''
      : `dynamixel:port:${encodeURIComponent(serialPort)}:id:${numericBusId}`;
  }
  return '';
}

export function motionMotorRefs(motor) {
  const canonical = motionMotorRef(motor);
  const motorType = normalizeMotorTypeKey(motor?.motor_type, motor?.motor_type_label);
  if (motorType === 'ac_servo') {
    const alias = Number(motor?.alias ?? motor?.ethercat_alias);
    const legacy = Number.isFinite(alias) && alias > 0 ? `ac_servo:alias:${alias}` : '';
    return [canonical, legacy].filter(Boolean);
  }
  if (motorType === 'dynamixel') {
    const busId = Number(motor?.bus_id ?? motor?.node_id);
    const legacy = Number.isInteger(busId) && busId >= 0 ? `dynamixel:id:${busId}` : '';
    return [canonical, legacy].filter(Boolean);
  }
  return canonical ? [canonical] : [];
}

export function motionMotorSelectionValue(motor) {
  const motorRef = motionMotorRef(motor);
  if (motorRef) return motorRef;
  const axis = Number(motor?.controller_index);
  return Number.isFinite(axis) ? `axis:${axis}` : '';
}

export function motionMotorIdentityLabel(motor) {
  const motorType = normalizeMotorTypeKey(motor?.motor_type, motor?.motor_type_label);
  if (motorType === 'ac_servo') {
    const alias = Number(motor?.alias ?? motor?.ethercat_alias);
    const masterIndex = formatInt(motor?.ethercat_master_index ?? 0);
    return Number.isFinite(alias) && alias > 0
      ? `AC Master ${masterIndex} · EEPROM Alias ${formatInt(alias)}`
      : (
        `AC Master ${masterIndex}`
        + ` · EEPROM Alias 미설정 · Slave Position ${formatInt(motor?.slave_position)}`
      );
  }
  if (motorType === 'dynamixel') {
    const serialPort = String(motor?.serial_port ?? '').trim() || '직렬 포트 미설정';
    const busId = motor?.bus_id ?? motor?.node_id ?? motor?.id ?? motor?.device_id;
    return `Dynamixel ${serialPort} · ID ${formatInt(busId)}`;
  }
  const motorId = motor?.id ?? motor?.device_id;
  return `ID ${formatInt(motorId)}`;
}

export function motionMappingTargetKey(row) {
  const motorRef = String(row?.motor_ref || '').trim();
  if (motorRef) return `ref:${motorRef.toLowerCase()}`;
  if (row?.motor_axis !== null && row?.motor_axis !== undefined && row?.motor_axis !== '') {
    return `axis:${Number(row.motor_axis)}`;
  }
  return '';
}

export function motionMotorTargetKey(motor) {
  const motorRef = motionMotorRef(motor);
  if (motorRef) return `ref:${motorRef.toLowerCase()}`;
  const axis = Number(motor?.controller_index);
  return Number.isFinite(axis) ? `axis:${axis}` : '';
}

const JOINT_NAME_LIST_ID = 'motionMappingJointNames';

/** 자동 완성 후보 · 애니메이션 조인트 이름 − 이미 쓴 이름 · 순서는 애니메이션 그대로 · 수정 목록 68 */
export function jointNameSuggestions(motionIds = [], used = new Set()) {
  const seen = new Set();
  return (Array.isArray(motionIds) ? motionIds : [])
    .map((item) => String(item?.motion_id ?? item ?? '').trim())
    .filter((name) => {
      if (!name || used.has(name) || seen.has(name)) return false;
      seen.add(name);
      return true;
    });
}

function defaultMotionAxisRow(motionId, motorAxis = null) {
  return {
    motion_id: String(motionId), enabled: motorAxis !== null,
    motor_ref: '', motor_axis: motorAxis,
    reference_enabled: true, reference_position_deg: 0.0,
    motion_lower_deg: -180.0, motion_upper_deg: 180.0,
    initial_mode: 'reference', initial_motion_position_deg: 0.0,   // 기본 기준점 · 2026-10-03 (13-3)
    initial_move_time_sec: 5.0, invert: false, offset_deg: 0.0,
    scale: 1.0, gear_ratio: 1.0,
  };
}

export function buildGeneratedMotionAxisRows(motors = [], previousRows = []) {
  const normalizedPrevious = (Array.isArray(previousRows) ? previousRows : []).map((row) => ({
    ...row,
    motor_ref: String(row?.motor_ref || '').trim().toLowerCase() === 'ac_servo:alias:0'
      ? ''
      : String(row?.motor_ref || '').trim(),
  })).map((row) => {
    const target = String(row.motor_ref || '').trim().toLowerCase();
    const matches = motors.filter((motor) => target
      ? motionMotorRefs(motor).some((ref) => ref.toLowerCase() === target)
      : Number(motor?.controller_index) === Number(row.motor_axis));
    return matches.length === 1
      ? { ...row, motor_ref: motionMotorRef(matches[0]) }
      : row;
  });
  const targetCounts = normalizedPrevious.reduce((counts, row) => {
    const key = motionMappingTargetKey(row);
    if (key) counts.set(key, (counts.get(key) || 0) + 1);
    return counts;
  }, new Map());
  const previousByTarget = new Map(normalizedPrevious
    .filter((row) => targetCounts.get(motionMappingTargetKey(row)) === 1)
    .map((row) => [motionMappingTargetKey(row), row]));
  const preservedRows = motors.map((motor) => (
    previousByTarget.get(motionMotorTargetKey(motor)) || null
  ));
  // 새 줄의 조인트 이름은 비워 둔다 · 예전 `1-1`·`1-2` 는 Blender 본 이름과 무관해
  // 결국 다 고쳐 써야 했다 · 빈 칸은 저장 전 검사가 막는다 · 수정 목록 68
  return motors.map((motor, index) => {
    const motorRef = motionMotorRef(motor);
    const motorAxis = Number(motor?.controller_index);
    const existing = preservedRows[index];
    return {
      ...(existing || defaultMotionAxisRow('', motorAxis)),
      motor_ref: motorRef,
      motor_axis: motorAxis,
    };
  });
}

export function mergeConfiguredMotionMotors(runtimeMotors = [], configuredMotors = []) {
  if (!Array.isArray(configuredMotors) || !configuredMotors.length) {
    return Array.isArray(runtimeMotors) ? runtimeMotors : [];
  }
  const runtime = Array.isArray(runtimeMotors) ? runtimeMotors : [];
  return configuredMotors.map((configured) => {
    const controllerIndex = configured?.config?.controller_index ?? configured?.axis;
    const current = runtime.find((item) => (
      Number(item?.controller_index) === Number(controllerIndex)
    )) || {};
    return {
      ...current,
      controller_index: controllerIndex,
      display_name: configured?.name || current?.display_name || '-',
      motor_type: configured?.motor_type || current?.motor_type,
      motor_type_label: configured?.motor_type_label || current?.motor_type_label,
      alias: configured?.config?.alias
        ?? configured?.identity?.ethercat_alias
        ?? current?.alias,
      ethercat_master_index: configured?.config?.ethercat_master_index
        ?? configured?.identity?.ethercat_master_index
        ?? current?.ethercat_master_index
        ?? 0,
      ethercat_alias: configured?.identity?.ethercat_alias ?? current?.ethercat_alias,
      slave_position: configured?.identity?.slave_position
        ?? configured?.config?.position
        ?? current?.slave_position,
      bus_id: configured?.identity?.bus_id
        ?? configured?.config?.bus_id
        ?? current?.bus_id,
      node_id: configured?.identity?.node_id ?? current?.node_id,
      serial_port: configured?.identity?.serial_port
        ?? configured?.config?.serial_port
        ?? current?.serial_port,
    };
  });
}

function exceedsMotorAxisAngleAlert(value) {
  const number = degValue(value);
  return number !== null && Math.abs(number) >= MOTOR_AXIS_ANGLE_ALERT_DEG;
}

function timeText(epochSeconds) {
  if (!epochSeconds) return '-';
  return new Date(epochSeconds * 1000).toLocaleString();
}

function analysisOf(file) {
  // 값은 서버 내부 단위(rad) · 화면은 deg (수정 목록 6)
  return analysisInDeg(file?.analysis);
}

function statusText(file) {
  const analysis = analysisOf(file);
  if (!analysis.format_valid) return '형식 오류';
  if (!analysis.json_valid && analysis.valid) return '호환 형식';
  return analysis.valid ? '정상' : '검사 오류';
}

function statusClass(file) {
  const analysis = analysisOf(file);
  if (!analysis.format_valid || !analysis.valid) return 'bad';
  if (Array.isArray(analysis.warnings) && analysis.warnings.length) return 'warn';
  return 'ok';
}

function emptyRow(colspan, message) {
  return `<tr><td colspan="${colspan}" class="empty">${displayText(message)}</td></tr>`;
}


function drawGraph(canvas, messageEl, analysis, hiddenIds = new Set()) {
  if (!canvas) return;
  const context = canvas.getContext('2d');
  if (!context) return;

  const width = Math.max(canvas.clientWidth || canvas.width, 320);
  const height = Math.max(canvas.clientHeight || canvas.height, 220);
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;

  context.clearRect(0, 0, width, height);
  context.fillStyle = chartTheme().bg;
  context.fillRect(0, 0, width, height);

  const allSeries = Array.isArray(analysis?.graph_series) ? analysis.graph_series : [];
  const series = allSeries
    .map((item, index) => ({ ...item, colorIndex: index }))
    .filter((item) => !hiddenIds.has(String(item.motion_id)));
  const points = series.flatMap((item) => item.points || []);
  if (!allSeries.length) {
    if (messageEl) messageEl.textContent = '그래프 데이터가 없습니다';
    context.fillStyle = chartTheme().muted;
    context.fillText('그래프 데이터 없음', 16, 28);
    return;
  }
  if (!series.length || !points.length) {
    if (messageEl) messageEl.textContent = '표시할 모터가 없습니다';
    context.fillStyle = chartTheme().muted;
    context.fillText('축 버튼을 눌러 그래프를 표시하세요', 16, 28);
    return;
  }

  const minTime = minOf(points.map((point) => Number(point.time_sec)));
  const maxTime = maxOf(points.map((point) => Number(point.time_sec)));
  const minValue = minOf(points.map((point) => Number(point.value)));
  const maxValue = maxOf(points.map((point) => Number(point.value)));
  const timeRange = Math.max(maxTime - minTime, 1e-9);
  const valueRange = Math.max(maxValue - minValue, 1e-9);
  const padLeft = 46;
  const padRight = 16;
  const padTop = 18;
  const padBottom = 34;
  const graphWidth = width - padLeft - padRight;
  const graphHeight = height - padTop - padBottom;
  const colors = CHART_SERIES_COLORS;

  context.strokeStyle = chartTheme().grid;
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(padLeft, padTop);
  context.lineTo(padLeft, padTop + graphHeight);
  context.lineTo(padLeft + graphWidth, padTop + graphHeight);
  context.stroke();

  context.fillStyle = chartTheme().muted;
  context.font = '12px Arial';
  context.fillText(`${formatNumber(maxValue, 1)} deg`, 6, padTop + 8);
  context.fillText(`${formatNumber(minValue, 1)} deg`, 6, padTop + graphHeight);
  context.fillText(`${formatNumber(minTime, 2)}s`, padLeft, height - 10);
  context.fillText(`${formatNumber(maxTime, 2)}s`, Math.max(padLeft, width - 68), height - 10);

  series.forEach((item, index) => {
    const color = colors[item.colorIndex % colors.length];
    const itemPoints = Array.isArray(item.points) ? item.points : [];
    if (!itemPoints.length) return;
    context.strokeStyle = color;
    context.lineWidth = 1.8;
    context.beginPath();
    itemPoints.forEach((point, pointIndex) => {
      const x = padLeft + (((Number(point.time_sec) - minTime) / timeRange) * graphWidth);
      const y = padTop + graphHeight - (((Number(point.value) - minValue) / valueRange) * graphHeight);
      if (pointIndex === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
    context.fillStyle = color;
    context.fillText(`ID ${item.motion_id}`, padLeft + 8 + ((index % 4) * 78), padTop + 14 + (Math.floor(index / 4) * 14));
  });

  if (messageEl) {
    messageEl.textContent = `표시 ${formatInt(series.length)}/${formatInt(allSeries.length)}`;
  }
}

/** 프로젝트가 쓰는 조인트 매핑 파일 이름 · §6-239
 *
 * 프로젝트마다 이 파일은 **하나**다 · 사람이 이름을 지을 일이 없으므로
 * 고정한다 · 이미 다른 이름으로 만들어 둔 프로젝트는 그 파일을 그대로
 * 쓴다(서버가 `active_file_id` 로 알려준다) · 이 이름은 **처음 만들 때만**
 * 쓰인다.
 *
 * **함수 안이 아니라 여기에 둔다** · 안에 두었더니 `createMotionDataController`
 * 가 도는 도중 `emptyMappingDraft()` 가 먼저 불려서 선언 전에 읽혔고,
 * 화면이 통째로 못 떴다(`Cannot access 'DEFAULT_MAPPING_NAME' before
 * initialization`) · 검사는 통과했고 **띄워 보고서야** 드러났다.
 */
const DEFAULT_MAPPING_NAME = 'motion_axis';

export function createMotionDataController({
  el,
  getLatestState = () => null,
  getConfiguredMotors = null,
  onProjectFilesChange,
  // 매핑 저장이 모터 설정 파일의 운전 한계를 바꿨을 때 · 모터 관리 화면을 다시 읽는다
  onMotorLimitsChange = null,
  // 매핑 편집 상태가 바뀌었을 때 · 맨 아래 저장 바가 다시 그린다
  onMappingStateChange = null,
  // 매핑이 저장됐을 때 · 페이더가 새 기준점·범위로 다시 읽는다
  onMappingSaved = null,
  groupRun = null,
}) {
  let files = [];
  let selectedFileId = null;
  let selectedFile = null;
  // 파일로 저장할 때 쓰는 주소가 프로젝트 번호를 요구한다 · 목록 응답이 실어 온다.
  let motionProjectId = '';
  let mappingFiles = [];
  let selectedMappingId = null;
  let mappingDraft = emptyMappingDraft();
  let registeredMotionFileIdValue = '';
  //: 재생 목록 · 1번 = `registeredMotionFileIdValue` · 수정 목록 35
  let registeredPlaylistValue = [];
  let mappingValidation = null;
  let mappingMotionFileDetail = null;
  let loading = false;
  let mappingLoading = false;
  let mappingDirty = false;
  //: 「초기 위치 이동」 결과를 지켜보는 시한 (0 = 안 봄) · 이동 시간 10 s + 확인 여유
  let initializeWatchUntil = 0;
  let initializeWatchStarted = false;
  const INITIALIZE_WATCH_MS = 30000;
  // 웹 3D 표시 · 7-a · 선택한 애니메이션을 따라간다 · 접혀 있으면 아무것도 받지 않는다
  const sim3d = createSim3dViewer({ el, getLatestState });
  // 오래 걸리는 일 표시 · 올리기 · 읽기 · 재생 등록 · 87
  const busy = createBusyIndicator({ el });
  let fileLoadToken = 0;
  let mappingLoadToken = 0;
  let mappingRevision = '';
  let mappingRevisionConflict = false;
  let activeMotionPanel = 'run';
  let motionRunStatus = null;
  let motionRunLastResult = null;
  let motionRunLoading = false;
  let motionRunGraphAnimationId = null;
  let motionRunGraphFileId = '';
  let motionRunGraphToggleSignature = '';
  const motionRunGraphHiddenIds = new Set();

  function setMessage(message) {
    if (el.motionFileMessage) {
      el.motionFileMessage.textContent = message;
      // 칸이 좁아 「…」 로 잘린다 · 마우스를 올리면 전체 · 수정 목록 55
      el.motionFileMessage.title = String(message ?? '');
    }
  }

  /** 실패는 작은 글씨만으론 놓친다 · 창으로도 띄운다 (2026-10-02) */
  function reportImportFailure(message) {
    setMessage(message);
    showAlert(message, { title: '애니메이션 불러오기', tone: 'warning' });
  }

  /** 애니메이션 .json 업로드 · 불러오기 버튼 · 드래그&드롭 (파일 · 폴더) · P5
   *
   * 길은 기존 그대로다 · `POST /api/projects/{id}/files` (JSONL 검증 포함) ·
   * 화면은 파일을 글자로 읽어 싣기만 한다 · 조인트 매핑이 없는 프로젝트는
   * 서버가 문 앞에서 거절하고, 그 사유를 그대로 보여 준다.
   *
   * `fromFolder` · 폴더째 놓으면 그 안의 .json 만 고른다 (다른 파일은 건너뛴다) ·
   * 낱개로 고른·놓은 파일에 .json 이 아닌 것이 있으면 통째로 거절한다.
   */
  async function importAnimationFiles(fileList, { fromFolder = false } = {}) {
    let picked = [...(fileList || [])];
    if (fromFolder) picked = picked.filter((file) => /\.json$/i.test(file.name || ''));
    if (!picked.length) {
      if (fromFolder) reportImportFailure('폴더 안에 .json 애니메이션이 없습니다');
      return;
    }
    // 프로젝트 번호는 애니메이션 목록 응답이 실어 온다 (내 PC로 저장과 같은 출처) ·
    // 전에는 상태 스트림에서 찾았다 · 그쪽엔 프로젝트 번호가 없어서 늘 비었다
    if (!motionProjectId) await loadFiles();
    const projectId = motionProjectId;
    if (!projectId) {
      reportImportFailure('프로젝트를 먼저 선택하세요');
      return;
    }
    const wrongType = picked.find((file) => !/\.json$/i.test(file.name || ''));
    if (wrongType) {
      reportImportFailure(`애니메이션은 .json 만 받습니다: ${wrongType.name}`);
      return;
    }
    try {
      await uploadAndRefresh(picked, projectId);
    } finally {
      busy.end('upload');
    }
  }

  async function uploadAndRefresh(picked, projectId) {
    let imported = 0;
    const uploadedNames = [];
    for (const [index, file] of picked.entries()) {
      try {
        const size = `${(Number(file.size || 0) / 1e6).toFixed(1)} MB`;
        busy.begin('upload', `올리는 중 ${index + 1}/${picked.length} · ${file.name} (${size}) · 서버가 검사하는 중`);
        const content = await file.text();
        await importProjectFile(projectId, {
          category: 'motions', file_name: file.name, content,
        });
        imported += 1;
        uploadedNames.push(file.name);
      } catch (error) {
        // 하나 실패하면 멈춘다 · 사유(중복 이름 · 조인트 매핑 없음 · 형식
        // 오류)가 다음 성공 메시지에 덮이지 않게
        reportImportFailure(
          `${file.name} 업로드 실패: ${error?.message || error}`
          + (imported ? ` · 앞의 ${imported}개는 올라갔습니다` : ''),
        );
        break;
      }
    }
    if (imported) {
      if (imported === picked.length) setMessage(`애니메이션 ${imported}개 업로드 완료`);
      busy.begin('upload', `${imported}개 올림 · 목록 다시 읽는 중 (긴 애니는 분석에 몇 초)`);
      await loadFiles();
      await onProjectFilesChange?.();
      // MuJoCo 구성(계산형)이면 올라온 것부터 바로 계산을 돌린다 · P7
      // (다시 읽은 목록에서 고른다 · 드롭한 File 에는 미리보기 상태가 없다)
      const toCompute = files.filter(
        (entry) => mujocoState(entry) === 'missing'
          && uploadedNames.includes(entry.id),
      );
      for (const entry of toCompute) {
        try {
          await precomputeMotionFile(entry.id);
        } catch { /* 사유는 MuJoCo 버튼을 누르면 다시 보인다 */ }
      }
      if (toCompute.length) {
        setMessage(`애니메이션 ${imported}개 업로드 · MuJoCo 계산 ${toCompute.length}개 시작`);
        await loadFiles();
      }
    }
  }

  /** 받는 칸 · 애니메이션 화면 전체 (목록 칸만이면 조금만 빗나가도 브라우저가 파일을 연다) */
  function bindAnimationDropZone() {
    const column = el.motionFileRows?.closest('.motion-file-column');
    const zone = el.motionFileRows?.closest('.motion-data-panel') || column;
    if (!zone) return;
    const highlight = column || zone;
    ['dragenter', 'dragover'].forEach((kind) => {
      zone.addEventListener(kind, (event) => {
        if (!draggingFiles(event)) return;
        event.preventDefault();
        highlight.classList.add('drop-active');
      });
    });
    zone.addEventListener('dragleave', (event) => {
      if (!zone.contains(event.relatedTarget)) highlight.classList.remove('drop-active');
    });
    zone.addEventListener('drop', async (event) => {
      if (!draggingFiles(event)) return;
      event.preventDefault();
      highlight.classList.remove('drop-active');
      // 항목은 await 전에 꺼낸다
      const entries = droppedEntries(event.dataTransfer);
      const files = [...(event.dataTransfer?.files || [])];
      if (!entries.some((entry) => entry.isDirectory)) {
        importAnimationFiles(files);
        return;
      }
      try {
        const nested = await Promise.all(entries.map((entry) => walkEntry(entry)));
        importAnimationFiles(nested.flat().map((item) => item.file), { fromFolder: true });
      } catch (error) {
        reportImportFailure(`폴더 읽기 실패: ${error?.message || error}`);
      }
    });
    // 불러오기 버튼 · 여러 개 한 번에
    el.motionFileImportButton?.addEventListener('click', () => el.motionFileImportInput?.click());
    el.motionFileImportInput?.addEventListener('change', () => {
      const chosen = [...(el.motionFileImportInput.files || [])];
      el.motionFileImportInput.value = '';
      importAnimationFiles(chosen);
    });
  }

  /** 조인트 매핑 안내 줄 · 할 말이 없으면 줄을 숨긴다 · 잘 읽힌 상태(파일 이름 나열)는 보이지 않는다 (2026-10-08) */
  function setMappingMessage(message) {
    if (!el.motionMappingMessage) return;
    el.motionMappingMessage.textContent = message || '';
    el.motionMappingMessage.classList.toggle('hidden', !message);
  }

  function markMappingDirty() {
    mappingDirty = true;
  }

  function isMappingRevisionConflict(message) {
    const text = String(message || '');
    return text.includes('조인트 매핑이 화면을 불러온 뒤 변경')
      || text.includes('조인트 매핑 버전 정보가 없습니다');
  }

  /** 저장된 내용이 이 화면과 달라졌을 때 사람에게 묻는다 · §6-243
   *
   * **말이 사람 말이어야 한다** · 전에는 이랬다.
   *
   *     「저장된 내용 불러오기」   ← 무엇을 잃는지 안 적혀 있다
   *     「편집 내용 유지」         ← 유지해서 어쩌라는 것인지 안 적혀 있다
   *
   * 게다가 「편집 내용 유지」는 **막다른 길**이었다 · `mappingRevisionConflict`
   * 가 참으로 남아서 저장을 다시 눌러도 같은 창만 뜨고 영영 저장되지 않았다 ·
   * 남는 길은 편집을 버리는 것뿐인데, 그걸 고르는 창이 두 갈래로 보였다.
   *
   * 이제 묻는 것은 하나다 — **지금 고친 것을 버릴 것인가.**
   */
  async function resolveMappingRevisionConflict(message) {
    mappingRevisionConflict = true;
    setMappingMessage(`저장하지 못했습니다: ${message}`);
    const reload = await showConfirm(
      '저장된 조인트 매핑이 이 화면을 연 뒤에 바뀌었습니다.\n'
      + '지금 고친 내용은 저장되지 않았습니다.\n\n'
      + '저장된 내용을 다시 불러오면 지금 고친 것은 사라집니다.',
      {
        title: '저장하지 못했습니다',
        confirmLabel: '고친 것을 버리고 다시 불러오기',
        cancelLabel: '그대로 두기',
        tone: 'warning',
      },
    );
    if (reload && selectedMappingId) {
      await selectMapping(selectedMappingId);
      return;
    }
    // 「그대로 두기」를 골라도 **다시 저장은 해볼 수 있어야 한다** · 화면에
    // 남은 편집이 유일한 사본이다 · 막아두면 사람이 손으로 옮겨 적는 수밖에
    // 없다 · 그 사이 파일이 또 바뀌었으면 이 창이 다시 뜰 뿐이다.
    mappingRevisionConflict = false;
    setMappingMessage(
      '고친 내용을 화면에 두었습니다 · 다시 저장을 누르면 한 번 더 시도합니다',
    );
    renderMappingPanel();
  }

  function mappingFileRevision(file) {
    return String(file?.mapping_revision || file?.revision || '').trim();
  }

  function syncMappingFileRevision(file) {
    if (!file || typeof file !== 'object') return false;
    const fileId = String(file.id || file.filename || '').trim();
    const revision = mappingFileRevision(file);
    if (!fileId || fileId !== selectedMappingId || !revision) return false;
    mappingRevision = revision;
    mappingFiles = mappingFiles.map((item) => (
      item?.id === fileId ? { ...item, ...file } : item
    ));
    setMappingMessage(
      mappingDirty
        ? '파일 개정을 반영했습니다 · 편집 중인 조인트 매핑은 유지됩니다'
        : '파일 개정을 반영했습니다 · 조인트 매핑을 계속 편집할 수 있습니다',
    );
    return true;
  }

  function setMotionRunMessage(message) {
    if (el.motionRunMessage) el.motionRunMessage.textContent = message;
  }

  async function showMotionRunFailure(message, title) {
    const detail = String(message || '애니메이션 재생 요청이 실패했습니다');
    const blockedByCoordination = /DDS 그룹 실행이 로컬 애니메이션 재생을 사용 중입니다/.test(detail);
    await showAlert(
      blockedByCoordination
        ? `${detail}\n\n`
          + 'PC 연동 화면에서 그룹 실행을 종료하거나 「그룹 참여」를 끈 뒤 다시 시도하세요.'
        : detail,
      {
        title: blockedByCoordination ? 'DDS 그룹 실행 중' : title,
        confirmLabel: '확인',
        tone: 'danger',
      },
    );
  }

  function emptyMappingDraft() {
    return {
      file_id: '',
      name: DEFAULT_MAPPING_NAME,
      motion_file_id: '',
      created_at: null,
      updated_at: null,
      mappings: [],
    };
  }

  function sortedRuntimeMotors() {
    const latestState = getLatestState();
    const runtimeMotors = Array.isArray(latestState?.motors) ? latestState.motors : [];
    const hasConfiguredSource = typeof getConfiguredMotors === 'function';
    const configuredValue = hasConfiguredSource ? getConfiguredMotors() : null;
    const configuredMotors = Array.isArray(configuredValue) ? configuredValue : [];
    const runtimeMatchesConfiguration = latestState?.project_scope?.runtime_matches_selected === true
      && latestState?.project_scope?.motor_config_applied === true;
    const motors = hasConfiguredSource
      ? (configuredMotors.length
        ? mergeConfiguredMotionMotors(
          runtimeMatchesConfiguration ? runtimeMotors : [],
          configuredMotors,
        )
        : [])
      : runtimeMotors;
    return motors
      .filter((motor) => Number.isFinite(Number(motor?.controller_index)))
      .sort((a, b) => Number(a.controller_index) - Number(b.controller_index));
  }

  function motorOptionLabel(motor) {
    const identity = motionMotorIdentityLabel(motor);
    return `${identity} / 현재 모터 번호 ${formatInt(motor.controller_index)} / ${motor.display_name || '-'}`;
  }

  function motorForAxis(axis) {
    if (axis === null || axis === undefined || axis === '') return null;
    return sortedRuntimeMotors().find((motor) => Number(motor.controller_index) === Number(axis)) || null;
  }

  function motorRefForMotor(motor) {
    return motionMotorRef(motor);
  }

  function motorForRef(motorRef) {
    const target = String(motorRef || '').trim().toLowerCase();
    if (!target) return null;
    const matches = sortedRuntimeMotors().filter((motor) => (
      motionMotorRefs(motor).some((ref) => ref.toLowerCase() === target)
    ));
    return matches.length === 1 ? matches[0] : null;
  }

  function motorSelectionValue(motor) {
    return motionMotorSelectionValue(motor);
  }

  function motorForSelectionValue(value) {
    const selection = String(value || '').trim();
    const axisMatch = /^axis:(\d+)$/.exec(selection.toLowerCase());
    return axisMatch ? motorForAxis(Number(axisMatch[1])) : motorForRef(selection);
  }

  function motorForMapping(row) {
    const byRef = motorForRef(row?.motor_ref);
    return byRef || (!row?.motor_ref ? motorForAxis(row?.motor_axis) : null);
  }

  function mappingTargetKey(row) {
    return motionMappingTargetKey(row);
  }

  function upgradeLegacyMappingRefs() {
    const rows = Array.isArray(mappingDraft.mappings) ? mappingDraft.mappings : [];
    rows.forEach((row) => {
      if (String(row.motor_ref || '').trim().toLowerCase() === 'ac_servo:alias:0') {
        row.motor_ref = '';
      }
      const current = motorForRef(row.motor_ref);
      if (current) {
        row.motor_axis = Number(current.controller_index);
        row.motor_ref = motorRefForMotor(current);
        return;
      }
      if (String(row.motor_ref || '').trim()) return;
      const motor = motorForAxis(row.motor_axis);
      const motorRef = motorRefForMotor(motor);
      if (motorRef) row.motor_ref = motorRef;
    });
  }

  function motorLimitInfo(row, detail) {
    const motor = motorForMapping(row);
    if (!motor) {
      return { className: 'warn', rangeText: '리미트 확인 불가' };
    }
    const lower = degValue(motor.lower);
    const upper = degValue(motor.upper);
    if (lower === null && upper === null) {
      return { className: 'warn', rangeText: '리미트 정보 없음' };
    }
    const targetMin = degValue(detail.motion_motor_target_min_deg);
    const targetMax = degValue(detail.motion_motor_target_max_deg);
    if (targetMin === null || targetMax === null) {
      return { className: 'warn', rangeText: limitRangeText(lower, upper) };
    }
    const below = lower !== null && targetMin < lower;
    const above = upper !== null && targetMax > upper;
    if (below || above) {
      return { className: 'bad', rangeText: limitRangeText(lower, upper) };
    }
    return { className: 'ok', rangeText: limitRangeText(lower, upper) };
  }

  function limitRangeText(lower, upper) {
    const lowerText = lower === null ? '-∞' : targetText(lower);
    const upperText = upper === null ? '+∞' : targetText(upper);
    return `${lowerText} ~ ${upperText}`;
  }

  function isDynamixelMotor(motor) {
    return normalizeMotorTypeKey(motor?.motor_type, motor?.motor_type_label) === 'dynamixel';
  }


  function firstMotionValueFor(motionId) {
    const motionIds = Array.isArray(analysisOf(mappingMotionFileDetail)?.motion_ids)
      ? analysisOf(mappingMotionFileDetail).motion_ids
      : [];
    const found = motionIds.find((item) => String(item.motion_id) === String(motionId));
    const value = Number(found?.first_value);
    return Number.isFinite(value) ? value : null;
  }

  function displayInitialPosition(row) {
    if ((row.initial_mode || 'reference') === 'reference') return 0.0;
    if (row.initial_mode !== 'first_frame') {
      return numericOr(row.initial_motion_position_deg, 0.0);
    }
    const firstValue = firstMotionValueFor(row.motion_id);
    return firstValue === null ? numericOr(row.initial_motion_position_deg, 0.0) : firstValue;
  }

  function displayReferencePosition(row) {
    return numericOr(row.reference_position_deg, 0.0);
  }

  function motorPositionDeg(motor) {
    const candidates = [
      motor?.position_deg,
      motor?.position_actual_deg,
      motor?.output_position_deg,
      motor?.present_position_deg,
      motor?.position_actual,
    ];
    for (const value of candidates) {
      const number = Number(value);
      if (Number.isFinite(number)) return number;
    }
    return null;
  }

  function selectedMappingFile() {
    return mappingFiles.find((file) => file.id === selectedMappingId) || null;
  }

  function motionRunPayload() {
    const initialMoveTimeSec = motionRunInitialMoveTimeSec();
    const repeatMode = String(el.motionAutomationRepeatMode?.value || 'reinitialize');
    const dwellSec = Number(el.motionAutomationDwellSec?.value);
    const targetCycleCount = Math.max(0, parseInt(el.motionRunTargetCycle?.value || '0', 10));
    return {
      motion_file_id: registeredMotionFileId({ motion_file_id: registeredMotionFileIdValue }),
      mapping_file_id: selectedMappingId || '',
      initial_move_time_sec: initialMoveTimeSec,
      run_mode: 'once',
      repeat_mode: repeatMode,
      dwell_sec: Number.isFinite(dwellSec) ? dwellSec : 0.0,
      target_cycle_count: Number.isFinite(targetCycleCount) ? targetCycleCount : 0,
    };
  }

  function motionRunInitialMoveTimeSec() {
    const rawValue = String(el.motionRunInitialMoveTime?.value || 'mapping');
    if (rawValue === 'mapping') return null;
    const value = Number(rawValue);
    return [5, 7, 10].includes(value) ? value : 5;
  }

  function motionRunSelectedMotionFile() {
    const fileId = motionRunPayload().motion_file_id;
    if (mappingMotionFileDetail?.id === fileId) return mappingMotionFileDetail;
    if (selectedFile?.id === fileId) return selectedFile;
    return files.find((file) => file.id === fileId) || null;
  }

  async function ensureMotionRunMotionFileDetail() {
    const fileId = motionRunPayload().motion_file_id;
    if (!fileId) return null;
    return ensureMappingMotionFileDetail(fileId);
  }

  function motionRunStateText(state) {
    const key = String(state || 'idle');
    const labels = {
      idle: '재생 전',
      ready: '실행 준비 완료',
      initializing: '초기 위치 이동 중',
      initialized: '초기 위치 완료',
      running: '재생 중',
      waiting: '반복 대기 중',
      verifying: '위치 확인 중',
      // 연속 재생 가벼운 오류 · 제자리에서 기다렸다 초기 위치부터 다시 · 수정 목록 73
      recovering: '자동 복구 대기',
      stopping: '정지 중',
      stopped: '정지',
      completed: '재생 완료',
      error: '오류',
    };
    return labels[key] || key;
  }

  function motionRunStateClass(state) {
    const key = String(state || 'idle');
    if (key === 'error') return 'bad';
    if (
      key === 'running'
      || key === 'waiting'
      || key === 'initializing'
      || key === 'verifying'
      || key === 'stopping'
      || key === 'recovering'
    ) return 'warn';
    if (key === 'ready' || key === 'initialized' || key === 'completed') return 'ok';
    return 'warn';
  }

  function motionRunStageKey(status) {
    const state = String(status?.state || 'idle');
    if (
      state === 'waiting'
      || state === 'stopping'
      || state === 'stopped'
      || state === 'error'
    ) return state;
    if (MOTION_RUN_STAGES.some((stage) => stage.key === state)) return state;
    return 'idle';
  }

  function motionRunStageIndex(key) {
    return MOTION_RUN_STAGES.findIndex((stage) => stage.key === key);
  }

  function motionRunEffectiveProgress(status = motionRunStatus || {}) {
    return effectiveMotionRunProgress(status, {
      initialMoveTimeSec: motionRunInitialMoveTimeSec(),
    });
  }

  function renderMotionRunStages() {
    if (!el.motionRunStageStrip) return;
    const status = motionRunStatus || {};
    const currentKey = motionRunStageKey(status);
    const currentIndex = motionRunStageIndex(currentKey);
    const stageHtml = MOTION_RUN_STAGES.map((stage, index) => {
      let className = 'motion-run-stage';
      if (currentIndex >= 0 && index < currentIndex) className += ' done';
      if (stage.key === currentKey) className += ' active';
      const label = stage.key === currentKey ? `현재: ${stage.label}` : stage.label;
      return `<span class="${className}">${displayText(label)}</span>`;
    }).join('');
    const extraState = (
      currentKey === 'waiting'
      || currentKey === 'stopping'
      || currentKey === 'stopped'
      || currentKey === 'error'
    )
      ? `<span class="motion-run-stage ${motionRunStateClass(currentKey)} active">${displayText(`현재: ${motionRunStateText(currentKey)}`)}</span>`
      : '';
    el.motionRunStageStrip.innerHTML = `${stageHtml}${extraState}`;
  }

  function motionRunProgressRatio(status = motionRunStatus || {}) {
    const state = String(status?.state || 'idle');
    if (state === 'completed' || state === 'initialized') return 1.0;
    if (state === 'ready' || state === 'idle') return 0.0;
    return motionRunEffectiveProgress(status).ratio;
  }

  function motionRunProgressText(status = motionRunStatus || {}) {
    const state = String(status?.state || 'idle');
    const progress = motionRunEffectiveProgress(status);
    const targetCycle = Number(status?.summary?.target_cycle_count) || 0;
    const currentCycle = Number(status?.current_cycle) || 0;
    const cycleText = targetCycle > 0 
      ? ` [${formatInt(currentCycle)} / ${formatInt(targetCycle)}회차]` 
      : (currentCycle > 0 ? ` [${formatInt(currentCycle)}회차]` : '');
    
    // 재생 목록이면 몇 번째인지 · 다음은 무엇인지 · 수정 목록 35
    const playlistText = playlistProgressText(status);
    const listText = playlistText ? ` · ${playlistText}` : '';
    if (state === 'initializing') {
      return `초기 위치 이동 ${formatNumber(progress.elapsed_sec, 2)} / ${formatNumber(progress.duration_sec, 2)} s${cycleText}${listText}`;
    }
    if (state === 'running' || state === 'stopping') {
      return `재생 진행 ${formatNumber(progress.elapsed_sec, 2)} / ${formatNumber(progress.duration_sec, 2)} s${cycleText}${listText}`;
    }
    if (state === 'waiting') return String(status?.message || '반복 대기 중');
    if (state === 'verifying') return '최종 위치 확인 중';
    if (state === 'initialized') return '초기 위치 이동 완료';
    if (state === 'completed') return `재생 완료 ${formatNumber(progress.duration_sec, 2)} s`;
    if (state === 'ready') return '실행 준비 완료';
    if (state === 'stopped') return '정지됨';
    if (state === 'error') return '오류';
    return '재생 전';
  }

  function renderMotionRunProgressBar() {
    const status = motionRunStatus || {};
    const state = String(status.state || 'idle');
    const ratio = motionRunProgressRatio(status);
    const percent = Math.min(Math.max(ratio, 0.0), 1.0) * 100;
    if (el.motionRunCurrentPhase) {
      el.motionRunCurrentPhase.textContent = `현재 단계: ${motionRunStateText(state)}`;
    }
    if (el.motionRunProgressText) {
      el.motionRunProgressText.textContent = `${motionRunProgressText(status)} · ${formatNumber(percent, 1)} %`;
    }
    if (el.motionRunProgressFill) {
      el.motionRunProgressFill.className = `motion-run-progress-fill ${state}`;
      el.motionRunProgressFill.style.width = `${percent}%`;
    }
  }

  function drawMotionRunGraph(canvas, messageEl, file, status = {}, hiddenIds = new Set()) {
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const width = Math.max(canvas.clientWidth || canvas.width, 360);
    const height = Math.max(canvas.clientHeight || canvas.height, 240);
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;

    context.clearRect(0, 0, width, height);
    context.fillStyle = chartTheme().bg;
    context.fillRect(0, 0, width, height);

    const analysis = analysisOf(file);
    const allSeries = Array.isArray(analysis?.graph_series) ? analysis.graph_series : [];
    const series = allSeries
      .map((item, index) => ({ ...item, colorIndex: index }))
      .filter((item) => !hiddenIds.has(String(item.motion_id)));
    const points = series.flatMap((item) => item.points || []);
    if (!allSeries.length) {
      if (messageEl) messageEl.textContent = '재생 그래프 데이터가 없습니다';
      context.fillStyle = chartTheme().muted;
      context.font = '13px Arial';
      context.fillText('재생 그래프 데이터 없음', 16, 28);
      return;
    }
    if (!series.length || !points.length) {
      if (messageEl) messageEl.textContent = '표시할 모터가 없습니다';
      context.fillStyle = chartTheme().muted;
      context.font = '13px Arial';
      context.fillText('축 버튼을 눌러 그래프를 표시하세요', 16, 28);
      return;
    }

    const minTime = minOf(points.map((point) => Number(point.time_sec)));
    const maxTime = maxOf(points.map((point) => Number(point.time_sec)));
    const minValue = minOf(points.map((point) => Number(point.value)));
    const maxValue = maxOf(points.map((point) => Number(point.value)));
    const timeRange = Math.max(maxTime - minTime, 1e-9);
    const valueRange = Math.max(maxValue - minValue, 1e-9);
    const padLeft = 54;
    const padRight = 18;
    const padTop = 20;
    const padBottom = 38;
    const graphWidth = width - padLeft - padRight;
    const graphHeight = height - padTop - padBottom;
    const colors = CHART_SERIES_COLORS;

    context.strokeStyle = chartTheme().grid;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(padLeft, padTop);
    context.lineTo(padLeft, padTop + graphHeight);
    context.lineTo(padLeft + graphWidth, padTop + graphHeight);
    context.stroke();

    context.fillStyle = chartTheme().muted;
    context.font = '12px Arial';
    context.fillText(`${formatNumber(maxValue, 1)} deg`, 6, padTop + 8);
    context.fillText(`${formatNumber(minValue, 1)} deg`, 6, padTop + graphHeight);
    context.fillText(`${formatNumber(minTime, 2)}s`, padLeft, height - 10);
    context.fillText(`${formatNumber(maxTime, 2)}s`, Math.max(padLeft, width - 70), height - 10);

    series.forEach((item, index) => {
      const color = colors[item.colorIndex % colors.length];
      const itemPoints = Array.isArray(item.points) ? item.points : [];
      if (!itemPoints.length) return;
      context.strokeStyle = color;
      context.lineWidth = 1.8;
      context.beginPath();
      itemPoints.forEach((point, pointIndex) => {
        const x = padLeft + (((Number(point.time_sec) - minTime) / timeRange) * graphWidth);
        const y = padTop + graphHeight - (((Number(point.value) - minValue) / valueRange) * graphHeight);
        if (pointIndex === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      context.stroke();
      context.fillStyle = color;
      context.fillText(`ID ${item.motion_id}`, padLeft + 8 + ((index % 5) * 82), padTop + 14 + (Math.floor(index / 5) * 14));
    });

    const state = String(status?.state || 'idle');
    const effective = motionRunEffectiveProgress(status);
    let cursorTime = minTime;
    if (
      state === 'running'
      || state === 'waiting'
      || state === 'verifying'
      || state === 'completed'
    ) {
      cursorTime = Math.min(Math.max(effective.elapsed_sec, minTime), maxTime);
    } else if (state === 'initialized') {
      cursorTime = minTime;
    }
    const cursorX = padLeft + (((cursorTime - minTime) / timeRange) * graphWidth);
    context.strokeStyle = state === 'running' ? chartTheme().ink : chartTheme().faint;
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(cursorX, padTop);
    context.lineTo(cursorX, padTop + graphHeight);
    context.stroke();

    context.fillStyle = state === 'running' ? chartTheme().ink : chartTheme().faint;
    context.font = '12px Arial';
    const cursorLabel = (
      state === 'running'
      || state === 'waiting'
      || state === 'verifying'
      || state === 'completed'
    )
      ? `${formatNumber(cursorTime, 2)}s`
      : motionRunStateText(state);
    context.fillText(cursorLabel, Math.min(cursorX + 6, width - 80), padTop + graphHeight - 8);

    if (messageEl) {
      const visibleText = `표시 ${series.length}/${allSeries.length}`;
      if (state === 'initializing') {
        messageEl.textContent = `초기 위치 이동 중 ${formatNumber(effective.elapsed_sec, 2)} / ${formatNumber(effective.duration_sec, 2)} s · ${visibleText}`;
      } else if (state === 'running') {
        messageEl.textContent = `재생 중 ${formatNumber(effective.elapsed_sec, 2)} / ${formatNumber(effective.duration_sec, 2)} s · ${visibleText}`;
      } else if (state === 'waiting') {
        messageEl.textContent = `${String(status?.message || '반복 대기 중')} · ${visibleText}`;
      } else if (state === 'verifying') {
        messageEl.textContent = `최종 위치 확인 중 · ${visibleText}`;
      } else if (state === 'completed') {
        messageEl.textContent = `재생 완료 ${formatNumber(effective.duration_sec, 2)} s · ${visibleText}`;
      } else {
        messageEl.textContent = visibleText;
      }
    }
  }

  function renderMotionRunGraph() {
    drawMotionRunGraph(
      el.motionRunGraphCanvas,
      el.motionRunGraphMessage,
      motionRunSelectedMotionFile(),
      motionRunStatus || {},
      motionRunGraphHiddenIds,
    );
  }

  function renderMotionRunGraphAxisToggles() {
    if (!el.motionRunGraphAxisToggles) return;
    const file = motionRunSelectedMotionFile();
    const fileId = String(motionRunPayload().motion_file_id || file?.id || '');
    if (fileId !== motionRunGraphFileId) {
      motionRunGraphFileId = fileId;
      motionRunGraphToggleSignature = '';
      motionRunGraphHiddenIds.clear();
    }
    const series = Array.isArray(analysisOf(file)?.graph_series)
      ? analysisOf(file).graph_series
      : [];
    if (!series.length) {
      if (motionRunGraphToggleSignature !== `${fileId}|empty`) {
        el.motionRunGraphAxisToggles.innerHTML = '';
        motionRunGraphToggleSignature = `${fileId}|empty`;
      }
      return;
    }
    const allVisible = series.every((item) => !motionRunGraphHiddenIds.has(String(item.motion_id)));
    const noneVisible = series.every((item) => motionRunGraphHiddenIds.has(String(item.motion_id)));
    const allStateText = allVisible ? '표시' : (noneVisible ? '숨김' : '일부');
    const signature = `${fileId}|${series.map((item) => {
      const motionId = String(item.motion_id);
      return `${motionId}:${motionRunGraphHiddenIds.has(motionId) ? '0' : '1'}`;
    }).join(',')}`;
    if (signature === motionRunGraphToggleSignature) return;
    const allButton = `<button type="button" class="motion-run-graph-toggle ${allVisible ? 'active' : ''}" data-motion-run-graph-all="true" aria-pressed="${allVisible}">전체 · ${allStateText}</button>`;
    const axisButtons = series.map((item) => {
      const motionId = String(item.motion_id);
      const visible = !motionRunGraphHiddenIds.has(motionId);
      return `<button type="button" class="motion-run-graph-toggle ${visible ? 'active' : ''}" data-motion-run-graph-id="${displayText(motionId)}" aria-pressed="${visible}">${displayText(motionId)} · ${visible ? '표시' : '숨김'}</button>`;
    }).join('');
    el.motionRunGraphAxisToggles.innerHTML = `${allButton}${axisButtons}`;
    motionRunGraphToggleSignature = signature;
  }

  function motionRunNeedsGraphAnimation() {
    const state = String(motionRunStatus?.state || 'idle');
    return state === 'initializing' || state === 'running' || state === 'verifying';
  }

  function updateMotionRunGraphAnimation() {
    if (motionRunGraphAnimationId !== null || !motionRunNeedsGraphAnimation()) return;
    const step = () => {
      motionRunGraphAnimationId = null;
      renderMotionRunProgressBar();
      renderMotionRunGraph();
      if (motionRunNeedsGraphAnimation()) {
        motionRunGraphAnimationId = window.requestAnimationFrame(step);
      }
    };
    motionRunGraphAnimationId = window.requestAnimationFrame(step);
  }

  function stopMotionRunGraphAnimationIfIdle() {
    if (motionRunNeedsGraphAnimation() || motionRunGraphAnimationId === null) return;
    window.cancelAnimationFrame(motionRunGraphAnimationId);
    motionRunGraphAnimationId = null;
  }

  function renderMotionRunSummary() {
    if (!el.motionRunSummary) return;
    const payload = motionRunPayload();
    const runFile = motionRunSelectedMotionFile();
    const mappingFile = selectedMappingFile();
    const status = motionRunStatus || {};
    const summary = status.summary || motionRunLastResult?.summary || {};
    const mismatch = selectedFileId
      && mappingDraft.motion_file_id
      && selectedFileId !== mappingDraft.motion_file_id;
    // 아홉 칸을 같은 크기로 늘어놓으면 정작 알아야 할 "무엇이 재생되는가"가
    // 묻힌다. 실행 대상 셋을 크게 두고, 나머지 수치는 아래에 작게 붙인다.
    const targets = [
      {
        label: registeredPlaylistValue.length > 1 ? '재생 목록' : '재생 파일',
        value: registeredPlaylistValue.length > 1
          ? `${registeredPlaylistValue.length}개 · ${registeredPlaylistValue.join(' → ')}`
          : (runFile?.filename || payload.motion_file_id || '등록된 파일 없음'),
        missing: !runFile && !payload.motion_file_id,
      },
      { label: '조인트 매핑', value: mappingFile?.filename || payload.mapping_file_id || '선택 안 됨', missing: !mappingFile && !payload.mapping_file_id },
      { label: '상태', value: motionRunStateText(status.state) },
    ].map((item) => (
      `<div class="motion-run-target-item${item.missing ? ' missing' : ''}">`
      + `<span>${displayText(item.label)}</span>`
      + `<strong title="${displayText(item.value)}">${displayText(item.value)}</strong>`
      + '</div>'
    )).join('');

    const metrics = [
      {
        label: '초기 이동',
        value: payload.initial_move_time_sec === null
          ? '매핑 모터별 설정'
          : `${formatNumber(payload.initial_move_time_sec, 0)} s 일괄`,
      },
      { label: '실행 축', value: formatInt(summary.axis_count) },
      { label: '총 시간', value: `${formatNumber(summary.duration_sec, 3)} s` },
      {
        label: '연속 동작',
        value: typeof summary.continuous_available === 'boolean'
          ? (summary.continuous_available ? '가능' : '불가')
          : '검사 전',
      },
      { label: '주기', value: `${formatNumber(summary.period_sec, 3)} s` },
    ].map((item) => (
      `<div class="motion-run-metric"><span>${displayText(item.label)}</span>`
      + `<strong>${displayText(item.value)}</strong></div>`
    )).join('');

    // 고른 파일과 등록된 파일이 다르면 실행 결과가 어긋난다 · 그 자리에서 알린다.
    const notice = mismatch
      ? '<div class="motion-run-notice">선택한 파일은 재생 등록되어 있지 않습니다 ·'
        + ' 재생 등록된 파일 기준으로 실행됩니다</div>'
      : '';

    el.motionRunSummary.innerHTML =
      `<div class="motion-run-targets">${targets}</div>`
      + `<div class="motion-run-metrics">${metrics}</div>`
      + notice;
  }

  function renderMotionRunStatus() {
    if (!el.motionRunStatus) return;
    const status = motionRunStatus || {};
    const progress = motionRunEffectiveProgress(status);
    const capabilities = status.capabilities || {};
    const warnings = Array.isArray(status.warnings) ? status.warnings : [];
    const ratio = Number(progress.ratio);
    const repeatMode = String(el.motionAutomationRepeatMode?.value || 'reinitialize');
    const continuousText = (() => {
      const cap = capabilities.continuous_run;
      if (!cap || typeof cap.available !== 'boolean') return '검사 전';
      if (cap.available === false && (repeatMode === 'reinitialize' || repeatMode === 'dwell_reinitialize')) {
        return '가능 — 초기 위치 이동 설정으로 안전 가드 통과';
      }
      return `${cap.available ? '가능' : '불가'} — ${cap.reason || '-'}`;
    })();
    const capabilityText = (capability) => {
      if (!capability || typeof capability.available !== 'boolean') return '검사 전';
      return `${capability.available ? '가능' : '불가'} — ${capability.reason || '-'}`;
    };
    el.motionRunStatus.innerHTML = `
      <table class="motion-state-table motion-run-status-table">
        <tbody>
          <tr>
            <th>상태</th><td>${displayText(motionRunStateText(status.state))}</td>
            <th>모드 / 완료</th><td>${displayText(`${status.run_mode === 'continuous' ? '연속' : '1회'} / ${formatInt(status.cycle_count)}회`)}</td>
          </tr>
          <tr>
            <th>진행</th><td>${displayText(Number.isFinite(ratio) ? `${formatNumber(ratio * 100, 1)} %` : '-')}</td>
            <th>경과 / 전체</th><td>${displayText(`${formatNumber(progress.elapsed_sec, 2)} / ${formatNumber(progress.duration_sec, 2)} s`)}</td>
          </tr>
          <!-- 두 쌍씩 채워 다섯 줄로 · §6-100 · 한 쌍만 쓰고 가로를 비워 두면
               실행 화면에서 상태표가 그래프보다 높이를 더 먹는다 -->
          <tr>
            <th>초기 위치</th><td>${displayText(capabilityText(capabilities.initial_position))}</td>
            <th>1회 재생</th><td>${displayText(capabilityText(capabilities.single_run))}</td>
          </tr>
          <tr>
            <th>연속 재생</th><td>${displayText(continuousText)}</td>
            <th>범위 제한</th><td>${displayText(warnings.length ? warnings.join(' / ') : '제한 적용 없음')}</td>
          </tr>
          <tr>
            <th>메시지</th><td>${displayText(status.message || '-')}</td>
            <th>갱신</th><td>${displayText(timeText(status.updated_at))}</td>
          </tr>
        </tbody>
      </table>
    `;
  }

  /** 이 조인트의 라이브 오버라이드 · 없으면 빈 객체 */
  function liveOverrideOf(motionId) {
    const overrides = motionRunStatus?.live_overrides;
    const entry = overrides && typeof overrides === 'object'
      ? overrides[String(motionId)]
      : null;
    return entry && typeof entry === 'object' ? entry : {};
  }

  function renderMotionRunAxes() {
    if (!el.motionRunAxisRows) return;
    // 재생 중 상태가 계속 들어온다 · 입력 중인 칸을 덮어쓰지 않는다
    if (el.motionRunAxisRows.contains(document.activeElement)) return;
    const axes = Array.isArray(motionRunStatus?.axes) ? motionRunStatus.axes : [];
    if (!axes.length) {
      el.motionRunAxisRows.innerHTML = emptyRow(12, '실행 준비 검사를 누르면 표시됩니다');
      return;
    }
    el.motionRunAxisRows.innerHTML = axes.map((axis) => {
      const muted = Boolean(liveOverrideOf(axis.motion_id).muted);
      return `<tr class="${muted ? 'live-muted' : ''}">
        <td><label class="live-mute-cell"><input type="checkbox" data-live-mute="${escapeHtml(axis.motion_id)}"
          title="즉시 적용 · 끄면 이 조인트 명령을 빼고 모터는 그 자리에 섭니다 (서보 유지) · 다시 켜면 초기 이동 시간 동안 천천히 이어 갑니다 · 저장 안 됨"
          ${muted ? '' : 'checked'}>${muted ? '<span class="live-muted-badge">제외 중</span>' : ''}</label></td>
        <td class="mono">${displayText(axis.motion_id)}</td>
        <td class="mono">${formatInt(axis.motor_axis)}</td>
        <td>${displayText(axis.motor_type || '-')}</td>
        <td>${targetText(axis.motion_limit_lower_deg)}</td>
        <td>${targetText(axis.motion_limit_upper_deg)}</td>
        <td>${targetText(axis.initial_motor_target_deg)}</td>
        <td>${targetText(axis.target_min_deg)} ~ ${targetText(axis.target_max_deg)}</td>
        <td>${targetText(axis.loop_start_motion_deg)} / ${targetText(axis.loop_end_motion_deg)}</td>
        <td>${Number(axis.loop_delta_deg) <= Number(axis.loop_tolerance_deg)
          ? `가능 (차이 ${targetText(axis.loop_delta_deg)})`
          : `불가 (차이 ${targetText(axis.loop_delta_deg)}, 허용 ${targetText(axis.loop_tolerance_deg)})`}</td>
        <td>${axis.motion_clamped
          ? `${targetText(axis.source_motion_min_deg)} ~ ${targetText(axis.source_motion_max_deg)} → ${targetText(axis.command_motion_min_deg)} ~ ${targetText(axis.command_motion_max_deg)}`
          : '제한 없음'}</td>
        <td class="live-clamp-cell" title="재생 값을 이 범위로 산 채로 자릅니다 · 빈 칸이면 매핑 리밋 그대로 · 매핑 파일은 안 바뀝니다">
          <input class="numeric-input live-clamp-input" type="number" step="0.1"
            data-live-clamp="${escapeHtml(axis.motion_id)}" data-live-clamp-side="lo"
            value="${liveOverrideOf(axis.motion_id).clamp ? liveOverrideOf(axis.motion_id).clamp[0] : ''}"
            placeholder="${targetText(axis.motion_limit_lower_deg)}">
          ~
          <input class="numeric-input live-clamp-input" type="number" step="0.1"
            data-live-clamp="${escapeHtml(axis.motion_id)}" data-live-clamp-side="hi"
            value="${liveOverrideOf(axis.motion_id).clamp ? liveOverrideOf(axis.motion_id).clamp[1] : ''}"
            placeholder="${targetText(axis.motion_limit_upper_deg)}">
        </td>
      </tr>`;
    }).join('');
  }

  /** 사용 토글·라이브 리밋 변경 → 즉시 런타임에 반영 · 다음 20ms 틱부터 · P7 */
  async function handleLiveOverrideEdit(target) {
    const muteId = target?.dataset?.liveMute;
    const clampId = target?.dataset?.liveClamp;
    if (muteId === undefined && clampId === undefined) return;
    const motionId = muteId !== undefined ? muteId : clampId;
    const payload = { motion_id: motionId };
    if (muteId !== undefined) {
      payload.muted = !target.checked;
    } else {
      const inputs = el.motionRunAxisRows.querySelectorAll(
        `[data-live-clamp="${CSS.escape(motionId)}"]`,
      );
      const values = {};
      inputs.forEach((input) => {
        values[input.dataset.liveClampSide] = String(input.value ?? '').trim();
      });
      if (!values.lo && !values.hi) {
        payload.clamp = null;
      } else {
        const axis = (motionRunStatus?.axes || []).find(
          (row) => String(row.motion_id) === motionId,
        );
        const low = values.lo === '' ? Number(axis?.motion_limit_lower_deg) : Number(values.lo);
        const high = values.hi === '' ? Number(axis?.motion_limit_upper_deg) : Number(values.hi);
        if (!Number.isFinite(low) || !Number.isFinite(high) || low > high) {
          setMotionRunMessage('라이브 리밋은 최소 ≤ 최대 인 숫자여야 합니다');
          renderMotionRunAxes();
          return;
        }
        payload.clamp = [low, high];
      }
    }
    try {
      const result = await setMotionRunLiveOverride(payload);
      if (motionRunStatus && typeof motionRunStatus === 'object') {
        motionRunStatus.live_overrides = result?.live_overrides || {};
      }
      setMotionRunMessage(payload.muted !== undefined
        ? (payload.muted
          ? `조인트 이름 ${motionId} 제외 · 모터는 그 자리에 섭니다`
          : `조인트 이름 ${motionId} 다시 사용 · 초기 이동 시간 동안 천천히 이어 갑니다`)
        : (payload.clamp
          ? `조인트 이름 ${motionId} 라이브 리밋 ${payload.clamp[0]} ~ ${payload.clamp[1]}°`
          : `조인트 이름 ${motionId} 라이브 리밋 해제`));
    } catch (error) {
      setMotionRunMessage(`라이브 오버라이드 실패: ${error?.message || error}`);
    }
    renderMotionRunAxes();
  }


  /** 한 회차가 끝나면 어떻게 잇는가 · 바로 · 대기 후 · 초기 위치 이동 후
   *
   * 부팅 때 스스로 시작하는 기능은 뺐다 · §6-134 · 여기 남은 것은 **반복
   * 방식**뿐이고, 스케줄도 이 값을 읽어 그대로 실어 보낸다.
   */
  function renderMotionAutomation() {
    const automation = motionRunStatus?.automation || {};
    // 안 적었으면 「초기 위치 이동 후 다음」이다 · §6-135 · 선택칸의
    // 기본값(`selected`)과 같아야 한다 · 전에는 여기만 `direct` 라서
    // 화면에 골라진 것과 실제로 나가는 값이 달랐다
    const repeatMode = String(automation.repeat_mode || 'reinitialize');
    const dwellSec = Number(automation.dwell_sec);
    const busy = motionRunLoading;

    // **저장된 값을 선택칸에 넣는다** · §6-268
    //
    // 전에는 `repeatMode` 를 읽어 놓고 선택칸에 넣지 않았다 · 그래서 화면은
    // 언제나 HTML 의 기본값(`초기 위치 이동 후 다음`)을 보여 줬고, 파일에
    // `바로 다음 모션` 이 적혀 있어도 그대로였다.
    //
    // 더 나쁜 것은 그다음이다 · 사람이 다른 값을 고르면 **화면에 보이던
    // 잘못된 값이 그대로 파일에 덮어써졌다** · 저장해 둔 설정이 화면을 한 번
    // 열었다는 이유로 바뀌었다.
    //
    // 사람이 그 칸을 만지는 중이면 건드리지 않는다 · 고르는 도중에 값이
    // 바뀌면 손이 미끄러진 것처럼 보인다.
    if (el.motionAutomationRepeatMode) {
      el.motionAutomationRepeatMode.disabled = busy;
      if (document.activeElement !== el.motionAutomationRepeatMode
        && el.motionAutomationRepeatMode.value !== repeatMode) {
        el.motionAutomationRepeatMode.value = repeatMode;
      }
    }
    const currentRepeatMode = el.motionAutomationRepeatMode?.value || repeatMode;
    const showDwell = currentRepeatMode === 'dwell' || currentRepeatMode === 'dwell_reinitialize';
    el.motionAutomationDwellWrap?.classList.toggle('hidden', !showDwell);
    if (el.motionAutomationDwellSec) {
      el.motionAutomationDwellSec.disabled = busy;
      if (document.activeElement !== el.motionAutomationDwellSec
        && Number.isFinite(dwellSec)
        && Number(el.motionAutomationDwellSec.value) !== dwellSec) {
        el.motionAutomationDwellSec.value = String(dwellSec);
      }
    }
    if (el.motionAutomationDetail) {
      const fileName = motionRunSelectedMotionFile()?.filename
        || automation.motion_file_id
        || '재생 등록 파일 없음';
      el.motionAutomationDetail.textContent = automation.message
        || `${fileName} · ${repeatMode === 'direct'
          ? '바로 반복'
          : repeatMode === 'dwell'
            ? `${Number.isFinite(dwellSec) ? dwellSec : 0}초 정지 후 반복`
            : '초기 위치 이동 후 반복'}`;
    }
  }


  function renderMotionRunPanel() {
    // 3D 보기 「실물과 같이」(기본 켬 · 86) 가 따라갈 파일
    // 재생 목록이면 **지금 도는(또는 다음으로 가는) 애니**를 따라간다 · 수정 목록 35 ·
    // 초기 위치 이동 중에 이미 다음 파일 이름이 오므로 프레임을 미리 받아 둔다
    const playingId = Number(motionRunStatus?.playlist_length) > 1
      ? String(motionRunStatus?.motion_file_id || '')
      : '';
    const followTarget = files.find(
      (entry) => entry.id === (playingId || registeredMotionFileIdValue),
    ) || null;
    sim3d.update({ file: selectedFile, registeredFile: followTarget });
    const payload = motionRunPayload();
    const status = motionRunStatus || {};
    const state = String(status.state || 'idle');
    // 자동 복구 대기도 도는 중 · 정지 버튼이 살아 있어야 한다 · 73
    const running = state === 'running' || state === 'initializing'
      || state === 'verifying' || state === 'stopping' || state === 'waiting'
      || state === 'recovering';
    const hasMappingFile = Boolean(payload.mapping_file_id);
    const hasMotionFile = Boolean(payload.motion_file_id);
    const hasRequiredFiles = hasMappingFile && hasMotionFile;
    const context = getLatestState()?.execution_context || {};
    const contextReady = context.ready === true;
    const contextMessage = context.message || '현재 프로젝트 실행 설정 적용 대기 중입니다';
    const statusMatchesFiles = status.motion_file_id === payload.motion_file_id
      && status.mapping_file_id === payload.mapping_file_id;
    const continuousCapability = statusMatchesFiles
      ? status.capabilities?.continuous_run
      : null;
    const continuousUnavailable = (() => {
      if (continuousCapability?.available !== false) return false;
      const repeatMode = String(el.motionAutomationRepeatMode?.value || 'reinitialize');
      if (repeatMode === 'reinitialize' || repeatMode === 'dwell_reinitialize') return false;
      return true;
    })();
    // 범위에 따라 판정하는 규칙이 다르다 · 로컬은 실행 설정과 파일, 그룹은
    // 연동 상태(참가·통신·알람)가 정한다. 버튼은 한 벌이고 판정만 갈린다 · §6-65
    //
    // 대상과 사유는 순수 함수 둘이 정한다 · 화면 없이 시험할 수 있어야 한다 · §6-98
    const target = motionRunTargetView({
      role: groupRunRole(), chosen: 'local',
    });
    renderMotionRunTarget(target);
    const scope = target.scope;
    const group = scope === 'group' ? groupRunAvailability() : null;
    const groupActive = Boolean(group?.active);
    // 막힌 이유는 **진짜 이유**로 · 실행 설정이 준비됐는데 애니메이션만 없으면 그렇게 말한다
    // (전에는 이때 「저장 설정과 실행 설정이 일치합니다 · 사용자 제어 가능」이 사유로 떴다 · 2026-10-02)
    const localReason = contextReady && !hasMotionFile
      ? '재생 등록된 애니메이션이 없습니다 · 「재생 등록」 후 재생 · 초기 위치 이동은 지금도 됩니다'
      : contextMessage;
    const { blocked, reason: blockReason } = motionRunBlockView({
      scope,
      availability: group || {},
      localReady: contextReady && hasRequiredFiles,
      localReason,
    });

    // 같은 이름의 자동 재생이 둘이었다 · 범위마다 자기 것만 보인다 · §6-66
    el.motionAutomationToggleWrap?.classList.toggle('hidden', scope === 'group');
    if (el.motionRunScopeGroupHint) {
      const availability = group || groupRunAvailability();
      el.motionRunScopeGroupHint.textContent = availability.ok
        ? '같은 시각에 동시 시작'
        : (availability.reason || '연동 상태 확인 중');
    }
    if (el.motionRunCheckButton) {
      // 실행 준비 검사는 이 PC 기준이다 · 그룹 범위에서는 쓰지 않는다
      // **준비 검사는 상태를 보는 일이다** · §6-203
      //
      // 「실행 컨텍스트가 준비 안 됐으면」 막았다 · 그런데 무엇이 모자란지
      // 보려고 누르는 버튼이다 · 안 되는 이유를 알려면 눌러야 하는데
      // 안 된다고 막으면 알 길이 없다.
      el.motionRunCheckButton.disabled = motionRunLoading
        || !hasRequiredFiles || running || scope === 'group';
      el.motionRunCheckButton.title = scope === 'group'
        ? '실행 준비 검사는 이 PC 단독 범위에서만 사용합니다'
        : (contextReady ? '' : contextMessage);
    }
    if (el.motionRunInitializeButton) {
      el.motionRunInitializeButton.disabled = motionRunLoading || running
        || (scope === 'group' ? !group.ok : (!contextReady || !hasMappingFile));
      // 초기 위치 이동은 애니메이션이 없어도 된다 · 재생 쪽 막힘 사유를 빌려 쓰지 않는다
      el.motionRunInitializeButton.title = scope === 'group'
        ? (group.ok ? '참가 PC 전체를 초기 위치로 이동합니다' : (group.reason || ''))
        : !contextReady
          ? contextMessage
          : !hasMappingFile
            ? '조인트 매핑이 없습니다'
            : hasMotionFile
              ? '줄마다 「초기 위치」대로 이동합니다 · 첫 프레임 = 애니메이션 첫 줄 · 직접 지정 = 그 값 · 기준점 = 0°'
              : '애니메이션이 없어 「첫 프레임」 줄은 모션 0°(기준점)로 · 「직접 지정」 줄은 그 값으로 이동합니다';
    }
    if (el.manualInitializeButton) {
      // 수동 조작 화면 · 늘 이 PC · 조그·다이얼·동작이 움직이는 중이면 끔(두 이동이 겹치지 않게) · 수정 목록 58
      const activity = getLatestState()?.motor_activity || {};
      const manualMoving = Boolean(activity.active) && activity.source === 'motion_supervisor';
      el.manualInitializeButton.disabled = motionRunLoading || running
        || !contextReady || !hasMappingFile || manualMoving;
      el.manualInitializeButton.title = manualMoving
        ? `${activity.label || '수동 동작'} · 멈춘 뒤 누르세요`
        : !contextReady
          ? contextMessage
          : !hasMappingFile
            ? '조인트 매핑이 없습니다'
            : running ? '재생 중에는 쓸 수 없습니다' : '줄마다 「초기 위치」대로 이동합니다';
    }
    if (el.motionRunStartButton) {
      el.motionRunStartButton.disabled = motionRunLoading || running || blocked;
      el.motionRunStartButton.title = blocked
        ? blockReason
        : (scope === 'group'
          ? `참가 PC ${group.peerCount}대를 같은 시각에 1회 실행합니다`
          : '전체 조인트 초기 위치 이동 완료 후 애니메이션을 1회 실행합니다');
    }
    if (el.motionRunContinuousStartButton) {
      el.motionRunContinuousStartButton.disabled = motionRunLoading || running
        || blocked || continuousUnavailable;
      el.motionRunContinuousStartButton.title = continuousUnavailable
        ? (continuousCapability?.reason || '연속 재생 안전조건을 통과하지 못했습니다')
        : (blocked
          ? blockReason
          : '전체 조인트 초기 위치 이동 완료 후 정지할 때까지 애니메이션을 반복합니다');
    }
    // 시작은 마스터만이지만 정지는 누구나 · 그룹이 도는 동안이면 슬레이브에서도
    // 세울 수 있어야 한다 · §6-70
    const stoppable = scope === 'group' ? groupActive : running;
    if (el.motionRunStopButton) {
      el.motionRunStopButton.disabled = motionRunLoading || !stoppable;
      el.motionRunStopButton.title = scope === 'group'
        ? '참가 PC 전체를 즉시 정지합니다'
        : '이 PC의 애니메이션을 즉시 정지합니다';
    }
    if (el.motionRunStopAfterButton) {
      el.motionRunStopAfterButton.disabled = motionRunLoading || !stoppable;
      el.motionRunStopAfterButton.title = scope === 'group'
        ? '참가 PC 전체를 현재 회차까지 마친 뒤 정지합니다'
        : '이 PC의 애니메이션을 현재 회차까지 마친 뒤 정지합니다';
    }
    if (el.motionRunRefreshButton) {
      el.motionRunRefreshButton.disabled = motionRunLoading;
    }
    // 버튼을 회색으로만 두면 고장처럼 보인다 · 슬레이브 PC 는 시작이 영원히
    // 불가라 더 그렇다 · 사유를 늘 같은 자리에 적는다 · §6-98
    if (el.motionRunBlockReason) {
      el.motionRunBlockReason.textContent = blockReason;
      el.motionRunBlockReason.classList.toggle('hidden', !blocked || !blockReason);
    }
    if (el.motionRunInitialMoveTime) {
      el.motionRunInitialMoveTime.disabled = motionRunLoading || running;
    }
    if (el.motionRunMessage) {
      // 오류는 덮지 않는다 · 애니메이션이 없을 때 실패가 안내 문구에 가려 안 보였다 (2026-10-02)
      const message = motionRunLoading
        ? '재생 요청 처리 중'
        : !hasMappingFile
          ? '조인트 매핑 파일을 선택하세요'
          : status.state === 'error' && status.message
            ? status.message
            : !hasMotionFile
              ? '애니메이션 없음 · 첫 프레임 모터는 모션값 0°로 초기 위치 이동할 수 있습니다'
              : status.message || '실행 준비 가능';
      el.motionRunMessage.textContent = message;
    }
    renderMotionRunSummary();
    renderMotionRunStatus();
    renderMotionRunStages();
    renderMotionRunProgressBar();
    renderMotionRunGraphAxisToggles();
    renderMotionRunGraph();
    updateMotionRunGraphAnimation();
    stopMotionRunGraphAnimationIfIdle();
    renderMotionRunAxes();
    renderMotionAutomation();
  }

  function renderMotionTabs() {
    // 'files'는 'run'에, 'mapping'은 모터 관리 화면에 합쳐졌다 · 모션 패널은 'run' 하나다
    activeMotionPanel = 'run';
    if (el.motionPanels) {
      el.motionPanels.forEach((panel) => {
        panel.classList.toggle('hidden', panel.dataset.motionPanel !== activeMotionPanel);
      });
    }
  }

  function renderFileRows() {
    if (el.motionFileCount) {
      el.motionFileCount.textContent = files.length ? `${files.length}개` : '';
    }
    if (!el.motionFileRows) return;
    if (!files.length) {
      el.motionFileRows.innerHTML = emptyRow(4, '저장된 애니메이션이 없습니다');
      return;
    }
    el.motionFileRows.innerHTML = files.map((file) => {
      const analysis = analysisOf(file);
      const selected = file.id === selectedFileId;
      // 재생 등록된 파일은 목록에서 바로 구분돼야 한다. 등록 여부를 알려면
      // 조인트 매핑을 열어봐야 했던 것이 가장 흔한 혼란이었다.
      const positions = registeredPlaylistValue
        .map((id, index) => (id === file.id ? index + 1 : 0))
        .filter(Boolean);
      const registered = positions.length > 0;
      const rowClass = [selected ? 'selected' : '', registered ? 'registered' : '']
        .filter(Boolean).join(' ');
      // 목록이면 차례 번호까지 · 「재생 2·4」 = 목록의 2번째와 4번째
      const badgeText = registeredPlaylistValue.length > 1
        ? `재생 ${positions.join('·')}`
        : '재생';
      const badge = (registered
        ? `<span class="motion-registered-badge" title="이 파일이 재생 등록되어 있습니다">${badgeText}</span>`
        : '') + mujocoBadge(file);
      return (
        `<tr class="${rowClass}" data-motion-file-id="${displayText(file.id)}">
          <td class="motion-file-name-cell"><div class="motion-file-name-inner">${badge}<button type="button" class="link-button" data-motion-file-id="${displayText(file.id)}" title="${displayText(file.filename)}">${displayText(file.filename)}</button></div></td>
          <td><span class="motion-state-pill ${statusClass(file)}">${statusText(file)}</span></td>
          <td>${formatNumber(analysis.time?.duration_sec, 3)} s</td>
          <td class="motion-file-moment" title="마지막으로 바뀐 시각">${displayText(formatMoment(file.updated_at))}</td>
        </tr>`
      );
    }).join('');
  }

  /** 애니메이션 버튼을 켜고 끈다 · §6-100
   *
   * **화면 조각에 딸려 있으면 안 된다** · 전에는 `선택 파일 상세`를 그리는
   * 함수 안에 끼어 있었다 · 그 화면을 걷어내자 함수째 사라져 재생 등록도
   * 삭제도 못 하는 상태가 됐다 · 버튼은 그 화면이 없어도 있다.
   */
  function renderMotionFileActions() {
    const file = selectedFile;
    const registered = Boolean(file && registeredPlaylistValue.includes(file.id));
    const listed = registeredPlaylistValue.length;
    if (el.deleteMotionFileButton) {
      el.deleteMotionFileButton.disabled = !file || loading;
      el.deleteMotionFileButton.title = registered
        ? '재생 등록을 해제한 뒤 삭제할 수 있습니다'
        : '';
    }
    if (el.downloadMotionFileButton) {
      el.downloadMotionFileButton.disabled = !file || !motionProjectId || loading;
      el.downloadMotionFileButton.title = file
        ? '이 파일을 지금 보고 있는 PC 에 저장합니다'
        : '애니메이션을 먼저 선택하세요';
    }
    if (el.previewMotionFileButton) {
      // 계산 버튼만 남았다 · 보기는 「3D 보기 (웹)」 · 네이티브 뷰어 창은 없앴다(7)
      const state = mujocoState(file);
      const LABELS = {
        missing: 'MuJoCo 계산', failed: '다시 계산', stale: '다시 계산',
        computing: '계산 중…', ready: '계산 완료', direct: '계산 없는 구성',
      };
      el.previewMotionFileButton.textContent = LABELS[state] || 'MuJoCo 계산';
      el.previewMotionFileButton.disabled = !file || loading
        || !(state === 'missing' || state === 'failed' || state === 'stale');
      el.previewMotionFileButton.title = !file
        ? '애니메이션을 먼저 선택하세요'
        : (state === '' || state === 'unavailable'
          ? 'MuJoCo 설정이 없습니다 · 로봇 팩(시스템 정보) 또는 config/animation_preview.yaml'
          : (state === 'computing'
            ? '무거운 물리 계산이 도는 중입니다 · 끝나면 3D 보기가 켜집니다'
            : (state === 'stale'
              ? `${file.preview?.message || '로봇 팩 변경'} · 누르면 지금 팩으로 다시 계산합니다`
              : (state === 'missing' || state === 'failed'
                ? '무거운 물리 계산을 시작합니다 · 끝나면 「3D 보기 (웹)」 에서 봅니다'
                : (state === 'ready'
                  ? '계산이 끝났습니다 · 아래 「3D 보기 (웹)」에서 봅니다'
                  : '계산(precompute)이 없는 구성입니다 · 웹 3D 로 볼 결과가 없습니다')))));
    }
    // 재생 등록은 **조인트 매핑 편집과 상관없다** · §6-160
    //
    // 전에는 두 버튼이 `mappingDirty` 로 꺼졌다 · 조인트 매핑을 편집 중이면
    // 애니메이션도 못 바꿨고, 등록이 한 번 실패하면 프로그램이 제 손으로 세운
    // 그 표시 때문에 **되돌아갈 길까지 사라졌다**.
    //
    // 한 파일에 들어 있을 뿐 둘은 남남이다 · 재생 등록이 이미 그렇게
    // 떨어져 있다.
    if (el.registerMotionFileButton) {
      // 목록이 비었으면 「재생 등록」 · 있으면 끝에 붙인다 (같은 파일 두 번도 된다) · 수정 목록 35
      el.registerMotionFileButton.disabled = (
        !file || !selectedMappingId || loading || mappingLoading
        || (listed === 1 && registered)
      );
      el.registerMotionFileButton.textContent = listed ? '재생 목록에 추가' : '재생 등록';
      el.registerMotionFileButton.title = !selectedMappingId
        ? '저장된 조인트 매핑을 먼저 선택하세요'
        : (listed
          ? '재생 목록 끝에 붙입니다 · 목록을 차례로 돌고 끝나면 1번부터 다시 · 조인트 매핑 편집과는 무관합니다'
          : '이 파일을 재생 등록합니다 · 조인트 매핑 편집과는 무관합니다');
    }
    if (el.unregisterMotionFileButton) {
      el.unregisterMotionFileButton.disabled = (
        !registered || !selectedMappingId || loading || mappingLoading
      );
      el.unregisterMotionFileButton.textContent = listed > 1 ? '목록에서 빼기' : '재생 등록 해제';
      el.unregisterMotionFileButton.title = registered
        ? (listed > 1
          ? '재생 목록에서 이 파일을 모두 뺍니다 · 파일은 지우지 않습니다'
          : '현재 조인트 매핑에서 이 파일의 재생 등록을 해제합니다')
        : '현재 재생 등록된 파일을 선택하세요';
    }
    renderPlaylistPanel();
  }

  function renderMappingFileName() {
    // 고르는 자리가 아니라 **보여주는 자리**다 · §6-239
    //
    // 프로젝트는 조인트 매핑 파일을 **하나만** 물고 쓴다 · 전에는 목록에서
    // 고르게 했는데, 고를 일이 없으니 고르는 상자와 「새 매칭 작성」·「목록
    // 새로고침」·「현재 설정 파일 삭제」가 다 쓸모없는 손잡이였다 · 그것들이
    // 만들 수 있는 어긋난 상태(등록된 파일과 다른 것을 편집하고 있다)만
    // 남았다.
    // 화면에는 「조인트 매핑 편집」 제목만 · 파일 이름은 툴팁으로 (2026-10-08 · 「연결 파일」 칸 삭제)
    if (!el.motionMappingFileName) return;
    const file = mappingFiles.find((item) => item.id === selectedMappingId);
    const name = file?.filename || selectedMappingId || '아직 없음 · 저장하면 만들어집니다';
    el.motionMappingFileName.title = `조인트 매핑 파일 · ${name}`;
  }

  function mappingDuplicateAxisCounts() {
    return mappingDraft.mappings.reduce((counts, row) => {
      const key = mappingTargetKey(row);
      if (!row.enabled || !key) return counts;
      counts[key] = (counts[key] || 0) + 1;
      return counts;
    }, {});
  }

  function mappingRowStatus(row, duplicateCounts) {
    if (!row.enabled) return { text: '비활성', className: 'warn' };
    const targetKey = mappingTargetKey(row);
    if (!targetKey) {
      return { text: '모터 미선택', className: 'bad' };
    }
    if ((duplicateCounts[targetKey] || 0) > 1) {
      return { text: '중복 매칭', className: 'bad' };
    }
    if (!motorForMapping(row)) {
      return { text: '현재 모터 없음', className: 'warn' };
    }
    return { text: '사용 가능', className: 'ok' };
  }

  function mappingValidationRowStatus(row, fallbackStatus) {
    const validationRow = mappingValidation?.rows?.[String(row.motion_id)];
    if (!validationRow) return fallbackStatus;
    if (validationRow.status === 'error') return { text: '검증 오류', className: 'bad' };
    if (validationRow.status === 'warning') return { text: '검증 주의', className: 'warn' };
    return { text: '검증 통과', className: 'ok' };
  }

  function motorSelectHtml(row) {
    const motors = sortedRuntimeMotors();
    const mappedMotor = motorForMapping(row);
    // 대소문자를 무시하고 맞춘다 · §6-104
    //
    // 화면은 `encodeURIComponent` 로 값을 만드는데 그것은 **대문자**를 낸다
    // (`%2Fdev%2F...usb-FTDI_...`) · 서버는 저장할 때 **소문자**로 바꾼다
    // (`%2fdev%2f...usb-ftdi_...`). 그래서 저장을 누른 뒤 화면이 제 선택을
    // 못 찾아 「선택 안함」으로 되돌아갔다.
    //
    // AC 서보 값(`ac_servo:master:0:alias:103`)은 대문자가 없어 안 걸린다 ·
    // **다이나믹셀에서만** 났고, 저장 직후에만 났다.
    //
    // 짝을 찾는 다른 곳(`motorForRef`)은 이미 양쪽을 소문자로 낮춰 비교한다 ·
    // 여기만 빠져 있었다.
    const value = String(
      row.motor_ref || motorSelectionValue(mappedMotor) || ''
    ).trim().toLowerCase();
    return (
      `<select class="wide-select" data-motion-mapping-field="motor_ref" data-motion-id="${displayText(row.motion_id)}">
        <option value="">선택 안함</option>
        ${motors.map((motor) => {
          const selectionValue = motorSelectionValue(motor);
          const selected = selectionValue.trim().toLowerCase() === value ? ' selected' : '';
          return selectionValue
            ? `<option value="${displayText(selectionValue)}"${selected}>${displayText(motorOptionLabel(motor))}</option>`
            : '';
        }).join('')}
      </select>`
    );
  }

  function renderMappingRows() {
    if (!el.motionMappingRows) return;
    const rows = Array.isArray(mappingDraft.mappings) ? mappingDraft.mappings : [];
    if (!rows.length) {
      el.motionMappingRows.innerHTML = emptyRow(17, '조인트 이름을 추가하거나 자동 생성을 누르세요');
      return;
    }
    const duplicateCounts = mappingDuplicateAxisCounts();
    const pendingEdit = focusedMappingEdit();
    renderJointNameDatalist(rows);
    el.motionMappingRows.innerHTML = rows.map((row, index) => {
      const status = mappingValidationRowStatus(row, mappingRowStatus(row, duplicateCounts));
      const initialMode = row.initial_mode || 'reference';   // 칸 없으면 기준점 · 서버와 같다 (13-3)
      // 값을 직접 넣는 것은 「직접 지정」뿐 · 첫 프레임·기준점은 보여 주기만
      const initialPositionDisabled = initialMode !== 'manual';
      const referencePositionValue = displayReferencePosition(row);
      const initialPositionValue = displayInitialPosition(row);
      // 감속·기어비 · 다이나믹셀도 입력 · 외부 기어 사례 (2026-10-04 · 「1 고정」 폐지)
      const gearRatioValue = numericOr(row?.gear_ratio, 1.0);
      // 초기 위치 · 첫 프레임(애니메이션 첫 줄 값) · 직접 지정(이 칸) · 기준점(모션 0°) · 2026-10-02
      const initialPositionDisabledAttr = initialMode === 'reference'
        ? ' disabled title="기준점 · 재생 전 모션 0°(기준점 캡처한 자세)로 이동합니다"'
        : initialPositionDisabled
          ? ' disabled title="첫 프레임 · 애니메이션 첫 프레임 값으로 이동합니다 (애니메이션이 없으면 0°) · 값 입력은 「직접 지정」일 때만"'
          : ' title="직접 지정 · 재생 전 이 값(조인트 deg)으로 이동합니다"';
      return (
        `<tr data-mapping-index="${index}">
          <td class="motion-id-cell"><input class="motion-id-input mono${String(row.motion_id || '').trim() ? '' : ' motion-id-empty'}" type="text" list="${JOINT_NAME_LIST_ID}" title="Blender 본 이름 그대로 입력하세요 · 등록된 애니메이션의 조인트 이름은 목록에서 고를 수 있습니다 (구 파일의 1-1 형식도 그대로 사용 가능)" data-motion-mapping-field="motion_id" value="${escapeHtml(row.motion_id ?? '')}" placeholder="Blender 본 이름" autocomplete="off" autocapitalize="off" spellcheck="false"></td>
          <td><input type="checkbox" data-motion-mapping-field="enabled" ${row.enabled ? 'checked' : ''}></td>
          <td class="mapping-motor-cell">${motorSelectHtml(row)}</td>
          <td class="mapping-number-cell"><input class="numeric-input mapping-number-input" type="number" min="0.0001" step="0.0001" data-motion-mapping-field="gear_ratio" value="${displayText(gearRatioValue)}"></td>
          <td class="mapping-number-cell"><input class="numeric-input mapping-number-input" type="number" step="0.001" data-motion-mapping-field="reference_position_deg" value="${displayText(referencePositionValue)}"></td>
          <td>
            <button class="mapping-mini-button" type="button" data-motion-mapping-action="capture_reference">캡처</button>
          </td>
          <td class="mapping-number-cell"><input class="numeric-input mapping-number-input" type="number" step="0.001" data-motion-mapping-field="motion_lower_deg" value="${displayText(row.motion_lower_deg)}"></td>
          <td class="mapping-number-cell"><input class="numeric-input mapping-number-input" type="number" step="0.001" data-motion-mapping-field="motion_upper_deg" value="${displayText(row.motion_upper_deg)}"></td>
          <td class="mapping-number-cell"><input class="numeric-input mapping-number-input" type="number" min="0" step="1" placeholder="없음" data-motion-mapping-field="max_velocity_deg_s" value="${row.max_velocity_deg_s == null ? '' : displayText(row.max_velocity_deg_s)}"></td>
          <td class="mapping-number-cell"><input class="numeric-input mapping-number-input" type="number" min="0" step="10" placeholder="없음" data-motion-mapping-field="max_acceleration_deg_s2" value="${row.max_acceleration_deg_s2 == null ? '' : displayText(row.max_acceleration_deg_s2)}"></td>
          <td>
            <select class="compact-select" data-motion-mapping-field="initial_mode" title="재생 전에 먼저 옮겨 둘 자세">
              <option value="first_frame"${initialMode === 'first_frame' ? ' selected' : ''}>첫 프레임</option>
              <option value="manual"${initialMode === 'manual' ? ' selected' : ''}>직접 지정</option>
              <option value="reference"${initialMode === 'reference' ? ' selected' : ''}>기준점</option>
            </select>
          </td>
          <td class="mapping-number-cell ${initialPositionDisabled ? 'mapping-disabled-cell' : ''}"><input class="numeric-input mapping-number-input" type="number" step="0.001" data-motion-mapping-field="initial_motion_position_deg" value="${displayText(initialPositionValue)}"${initialPositionDisabledAttr}></td>
          <td><input type="checkbox" data-motion-mapping-field="invert" title="방향 반전 · 실물이 반대로 돌면 켭니다 · Blender 는 그대로" ${row.invert ? 'checked' : ''}></td>
          <td><span class="motion-state-pill ${status.className}">${displayText(status.text)}</span> <button class="mapping-mini-button" type="button" data-motion-mapping-action="delete">삭제</button></td>
        </tr>`
      );
    }).join('');
    restoreMappingEdit(pendingEdit);
  }

  /** 입력 중인 칸 · 표를 통째로 다시 그리면 친 글자와 커서가 사라진다 · 수정 목록 68
   *
   * 칸 값은 `change`(칸을 떠날 때)에야 초안에 들어간다 · 그 전에 애니메이션 목록
   * 새로 고침(MuJoCo 계산 중 5초마다 등)이 `render()` 로 표를 다시 그리면, 친 이름이
   * 초안의 옛 값(`1-2` 등)으로 되돌아갔다 · 다시 그리기 전에 칸·글자·커서를 적어
   * 두고 새 칸에 돌려놓는다. */
  function focusedMappingEdit() {
    const active = document.activeElement;
    if (!active || !el.motionMappingRows?.contains(active)) return null;
    const field = active.dataset?.motionMappingField;
    const row = active.closest?.('tr[data-mapping-index]');
    if (!field || !row || !['text', 'number'].includes(active.type)) return null;
    let selection = null;
    try {
      selection = [active.selectionStart, active.selectionEnd];
    } catch {
      selection = null;   // number 칸은 커서 위치를 못 읽는다
    }
    return {
      index: row.dataset.mappingIndex,
      field,
      value: active.value,
      // 초안에 아직 안 들어간 글자인지 · 다시 그린 칸의 기본값과 비교한다
      defaultValue: active.defaultValue,
      selection,
    };
  }

  function restoreMappingEdit(edit) {
    if (!edit) return;
    const input = el.motionMappingRows?.querySelector(
      `tr[data-mapping-index="${edit.index}"] [data-motion-mapping-field="${edit.field}"]`,
    );
    if (!input || input.disabled) return;
    input.value = edit.value;
    input.focus();
    if (edit.selection && edit.selection[0] !== null) {
      try {
        input.setSelectionRange(edit.selection[0], edit.selection[1]);
      } catch {
        // number 칸 · 커서 위치는 못 돌린다
      }
    }
    // 코드로 넣은 값은 칸을 떠날 때 `change` 가 안 난다 · 직접 낸다
    if (edit.value !== edit.defaultValue) {
      input.addEventListener('blur', () => {
        if (input.isConnected && input.value !== input.defaultValue) {
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }, { once: true });
    }
  }

  /** 조인트 이름 칸 자동 완성 · 조인트 매핑에 등록된 애니메이션의 조인트 이름 · 수정 목록 68
   *
   * 이미 다른 줄이 쓴 이름은 뺀다 · 목록에 없는 이름도 그대로 칠 수 있다 ·
   * `<datalist>` 는 표 안(`tbody`)에 둘 수 없어 문서 끝에 하나 둔다. */
  function renderJointNameDatalist(rows) {
    let list = document.getElementById(JOINT_NAME_LIST_ID);
    if (!list) {
      list = document.createElement('datalist');
      list.id = JOINT_NAME_LIST_ID;
      document.body.appendChild(list);
    }
    const used = new Set(rows.map((row) => String(row.motion_id || '').trim()).filter(Boolean));
    const names = jointNameSuggestions(analysisOf(mappingMotionFileDetail)?.motion_ids, used);
    list.innerHTML = names.map((name) => `<option value="${displayText(name)}"></option>`).join('');
  }

  function renderMappingValidation() {
    if (!el.motionMappingValidation) return;
    if (!mappingValidation) {
      el.motionMappingValidation.innerHTML = '<div class="empty">맨 아래 「저장」을 누르면 검증 결과가 표시됩니다</div>';
      return;
    }

    const errors = Array.isArray(mappingValidation.errors) ? mappingValidation.errors : [];
    const warnings = Array.isArray(mappingValidation.warnings) ? mappingValidation.warnings : [];
    const valid = Boolean(mappingValidation.valid);
    const issueItems = [
      ...errors.map((message) => `<li>오류: ${displayText(message)}</li>`),
      ...warnings.map((message) => `<li>주의: ${displayText(message)}</li>`),
    ].join('');
    const rows = Array.isArray(mappingDraft.mappings) ? mappingDraft.mappings : [];
    const tableRows = rows.map((row) => {
      const detail = mappingValidation.rows?.[String(row.motion_id)] || {};
      const status = detail.status === 'error'
        ? { text: '오류', className: 'bad' }
        : detail.status === 'warning'
          ? { text: '주의', className: 'warn' }
          : { text: '통과', className: 'ok' };
      const messages = Array.isArray(detail.messages) && detail.messages.length
        ? detail.messages.join(', ')
        : '-';
      const rangeText = (
        `${targetText(detail.motion_motor_target_min_deg)} ~ ${targetText(detail.motion_motor_target_max_deg)}`
      );
      const outputRangeText = (
        `${targetText(detail.motion_output_min_deg)} ~ ${targetText(detail.motion_output_max_deg)}`
      );
      const limitInfo = motorLimitInfo(row, detail);
      const referenceClass = exceedsMotorAxisAngleAlert(detail.reference_position_deg)
        ? 'validation-angle-alert'
        : '';
      const targetRangeClass = limitInfo.className === 'bad' ? 'validation-angle-alert' : '';
      const firstFrameText = Number.isFinite(Number(detail.first_frame_motor_target_deg))
        ? `${targetText(detail.first_frame_motion_position_deg)} -> ${targetText(detail.first_frame_output_deg)} -> ${targetText(detail.first_frame_motor_target_deg)}`
        : '첫 프레임 실행 시 계산';
      const initialText = row.initial_mode === 'manual'
        ? `${targetText(detail.initial_motion_position_deg)} -> ${targetText(detail.manual_initial_output_deg)} -> ${targetText(detail.manual_initial_motor_target_deg)}`
        : row.initial_mode === 'reference'
          ? `기준점 0 deg -> ${targetText(detail.reference_position_deg)}`
          : firstFrameText;
      return (
        `<tr>
          <td class="mono">${displayText(row.motion_id)}</td>
          <td><span class="motion-state-pill ${status.className}">${status.text}</span></td>
          <td>${displayText(messages)}</td>
          <td class="${referenceClass}">${targetText(detail.reference_position_deg)}</td>
          <td>${displayText(outputRangeText)}</td>
          <td>
            <div class="validation-range-cell">
              <span class="${targetRangeClass}">${displayText(rangeText)}</span>
              <span class="validation-limit-text">모터 리미트: ${displayText(limitInfo.rangeText)}</span>
            </div>
          </td>
          <td>${displayText(initialText)}</td>
        </tr>`
      );
    }).join('');

    el.motionMappingValidation.innerHTML = `
      <div class="motion-mapping-validation-summary">
        <span class="motion-state-pill ${valid ? 'ok' : 'bad'}">${valid ? '검증 통과' : '검증 오류'}</span>
        <span>오류 ${formatInt(errors.length)}</span>
        <span>주의 ${formatInt(warnings.length)}</span>
      </div>
      ${issueItems ? `<ul class="motion-mapping-validation-issues">${issueItems}</ul>` : ''}
      <table class="motion-mapping-validation-table">
        <thead>
          <tr>
            <th><span class="validation-head-label">조인트 이름</span><span class="validation-head-unit">ID</span></th>
            <th><span class="validation-head-label">상태</span><span class="validation-head-unit">검증</span></th>
            <th><span class="validation-head-label">메시지</span><span class="validation-head-unit">-</span></th>
            <th><span class="validation-head-label">기준점</span><span class="validation-head-unit">모터 deg</span></th>
            <th><span class="validation-head-label">출력축 범위</span><span class="validation-head-unit">출력축 deg</span></th>
            <th><span class="validation-head-label">모터 목표 범위</span><span class="validation-head-unit">모터 deg / limit</span></th>
            <th><span class="validation-head-label">초기 위치 변환</span><span class="validation-head-unit">모션 → 출력축 → 모터 deg</span></th>
          </tr>
        </thead>
        <tbody>${tableRows || emptyRow(7, '검증할 조인트가 없습니다')}</tbody>
      </table>
    `;
  }

  function renderMappingPanel() {
    renderMappingFileName();
    // 저장 단추는 모터 관리 맨 아래 「저장」 하나다 · 그 바가 편집 상태를 다시 그린다
    onMappingStateChange?.();
    if (el.addMotionIdButton) el.addMotionIdButton.disabled = mappingLoading;
    if (el.generateMotionIdsButton) el.generateMotionIdsButton.disabled = mappingLoading;
    if (el.resetMotionMappingButton) el.resetMotionMappingButton.disabled = mappingLoading;
    el.motionMappingRows?.closest('table')?.classList.toggle('mapping-loading', mappingLoading);
    renderMappingRows();
    renderMappingValidation();
  }

  function renderRuntimeMappingState() {
    // 매핑 표는 모터 관리 화면에 산다 · 화면에 보일 때만 실시간 값을 다시 그린다
    const host = el.motionMappingRows?.closest('[data-workspace-panel]');
    if (!host || host.classList.contains('hidden')) return;
    const activeElement = document.activeElement;
    if (
      activeElement &&
      activeElement.closest?.('#motionMappingRows')
    ) {
      return;
    }
    renderMappingRows();
  }

  /** 「초기 위치 이동」을 누른 뒤 상태가 오류로 끝나면 한 번 창으로 알린다 · 2026-10-02
   *
   * 요청은 바로 「시작」으로 답한다 · 움직이는 중 실패는 상태로만 와서 놓치기 쉬웠다.
   * 다른 데서 시작한 실행의 오류까지 띄우지 않게, 누른 뒤 정해진 시간 동안만 본다.
   */
  function watchInitializeOutcome(status) {
    if (!initializeWatchUntil) return;
    if (Date.now() > initializeWatchUntil) {
      initializeWatchUntil = 0;
      return;
    }
    const state = String(status?.state || '');
    // 직전 실행이 남긴 옛 오류에 속지 않게 · 누른 뒤 오류 아닌 상태를 한 번 본 다음부터 센다
    if (state !== 'error') initializeWatchStarted = true;
    if (state === 'error' && initializeWatchStarted) {
      initializeWatchUntil = 0;
      showMotionRunFailure(status.message || '초기 위치 이동 실패', '초기 위치 이동 실패');
    } else if (state === 'initialized' || state === 'completed' || state === 'stopped') {
      initializeWatchUntil = 0;
    }
  }

  function renderRuntimeState() {
    const status = getLatestState()?.motion_run_status;
    if (status && Object.keys(status).length) {
      motionRunStatus = status;
      watchInitializeOutcome(status);
      renderMotionRunPanel();
    }
    renderRuntimeMappingState();
  }

  function render() {
    renderMotionTabs();
    renderFileRows();
    scheduleMujocoPoll();
    renderMotionFileActions();
    renderMappingPanel();
    renderMotionRunPanel();
  }

  function newMotionAxisRow(motionId, motorAxis = null) {
    return defaultMotionAxisRow(motionId, motorAxis);
  }

  async function addMotionId() {
    const entered = await showPrompt('추가할 조인트 이름을 입력하세요 (Blender 본 이름)', {
      title: 'Motion ID 추가',
      defaultValue: '1-1',
      confirmLabel: '추가',
    });
    const motionId = String(entered || '').trim();
    if (!motionId) return;
    if (mappingDraft.mappings.some((row) => String(row.motion_id) === motionId)) {
      setMappingMessage(`이미 존재하는 조인트 이름입니다: ${motionId}`);
      return;
    }
    mappingDraft.mappings.push(newMotionAxisRow(motionId));
    mappingValidation = null;
    markMappingDirty();
    setMappingMessage(`조인트 이름 ${motionId} 추가 완료`);
    renderMappingPanel();
  }

  function generateMotionIdsFromMotors() {
    const motors = sortedRuntimeMotors();
    if (!motors.length) {
      setMappingMessage('현재 프로젝트에 등록된 모터모터가 없습니다. 모터 설정을 먼저 저장하세요');
      return;
    }
    upgradeLegacyMappingRefs();
    mappingDraft.mappings = buildGeneratedMotionAxisRows(motors, mappingDraft.mappings);
    mappingValidation = null;
    markMappingDirty();
    setMappingMessage(`${motors.length}개 모터 행을 만들었습니다 · 빈 조인트 이름 칸에 Blender 본 이름을 넣으세요`);
    renderMappingPanel();
  }

  async function ensureMappingMotionFileDetail(fileId) {
    if (!fileId) return null;
    if (mappingMotionFileDetail?.id === fileId) return mappingMotionFileDetail;
    if (selectedFile?.id === fileId) {
      mappingMotionFileDetail = selectedFile;
      return mappingMotionFileDetail;
    }
    const payload = await fetchMotionFile(fileId);
    mappingMotionFileDetail = payload.file || null;
    files = Array.isArray(payload.files) ? payload.files : files;
    return mappingMotionFileDetail;
  }

  function validateMappingDraft() {
    upgradeLegacyMappingRefs();
    if (!mappingDraft.name?.trim()) return '매핑 이름이 필요합니다';
    const rows = Array.isArray(mappingDraft.mappings) ? mappingDraft.mappings : [];
    if (!rows.length) return '조인트 이름을 먼저 추가하세요';
    // 조인트 이름 = Blender 본 이름 · 임의 문자열이라 형식 제한이 없다 (구 1-1 식도 그대로 동작)
    const emptyIndex = rows.findIndex((row) => !String(row.motion_id || '').trim());
    if (emptyIndex >= 0) {
      const motor = motorForMapping(rows[emptyIndex]);
      const motorText = motor ? ` · ${motorOptionLabel(motor)}` : '';
      return `조인트 이름이 비어 있습니다 · ${emptyIndex + 1}번째 줄${motorText}`;
    }
    const motionIdCounts = rows.reduce((counts, row) => {
      const motionId = String(row.motion_id || '').trim();
      counts[motionId] = (counts[motionId] || 0) + 1;
      return counts;
    }, {});
    const duplicateMotionId = Object.entries(motionIdCounts).find(([, count]) => count > 1);
    if (duplicateMotionId) return `조인트 이름이 중복되었습니다: ${duplicateMotionId[0]}`;
    const duplicateCounts = mappingDuplicateAxisCounts();
    const duplicateAxis = Object.entries(duplicateCounts).find(([, count]) => count > 1);
    if (duplicateAxis) return `동일한 모터 ID가 중복 사용되었습니다: ${duplicateAxis[0]}`;
    const enabledWithoutMotor = rows.find((row) => row.enabled && !mappingTargetKey(row));
    if (enabledWithoutMotor) return `활성화된 조인트 이름에 모터 ID가 없습니다: ${enabledWithoutMotor.motion_id}`;
    return '';
  }

  async function loadMappings(selectMappingId = selectedMappingId) {
    const loadToken = ++mappingLoadToken;
    mappingLoading = true;
    setMappingMessage('매핑 목록 불러오는 중');
    renderMappingPanel();
    try {
      const payload = await fetchMotionMappings();
      if (loadToken !== mappingLoadToken) return;
      mappingFiles = Array.isArray(payload.files) ? payload.files : [];
      if (selectMappingId && mappingFiles.some((file) => file.id === selectMappingId)) {
        await selectMapping(selectMappingId);
        return;
      }
      // **프로젝트가 물고 있는 파일**을 연다 · 판단은 밖에 있다 · §6-238
      const openId = mappingFileToOpen({
        files: mappingFiles,
        activeFileId: payload.active_file_id,
      });
      if (openId && openId !== selectedMappingId) {
        await selectMapping(openId);
        return;
      }
      if (selectedMappingId && !mappingFiles.some((file) => file.id === selectedMappingId)) {
        selectedMappingId = null;
        mappingRevision = '';
        mappingDraft = emptyMappingDraft();
        registeredMotionFileIdValue = '';
        registeredPlaylistValue = [];
        mappingValidation = null;
        mappingDirty = false;
        mappingRevisionConflict = false;
      }
      setMappingMessage('');
    } catch (error) {
      if (loadToken !== mappingLoadToken || error?.staleProjectResponse) return;
      setMappingMessage(`매핑 목록 실패: ${error?.message || error}`);
    } finally {
      if (loadToken === mappingLoadToken) {
        mappingLoading = false;
        renderMappingPanel();
      }
    }
  }

  async function selectMapping(fileId) {
    const requestedMappingId = fileId || null;
    const loadToken = ++mappingLoadToken;
    if (!requestedMappingId) {
      selectedMappingId = null;
      mappingDraft = emptyMappingDraft();
      registeredMotionFileIdValue = '';
      registeredPlaylistValue = [];
      mappingValidation = null;
      mappingMotionFileDetail = null;
      mappingDirty = false;
      mappingRevisionConflict = false;
      mappingRevision = '';
      renderMappingPanel();
      return;
    }
    mappingLoading = true;
    setMappingMessage('매핑 파일 불러오는 중');
    renderMappingPanel();
    try {
      const payload = await fetchMotionMapping(requestedMappingId);
      if (loadToken !== mappingLoadToken) return;
      if (payload.success === false || !payload.mapping) {
        // **실패한 응답으로 덮어쓰지 않는다** · §6-237
        //
        // 서버는 못 읽었을 때도 **HTTP 200** 에 `success: false` 만 실어
        // 보낸다 · 그래서 여기는 오류로 치지 않았고, 아래 한 줄이
        //
        //     const loadedDraft = payload.mapping || emptyMappingDraft();
        //
        // 들고 있던 설정을 **빈 것으로 갈아엎었다** · 「매핑 이름」이 비고
        // 저절로 돌아오지 않았다 · 파일은 서버에 멀쩡히 있는데도 그랬다.
        //
        // 「설정 적용 · 모터 재시작」 뒤에 늘 그랬다 · 웹 서버가 다시 뜨면
        // 화면이 곧바로 매핑을 다시 읽는데, 그 순간 모션 쪽 노드가 아직
        // 안 떠서 `success: false` 가 온다 · 실측 34밀리초 만에 지워졌다.
        //
        // 못 읽었으면 **아무것도 하지 않는 것이 맞다** · 화면이 들고 있던
        // 것이 마지막으로 확인된 값이다 · 노드가 뜨면 다시 읽는다.
        setMappingMessage('조인트 매핑을 아직 못 읽었습니다 · 잠시 후 다시 읽습니다');
        window.setTimeout(() => {
          if (selectedMappingId === requestedMappingId) selectMapping(requestedMappingId);
        }, 3000);
        return;
      }
      const loadedDraft = payload.mapping;
      let loadedMotionFileDetail = null;
      let loadedMotionFiles = files;
      if (loadedDraft.motion_file_id) {
        if (selectedFile?.id === loadedDraft.motion_file_id) {
          loadedMotionFileDetail = selectedFile;
        } else {
          const motionPayload = await fetchMotionFile(loadedDraft.motion_file_id);
          if (loadToken !== mappingLoadToken) return;
          loadedMotionFileDetail = motionPayload.file || null;
          loadedMotionFiles = Array.isArray(motionPayload.files)
            ? motionPayload.files
            : loadedMotionFiles;
        }
      }
      files = loadedMotionFiles;
      mappingFiles = Array.isArray(payload.files) ? payload.files : mappingFiles;
      mappingDraft = loadedDraft;
      registeredMotionFileIdValue = registeredMotionFileId(loadedDraft);
      registeredPlaylistValue = registeredPlaylist(loadedDraft);
      upgradeLegacyMappingRefs();
      selectedMappingId = payload.file?.id || mappingDraft.file_id || requestedMappingId;
      mappingRevision = mappingFileRevision(payload.file);
      mappingValidation = payload.validation || null;
      mappingMotionFileDetail = loadedMotionFileDetail;
      mappingDirty = false;
      mappingRevisionConflict = false;
      // 잘 읽었으면 할 말이 없다 · 파일 이름 줄이 늘 떠 있던 것 (사용자 2026-10-08)
      setMappingMessage('');
    } catch (error) {
      if (loadToken !== mappingLoadToken || error?.staleProjectResponse) return;
      setMappingMessage(`매핑 파일 실패: ${error?.message || error}`);
    } finally {
      if (loadToken === mappingLoadToken) {
        mappingLoading = false;
        renderMappingPanel();
      }
    }
  }

  /** 파일을 **이 웹을 보고 있는 컴퓨터**에 저장한다 · 서버끼리 옮기지 않는다.
   *
   * blob 이 아니라 평범한 링크다. blob 은 헤드리스에서 확인이 안 됐고, 서버가
   * 한글 파일명을 이미 `filename*=utf-8''` 로 붙여 준다.
   */
  /** MuJoCo 상태 · 서버가 파일마다 실어 준다 (ready·computing·missing…) · P7 */
  function mujocoState(file) {
    return String(file?.preview?.state || '');
  }

  function mujocoBadge(file) {
    const state = mujocoState(file);
    if (state === 'computing') return '<span class="mujoco-badge computing" title="무거운 물리 계산이 도는 중 · 끝나면 3D 보기가 켜집니다">MuJoCo 계산 중</span>';
    if (state === 'ready') return '<span class="mujoco-badge ready" title="MuJoCo 계산 완료 · 3D 보기 가능">MuJoCo</span>';
    if (state === 'failed') {
      // 이유(코드 · 기록 파일 · 옛 결과 있음)를 그대로 · 수정 목록 54
      const why = escapeHtml(`${file?.preview?.message || '마지막 계산이 실패했습니다'} · 다시 계산을 누르세요`);
      return `<span class="mujoco-badge failed" title="${why}">계산 실패</span>`;
    }
    if (state === 'stale') {
      const why = escapeHtml(file?.preview?.message || '로봇 팩 변경');
      return `<span class="mujoco-badge stale" title="${why}">다시 계산 필요</span>`;
    }
    return '';
  }

  /** MuJoCo 계산 버튼 · missing/failed/stale 에서만 · 보기는 「3D 보기 (웹)」 (7)
   *
   * missing → 「MuJoCo 계산」(시작) · computing → 그레이 「계산 중…」 ·
   * ready → 「계산 완료」(비활성) · failed/stale → 「다시 계산」
   */
  async function previewSelectedMotionFile() {
    if (!selectedFileId) return;
    const state = mujocoState(selectedFile);
    if (!(state === 'missing' || state === 'failed' || state === 'stale')) return;
    try {
      const result = await precomputeMotionFile(selectedFileId);
      setMessage(result?.message || 'MuJoCo 계산 시작');
      await loadFiles(selectedFileId);
    } catch (error) {
      setMessage(`MuJoCo 계산 실패: ${error?.message || error}`);
    }
  }

  /** 계산이 도는 동안은 목록을 몇 초마다 다시 읽어 상태를 갱신한다 */
  let mujocoPollTimer = null;
  function scheduleMujocoPoll() {
    const computing = files.some((file) => mujocoState(file) === 'computing');
    if (!computing || mujocoPollTimer) return;
    mujocoPollTimer = window.setTimeout(async () => {
      mujocoPollTimer = null;
      await loadFiles(selectedFileId);
    }, 5000);
  }

  function downloadSelectedMotionFile() {
    const file = selectedFile;
    if (!file || !motionProjectId) {
      setMessage('내 PC로 저장할 애니메이션을 먼저 선택하세요');
      return;
    }
    const anchor = document.createElement('a');
    anchor.href = projectFileDownloadUrl(motionProjectId, 'motions', file.id);
    anchor.download = file.filename || file.id;
    anchor.click();
    setMessage(`내 PC로 저장: ${file.filename || file.id}`);
  }

  /** 재생 등록·해제를 걸고 **실패하면 되돌린다** · §6-159
   *
   * 전에는 이랬다 · 등록을 누르면 먼저 초안을 고치고 `markMappingDirty()` 를
   * 세운 다음 저장했다 · 저장이 실패하면 **그 「고쳐진 중」 표시가 그대로
   * 남았다**.
   *
   * 그러면 등록 버튼도 해제 버튼도 `mappingDirty` 때문에 꺼진다 · 버튼에는
   * 「설정 저장 필요」 라고 뜨는데, 사용자는 아무것도 편집한 적이 없다 ·
   * 프로그램이 제 손으로 세운 표시 때문에 **되돌아갈 길이 사라진다**.
   *
   * 실제로 그렇게 막혔다 · 조인트 매핑 파일이 화면을 띄운 뒤 바뀌어
   * (`revision conflict`) 저장이 거부됐고, 그 뒤로는 등록도 해제도 안 됐다.
   *
   * 여기 들어올 때 `mappingDirty` 는 반드시 거짓이다(두 함수가 먼저 막는다) ·
   * 그러니 실패하면 우리가 세운 것만 지우면 된다.
   */
  /** 재생 등록·해제 · **조인트 매핑은 건드리지 않는다** · §6-160
   *
   * 전에는 `saveCurrentMapping()` 을 불렀다 · 그것은 조인트 매핑 **전체**를
   * 보내는 길이라 두 가지가 딸려 왔다.
   *
   *   하나 · 편집 중인 조인트 매핑까지 같이 저장된다 (원하지 않은 저장)
   *   둘  · 설정 개정 검사에 걸려 「조인트 매핑 저장 충돌」 창이 뜬다
   *
   * 애니메이션만 건드린 사람에게 편집한 적도 없는 설정을 되돌릴지 묻는
   * 창이 떴다 · 조인트 매핑과 재생 등록은 한 파일에 들어 있을 뿐
   * 서로 남남이다.
   */
  async function applyMotionFileRegistration(playlist, label) {
    setMappingMessage(label);
    mappingLoading = true;
    renderMappingPanel();
    // 등록 버튼·목록 버튼도 바로 잠근다 · 전에는 끝날 때까지 다시 눌렸다 (87)
    renderMotionFileActions();
    renderPlaylistPanel();
    busy.begin('register', `${label} · 로봇 프로그램에 적용하는 중 (긴 애니는 몇 초)`);
    try {
      const payload = await saveRegisteredMotionFile({
        file_id: selectedMappingId,
        motion_file_id: playlist[0] || '',
        motion_playlist: playlist,
      });
      if (payload.success === false) {
        setMappingMessage(`재생 등록 실패: ${payload.message || '저장하지 못했습니다'}`);
        return false;
      }
      // 편집 중인 조인트 매핑은 **그대로 둔다** · 우리가 바꾼 칸만 반영한다
      const saved = Array.isArray(payload.motion_playlist) ? payload.motion_playlist : playlist;
      const first = saved[0] || '';
      mappingDraft.motion_file_id = first;
      if (saved.length > 1) mappingDraft.motion_playlist = [...saved];
      else delete mappingDraft.motion_playlist;
      if (mappingMotionFileDetail?.id !== first) {
        mappingMotionFileDetail = selectedFile?.id === first ? selectedFile : null;
      }
      registeredMotionFileIdValue = registeredMotionFileId(mappingDraft);
      registeredPlaylistValue = registeredPlaylist(mappingDraft);
      registeredPlaylistValue = registeredPlaylist(mappingDraft);
      syncMappingFileRevision(payload.file);
      setMappingMessage(payload.message || label);
      await onProjectFilesChange?.();
      return true;
    } catch (error) {
      setMappingMessage(`재생 등록 실패: ${error?.message || error}`);
      return false;
    } finally {
      mappingLoading = false;
      busy.end('register');
      renderMappingPanel();
    }
  }

  async function registerSelectedMotionFile() {
    if (mappingLoading) return;
    if (!selectedFile || !selectedMappingId) {
      setMessage('재생 등록할 애니메이션과 저장된 조인트 매핑을 먼저 선택하세요');
      return;
    }
    const analysis = analysisOf(selectedFile);
    if (analysis.valid === false) {
      setMessage('검증에 실패한 애니메이션은 재생 등록할 수 없습니다');
      return;
    }
    const current = registeredPlaylistValue;
    const next = playlistWithAdded(current, selectedFile.id);
    if (current.length && next.length === current.length) {
      setMessage('재생 목록이 가득 찼습니다');
      return;
    }
    const confirmed = await showConfirm(
      current.length
        ? `${selectedFile.filename} 파일을 재생 목록 ${next.length}번째로 붙입니다.\n`
          + '목록을 차례로 돌고, 끝나면 1번부터 다시 돕니다.'
        : `${selectedFile.filename} 파일을 현재 조인트 매핑의 재생 파일로 등록합니다.\n`
          + `${selectedMappingId}`,
      {
        title: current.length ? '재생 목록에 추가' : '애니메이션 재생 등록',
        confirmLabel: current.length ? '추가' : '재생 등록',
        tone: 'primary',
      },
    );
    if (!confirmed) return;
    await applyMotionFileRegistration(
      next,
      `재생 등록 저장 중: ${selectedFile.filename}`,
    );
    render();
  }

  /** 재생 목록 칸에서 옮기기·빼기 · 확인 창 없이 · 되돌리기도 같은 버튼이다 */
  async function editPlaylist(action, index) {
    if (!selectedMappingId || mappingLoading) return;
    const current = registeredPlaylistValue;
    const next = action === 'remove'
      ? playlistWithout(current, index)
      : playlistWithMoved(current, index, action === 'up' ? -1 : 1);
    if (next.join('\n') === current.join('\n')) return;
    // 마지막 하나를 빼면 재생 등록 해제와 같다 · 같은 확인을 받는다 · 수정 목록 59
    if (!next.length) {
      const confirmed = await showConfirm(
        '재생 등록을 해제합니다.\n파일은 삭제되지 않으며, 다시 등록하기 전까지 애니메이션 재생은 차단됩니다.',
        { title: '애니메이션 재생 등록 해제', confirmLabel: '등록 해제', tone: 'danger' },
      );
      if (!confirmed) return;
    }
    await applyMotionFileRegistration(next, next.length ? '재생 목록 저장 중' : '재생 등록 해제 저장 중');
    if (!registeredMotionFileIdValue) {
      motionRunStatus = null;
      motionRunLastResult = null;
      setMotionRunMessage('재생 등록된 애니메이션이 없습니다');
    }
    render();
  }

  function renderPlaylistPanel() {
    const panel = el.motionPlaylistPanel;
    if (!panel) return;
    // 0개 · 1개여도 늘 보인다 · 수정 목록 59
    panel.classList.remove('hidden');
    panel.innerHTML = playlistPanelHtml(registeredPlaylistValue, {
      busy: loading || mappingLoading || !selectedMappingId,
      fileOf: (id) => {
        const file = files.find((entry) => entry.id === id);
        return file ? { filename: file.filename, durationSec: analysisOf(file).time?.duration_sec } : null;
      },
    });
  }

  async function unregisterSelectedMotionFile() {
    if (!selectedFile || !selectedMappingId || !registeredPlaylistValue.includes(selectedFile.id)) {
      setMessage('현재 재생 등록된 애니메이션을 선택하세요');
      return;
    }
    const registeredFilename = selectedFile.filename;
    const next = registeredPlaylistValue.filter((id) => id !== selectedFile.id);
    const confirmed = await showConfirm(
      next.length
        ? `${registeredFilename} 파일을 재생 목록에서 뺍니다.\n파일은 삭제되지 않습니다.`
        : `${registeredFilename} 파일의 재생 등록을 해제합니다.\n`
          + '파일은 삭제되지 않으며, 다시 등록하기 전까지 애니메이션 재생은 차단됩니다.',
      {
        title: next.length ? '재생 목록에서 빼기' : '애니메이션 재생 등록 해제',
        confirmLabel: next.length ? '빼기' : '등록 해제',
        tone: 'danger',
      },
    );
    if (!confirmed) return;
    await applyMotionFileRegistration(
      next,
      `재생 등록 해제 저장 중: ${registeredFilename}`,
    );
    if (!registeredMotionFileIdValue) {
      motionRunStatus = null;
      motionRunLastResult = null;
      setMotionRunMessage('재생 등록된 애니메이션이 없습니다');
    }
    render();
  }

  /** 저장하고 **됐는지 알려준다** · §6-159
   *
   * 전에는 아무것도 안 돌려줬다 · 부르는 쪽은 실패를 알 길이 없어 성공한 셈
   * 치고 넘어갔고, 그 사이 「고쳐진 중」 표시만 남아 버튼이 죽었다.
   */
  async function saveCurrentMapping() {
    const draftError = validateMappingDraft();
    if (draftError) {
      mappingValidation = null;
      setMappingMessage(`매핑 저장 중단: ${draftError}`);
      renderMappingPanel();
      return false;
    }
    mappingLoading = true;
    setMappingMessage('매핑 저장 중');
    upgradeLegacyMappingRefs();
    renderMappingPanel();
    try {
      const validated = await validateMotionMapping({
        file_id: selectedMappingId || '',
        mapping: mappingDraft,
      });
      mappingDraft = validated.mapping || mappingDraft;
      mappingValidation = validated.validation || null;
      if (validated.success === false || mappingValidation?.valid === false) {
        setMappingMessage(
          `검증 실패 · 저장하지 않음: ${validated.message || '설정 오류를 확인하세요'}`,
        );
        return false;
      }
      const payload = await saveMotionMapping({
        file_id: selectedMappingId || '',
        base_mapping_revision: mappingRevision,
        mapping: mappingDraft,
      });
      mappingValidation = payload.validation || null;
      if (payload.success === false) {
        mappingDraft = payload.mapping || mappingDraft;
        if (isMappingRevisionConflict(payload.message)) {
          await resolveMappingRevisionConflict(payload.message);
          return false;
        }
        setMappingMessage(`매핑 저장 실패: ${payload.message || '검증 실패'}`);
        return false;
      }
      mappingFiles = Array.isArray(payload.files) ? payload.files : mappingFiles;
      mappingDraft = payload.mapping || mappingDraft;
      registeredMotionFileIdValue = registeredMotionFileId(mappingDraft);
      registeredPlaylistValue = registeredPlaylist(mappingDraft);
      selectedMappingId = payload.file?.id || mappingDraft.file_id || selectedMappingId;
      mappingRevision = mappingFileRevision(payload.file);
      mappingDirty = false;
      mappingRevisionConflict = false;
      setMappingMessage(payload.message || (
        payload.runtime_applied
          ? `조인트 매핑 저장 완료: ${selectedMappingId} · 실행 컨텍스트 적용 완료`
          : `조인트 매핑 저장 완료: ${selectedMappingId}`
      ));
      await onProjectFilesChange?.();
      onMappingSaved?.();
      if (payload.motor_limits?.changed?.length) await onMotorLimitsChange?.(payload.motor_limits.changed);
      return true;
    } catch (error) {
      if (isMappingRevisionConflict(error?.message || error)) {
        await resolveMappingRevisionConflict(error?.message || error);
        return false;
      }
      setMappingMessage(`매핑 저장 실패: ${error?.message || error}`);
      return false;
    } finally {
      mappingLoading = false;
      renderMappingPanel();
    }
  }

  async function resetCurrentMapping() {
    const label = selectedMappingId || mappingDraft.name || '현재 조인트 매핑';
    const confirmed = await showConfirm(
      `${label}의 저장하지 않은 편집 내용을 버립니다.\n`
      + '저장된 파일이 있으면 디스크에서 다시 불러옵니다.',
      { title: '조인트 매핑 되돌리기', confirmLabel: '편집 내용 버리기', tone: 'warning' },
    );
    if (!confirmed) return;
    if (selectedMappingId) {
      await selectMapping(selectedMappingId);
      return;
    }
    mappingDraft = emptyMappingDraft();
    mappingMotionFileDetail = null;
    mappingValidation = null;
    mappingDirty = false;
    mappingRevisionConflict = false;
    setMappingMessage(`${label}의 저장하지 않은 편집 내용을 버렸습니다`);
    renderMappingPanel();
  }

  async function refreshMappingAfterReconnect() {
    if (!selectedMappingId) {
      // 고른 것이 없으면 **목록부터** 다시 읽는다 · §6-236
      //
      // 전에는 여기서 그냥 나갔다 · 「모터 설정」을 적용하면 웹 서버가
      // 다시 뜨는데, 그때 고른 매핑이 없으면 아무것도 안 읽었다 · 「편집할
      // 매칭」과 「매핑 이름」이 **빈 채로 남았다** · 프로젝트에 파일이
      // 멀쩡히 있는데도 그랬다 · 「목록 새로고침」을 누르기 전까지 그대로다.
      //
      // 고른 것이 없다는 말은 **읽을 것이 없다는 말이 아니다** · 목록을
      // 읽으면 첫 파일이 자동으로 잡힌다.
      await loadMappings();
      return;
    }
    if (!mappingDirty) {
      await selectMapping(selectedMappingId);
      return;
    }
    try {
      const payload = await fetchMotionMapping(selectedMappingId);
      const currentRevision = mappingFileRevision(payload.file);
      if (currentRevision && currentRevision !== mappingRevision) {
        mappingRevisionConflict = true;
        setMappingMessage(
          '프로그램 재연결 후 저장된 설정 변경을 확인했습니다 · '
          + '편집 내용은 유지 중이며 저장 전 저장된 내용을 다시 불러와야 합니다',
        );
      }
    } catch (error) {
      if (!error?.staleProjectResponse) {
        setMappingMessage(`재연결 후 조인트 매핑 확인 실패: ${error?.message || error}`);
      }
    }
  }

  function updateMappingRow(rowIndex, field, value, checked = false) {
    const row = mappingDraft.mappings[Number(rowIndex)];
    if (!row) return;
    if (field === 'motion_id') {
      row.motion_id = String(value || '').trim();
    } else if (field === 'enabled' || field === 'invert') {
      row[field] = Boolean(checked);
    } else if (field === 'motor_ref') {
      const selectionValue = String(value || '');
      const motor = motorForSelectionValue(selectionValue);
      row.motor_ref = selectionValue.toLowerCase().startsWith('axis:')
        ? ''
        : selectionValue;
      row.motor_axis = motor ? Number(motor.controller_index) : null;
    } else if (field === 'initial_mode') {
      row.initial_mode = ['manual', 'first_frame'].includes(value) ? value : 'reference';
      if (row.initial_mode === 'first_frame') {
        const firstValue = firstMotionValueFor(row.motion_id);
        if (firstValue !== null) row.initial_motion_position_deg = firstValue;
      }
      // 기준점 = 모션 0° · 칸에도 0 을 보여 준다
      if (row.initial_mode === 'reference') row.initial_motion_position_deg = 0.0;
    } else if (field === 'max_velocity_deg_s' || field === 'max_acceleration_deg_s2') {
      // 비우면 검사 안 함 · 칸 자체를 지운다 (수정 목록 5-2)
      const number = Number(value);
      if (String(value ?? '').trim() === '' || !Number.isFinite(number) || number <= 0) delete row[field];
      else row[field] = number;
    } else if (
      field === 'gear_ratio'
      || field === 'reference_position_deg'
      || field === 'motion_lower_deg'
      || field === 'motion_upper_deg'
      || field === 'initial_motion_position_deg'
      || field === 'initial_move_time_sec'
    ) {
      const number = Number(value);
      const fallback = field === 'scale' || field === 'gear_ratio' ? 1.0 : field === 'initial_move_time_sec' ? 5.0 : 0.0;
      row[field] = Number.isFinite(number) ? number : fallback;
    }
    mappingValidation = null;
    markMappingDirty();
    renderMappingPanel();
  }

  function captureReferencePosition(rowIndex) {
    const row = mappingDraft.mappings[Number(rowIndex)];
    if (!row) return;
    const motionId = String(row.motion_id || '');
    const scope = getLatestState()?.project_scope || {};
    if (scope.runtime_matches_selected !== true || scope.motor_config_applied !== true) {
      setMappingMessage(`현재 프로젝트 모터 설정을 적용·재시작한 뒤 기준점을 캡처하세요: 조인트 이름 ${motionId}`);
      return;
    }
    const motor = motorForMapping(row);
    const position = motorPositionDeg(motor);
    if (position === null) {
      setMappingMessage(`현재 위치를 읽을 수 없습니다: 조인트 이름 ${motionId}`);
      return;
    }
    row.reference_position_deg = position;
    row.reference_enabled = true;
    mappingValidation = null;
    markMappingDirty();
    setMappingMessage(`조인트 이름 ${motionId} 기준점 캡처: ${formatNumber(position, 3)} deg`);
    renderMappingPanel();
  }

  /** 다이얼에서 찍은 모터 위치를 조인트 매핑에 저장한다 · 2026-10-02
   *
   * kind · 'reference' = 기준점(모션 0°) · 'upper' = + limit · 'lower' = − limit
   * (+/− 는 **모터** 방향 · 다이얼이 모터 deg 로 움직이므로)
   *
   * 끝 → 모션 deg 환산 · motion = (motor − ref) ÷ (gear·scale·sign) − offset ·
   * 방향 반전(sign<0)이면 모터 + limit 이 모션 최소가 된다 · 경계는 안쪽으로 0.0001°
   * 반올림해 모터 리밋과 정확히 같은 값을 넘어서는 일이 없게 한다.
   *
   * 저장 안 한 편집이 있으면 거절한다 · 그것까지 같이 저장되면 안 된다.
   */
  async function saveCapturedPoint(axis, kind, motorDeg) {
    if (mappingDirty) {
      return {
        success: false,
        message: '조인트 매핑에 저장하지 않은 편집이 있습니다 · 먼저 저장하거나 되돌리세요',
      };
    }
    const rows = Array.isArray(mappingDraft?.mappings) ? mappingDraft.mappings : [];
    const row = rows.find((entry) => (
      entry?.enabled !== false && Number(entry?.motor_axis) === Number(axis)
    ));
    if (!row) {
      return { success: false, message: `${axis}번 모터에 연결된 조인트 이름이 없습니다 · 조인트 매핑에서 먼저 연결하세요` };
    }
    const scope = getLatestState()?.project_scope || {};
    if (scope.runtime_matches_selected !== true || scope.motor_config_applied !== true) {
      return { success: false, message: '현재 프로젝트 모터 설정을 적용·재시작한 뒤 찍을 수 있습니다' };
    }
    const position = Number(motorDeg);
    if (!Number.isFinite(position)) {
      return { success: false, message: '현재 모터 위치를 읽을 수 없습니다' };
    }
    const motionId = String(row.motion_id || '');
    if (kind === 'reference') {
      row.reference_position_deg = position;
      row.reference_enabled = true;
    } else {
      // 식은 `joint_mapping.js` 하나 · 수정 목록 6
      const factor = mappingGain(row);
      if (!factor) return { success: false, message: '감속·기어비·배율이 0이라 환산할 수 없습니다' };
      const motion = motorToJoint(row, position, 'deg');
      const motorUpper = kind === 'upper';
      const setsMotionUpper = motorUpper === (factor > 0);
      if (setsMotionUpper) {
        row.motion_upper_deg = Math.floor(motion * 10000) / 10000;
      } else {
        row.motion_lower_deg = Math.ceil(motion * 10000) / 10000;
      }
      const lower = Number(row.motion_lower_deg);
      const upper = Number(row.motion_upper_deg);
      if (Number.isFinite(lower) && Number.isFinite(upper) && lower > upper) {
        await selectMapping(selectedMappingId);   // 편집을 되돌린다
        return {
          success: false,
          message: `모션 범위가 뒤집힙니다 (최소 ${formatNumber(lower, 3)} > 최대 ${formatNumber(upper, 3)}) · 반대쪽 limit 을 먼저 다시 지정하세요`,
        };
      }
    }
    mappingValidation = null;
    markMappingDirty();
    renderMappingPanel();
    const saved = await saveCurrentMapping();
    if (!saved) {
      return { success: false, message: el.motionMappingMessage?.textContent || '조인트 매핑 저장 실패' };
    }
    return {
      success: true,
      message: kind === 'reference'
        ? `조인트 이름 ${motionId} 기준점 = 모터 ${formatNumber(position, 3)}°`
        : `조인트 이름 ${motionId} 범위 ${formatNumber(row.motion_lower_deg, 3)} ~ ${formatNumber(row.motion_upper_deg, 3)}°`,
    };
  }

  function resetProjectState() {
    files = [];
    selectedFileId = null;
    selectedFile = null;
    mappingFiles = [];
    selectedMappingId = null;
    mappingRevision = '';
    mappingDraft = emptyMappingDraft();
    registeredMotionFileIdValue = '';
    registeredPlaylistValue = [];
    mappingValidation = null;
    mappingMotionFileDetail = null;
    mappingDirty = false;
    mappingRevisionConflict = false;
    fileLoadToken += 1;
    mappingLoadToken += 1;
    motionRunStatus = null;
    motionRunLastResult = null;
    motionRunGraphFileId = '';
    motionRunGraphHiddenIds.clear();
    setMessage('현재 프로젝트 애니메이션을 불러오세요');
    setMappingMessage('현재 프로젝트 조인트 매핑을 불러오세요');
    setMotionRunMessage('현재 프로젝트 애니메이션을 선택하세요');
    render();
    renderMappingPanel();
    renderMotionRunPanel();
  }

  const fileManager = createMotionFileManager({
    onFilesChanged: (newFiles, projectId) => {
      files = newFiles;
      motionProjectId = String(projectId || '');
      render();
    },
    onFileSelected: (id, file) => { selectedFileId = id; selectedFile = file; render(); },
    onProjectFilesChange: () => onProjectFilesChange?.(),
    setMessage: setMessage,
    setLoading: (l) => {
      loading = l;
      if (l) busy.begin('files', '애니메이션 읽는 중 · 긴 애니는 몇 초 걸립니다');
      else busy.end('files');
      render();
    },
    checkIsFileRegistered: (id) => registeredPlaylistValue.includes(id),
  });

  async function loadFiles(id) { return fileManager.loadFiles(id); }
  async function selectFile(id, token) { return fileManager.selectFile(id, token); }
  async function deleteSelectedFile() { return fileManager.deleteSelectedFile(); }


  async function refreshMotionRunStatus() {
    motionRunLoading = true;
    renderMotionRunPanel();
    try {
      const payload = await fetchMotionRunStatus();
      motionRunStatus = payload.status || motionRunStatus || null;
      motionRunLastResult = payload;
      setMotionRunMessage(payload.message || '재생 상태 갱신 완료');
    } catch (error) {
      setMotionRunMessage(`상태 갱신 실패: ${error?.message || error}`);
    } finally {
      motionRunLoading = false;
      renderMotionRunPanel();
    }
  }

  async function checkCurrentMotionRun() {
    motionRunLoading = true;
    setMotionRunMessage('실행 준비 검사 중');
    renderMotionRunPanel();
    try {
      await ensureMotionRunMotionFileDetail();
      const payload = await checkMotionRun(motionRunPayload());
      motionRunStatus = payload.status || motionRunStatus || null;
      motionRunLastResult = payload;
      setMotionRunMessage(payload.message || (payload.success ? '실행 준비 검사 완료' : '실행 준비 검사 실패'));
    } catch (error) {
      setMotionRunMessage(`실행 준비 검사 실패: ${error?.message || error}`);
    } finally {
      motionRunLoading = false;
      renderMotionRunPanel();
    }
  }

  async function initializeCurrentMotionRun() {
    const hasMotionFile = Boolean(motionRunPayload().motion_file_id);
    const confirmed = await showConfirm(
      hasMotionFile
        ? '매핑된 모터를 초기 위치로 이동합니다.'
        : '애니메이션이 없습니다.\n\n첫 프레임 방식 모터는 모션값 0°로 이동합니다.\n수동 방식 모터는 설정한 초기위치로 이동합니다.\n계속할까요?',
      { title: '초기 위치 이동', confirmLabel: '이동 시작', tone: 'warning' },
    );
    if (!confirmed) return;
    motionRunLoading = true;
    setMotionRunMessage('초기 위치 이동 요청 중');
    renderMotionRunPanel();
    try {
      await ensureMotionRunMotionFileDetail();
      const payload = await initializeMotionRun(motionRunPayload());
      motionRunStatus = payload.status || motionRunStatus || null;
      motionRunLastResult = payload;
      setMotionRunMessage(payload.message || (payload.success ? '초기 위치 이동 시작' : '초기 위치 이동 실패'));
      if (payload.success === false) {
        await showMotionRunFailure(payload.message, '초기 위치 이동 실패');
      } else {
        // 움직이는 도중의 실패(도달 확인 실패 등)는 나중에 상태로 온다 · 그것도 창으로
        initializeWatchUntil = Date.now() + INITIALIZE_WATCH_MS;
        initializeWatchStarted = false;
      }
    } catch (error) {
      const message = error?.message || String(error);
      setMotionRunMessage(`초기 위치 이동 실패: ${message}`);
      await showMotionRunFailure(message, '초기 위치 이동 실패');
    } finally {
      motionRunLoading = false;
      renderMotionRunPanel();
    }
  }

  /** 실행 범위 · 'local'(이 PC) 또는 'group'(참가한 전체 PC).
   *
   * 둘은 같은 모터 경로를 쓰는 배타 관계다 · 그룹이 도는 동안 로컬 실행은
   * 브리지가 거절한다(`coordination_bridge.local_execution_blocker`). 그래서
   * 화면에서도 하나만 고르게 한다 · 같은 이름의 버튼을 두 벌 두지 않는다 · §6-65
   */


  /** 연동 역할 · 참가 여부와 PC 수의 주인은 조정 노드다. */
  function groupRunRole() {
    return groupRun?.role?.() || { joined: false, peerCount: 1, isMaster: false };
  }

  /** 이번 실행의 대상 · 고를 수 없는 것은 골라져 있어도 '이 PC 만' 이다. */
  function motionRunScope() {
    // 실행 화면에는 대상 선택이 없다 · §6-100 · 언제나 이 PC 다
    return 'local';
  }

  /** 버튼 이름을 판정대로 그린다 · 여기서 다시 판단하지 않는다. */
  function renderMotionRunTarget(target) {
    const labels = target.buttons;
    if (el.motionRunInitializeButton) {
      el.motionRunInitializeButton.textContent = labels.initialize;
    }
    if (el.motionRunStartButton) el.motionRunStartButton.textContent = labels.start;
    if (el.motionRunContinuousStartButton) {
      el.motionRunContinuousStartButton.textContent = labels.continuous;
    }
    if (el.motionRunStopButton) el.motionRunStopButton.textContent = labels.stop;
    if (el.motionRunStopAfterButton) {
      el.motionRunStopAfterButton.textContent = labels.stopAfter;
    }
  }

  function groupRunAvailability() {
    return groupRun?.availability?.() || { ok: false, reason: '연동 정보를 받지 못했습니다' };
  }


  async function startCurrentMotionRun(runMode = 'once') {
    const continuous = runMode === 'continuous';
    const confirmed = await showConfirm(
      continuous
        ? '조인트 매핑의 전체 활성 축를 초기 위치로 이동한 뒤 연속 재생을 시작합니다.\n정지 버튼을 누를 때까지 애니메이션을 반복합니다.'
        : '조인트 매핑의 전체 활성 축를 초기 위치로 이동한 뒤 현재 애니메이션을 1회 실행합니다.',
      {
        title: continuous ? '연속 재생 시작' : '1회 재생 시작',
        confirmLabel: '재생 시작',
        tone: 'warning',
      },
    );
    if (!confirmed) return;
    motionRunLoading = true;
    setMotionRunMessage('재생 시작 요청 중');
    renderMotionRunPanel();
    try {
      await ensureMotionRunMotionFileDetail();
      const payload = await startMotionRun({
        ...motionRunPayload(),
        run_mode: runMode,
      });
      motionRunStatus = payload.status || motionRunStatus || null;
      motionRunLastResult = payload;
      setMotionRunMessage(payload.message || (payload.success ? '애니메이션 재생 시작' : '애니메이션 재생 실패'));
      if (payload.success === false) {
        await showMotionRunFailure(payload.message, '애니메이션 재생 실패');
      }
    } catch (error) {
      const message = error?.message || String(error);
      setMotionRunMessage(`애니메이션 재생 실패: ${message}`);
      await showMotionRunFailure(message, '애니메이션 재생 실패');
    } finally {
      motionRunLoading = false;
      renderMotionRunPanel();
    }
  }

  /** 멈췄는데 스케줄이 되돌릴 거라면 그 자리에서 말해 준다 · §6-149
   *
   * 누를 때 한 번만 묻는다 · 상시로 두드리면 보여주려던 안내가 서버를 느리게
   * 만든다 · 실제로 그것 때문에 그룹 실행이 통째로 멈춘 적이 있다(§6-146).
   */
  async function scheduleResumeNote() {
    try {
      return motionScheduleResumeNote(await fetchScheduleStatus());
    } catch (error) {
      return '';                 // 안내를 못 해도 정지 자체는 이미 됐다
    }
  }

  async function stopCurrentMotionRun() {
    motionRunLoading = true;
    setMotionRunMessage('정지 요청 중');
    renderMotionRunPanel();
    try {
      const payload = await stopMotionRun();
      motionRunStatus = payload.status || motionRunStatus || null;
      motionRunLastResult = payload;
      const note = await scheduleResumeNote();
      setMotionRunMessage(
        `${payload.message || '정지 요청 완료'}${note ? ` · ${note}` : ''}`,
      );
    } catch (error) {
      setMotionRunMessage(`정지 요청 실패: ${error?.message || error}`);
    } finally {
      motionRunLoading = false;
      renderMotionRunPanel();
    }
  }

  async function stopCurrentMotionRunAfterCycle() {
    motionRunLoading = true;
    setMotionRunMessage('현재 회차 후 정지 대기 중');
    renderMotionRunPanel();
    try {
      const payload = await stopMotionRunAfterCycle();
      motionRunStatus = payload.status || motionRunStatus || null;
      motionRunLastResult = payload;
      const note = await scheduleResumeNote();
      setMotionRunMessage(
        `${payload.message || '회차 후 정지 대기 중'}${note ? ` · ${note}` : ''}`,
      );
    } catch (error) {
      setMotionRunMessage(`정지 요청 실패: ${error?.message || error}`);
    } finally {
      motionRunLoading = false;
      renderMotionRunPanel();
    }
  }

  function motionAutomationSettings() {
    const repeatMode = String(
      el.motionAutomationRepeatMode?.value
      || motionRunStatus?.automation?.repeat_mode
      || 'reinitialize',
    );
    const dwellSec = Number(el.motionAutomationDwellSec?.value);
    const motionFileId = motionRunSelectedMotionFile()?.filename
      || motionRunStatus?.automation?.motion_file_id
      || '';
    const mappingFileId = selectedMappingFile()?.filename
      || selectedMappingId
      || motionRunStatus?.automation?.mapping_file_id
      || '';
    return {
      repeat_mode: repeatMode,
      dwell_sec: Number.isFinite(dwellSec) && dwellSec >= 0 ? dwellSec : 0,
      motion_file_id: motionFileId,
      mapping_file_id: mappingFileId,
    };
  }

  /** 반복 방식·대기 시간을 저장한다 · 부팅 자동 재생은 없앴다 · §6-134 */
  async function saveMotionAutomation() {
    motionRunLoading = true;
    renderMotionRunPanel();
    try {
      const payload = await configureMotionAutomation(motionAutomationSettings());
      motionRunStatus = payload.status || motionRunStatus || null;
      motionRunLastResult = payload;
      if (payload.success === false) {
        await showAlert(payload.message || '자동 반복 설정 실패', {
          title: '자동 반복 설정',
          tone: 'danger',
        });
      }
    } catch (error) {
      await showAlert(error?.message || String(error), {
        title: '자동 반복 설정 실패',
        tone: 'danger',
      });
    } finally {
      motionRunLoading = false;
      renderMotionRunPanel();
    }
  }


  function bindEvents() {
    bindAnimationDropZone();
    el.motionRunAxisRows?.addEventListener('change', (event) => {
      handleLiveOverrideEdit(event.target);
    });
    if (el.motionFileRows) {
      el.motionFileRows.addEventListener('click', (event) => {
        const target = event.target.closest('[data-motion-file-id]');
        if (!target) return;
        selectFile(target.dataset.motionFileId);
      });
    }
    el.registerMotionFileButton?.addEventListener('click', registerSelectedMotionFile);
    el.motionPlaylistPanel?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-playlist-action]');
      if (!button || button.disabled) return;
      editPlaylist(button.dataset.playlistAction, Number(button.dataset.playlistIndex));
    });
    el.unregisterMotionFileButton?.addEventListener('click', unregisterSelectedMotionFile);
    el.downloadMotionFileButton?.addEventListener('click', downloadSelectedMotionFile);
    el.previewMotionFileButton?.addEventListener('click', previewSelectedMotionFile);
    if (el.deleteMotionFileButton) {
      el.deleteMotionFileButton.addEventListener('click', deleteSelectedFile);
    }
    if (el.motionRunCheckButton) {
      el.motionRunCheckButton.addEventListener('click', checkCurrentMotionRun);
    }
    // **이 버튼들은 언제나 이 PC 것이다** · §6-100
    //
    // 전에는 같은 버튼이 `실행 대상` 에 따라 이 PC 를 돌리기도, 참가한 PC
    // 전부에게 시작 신호를 보내기도 했다 · 모터가 실제로 움직이는 버튼에서
    // 그 애매함은 위험하다 · 그룹 실행은 `PC 연동 설정` 탭에 따로 있다.
    if (el.motionRunInitializeButton) {
      el.motionRunInitializeButton.addEventListener(
        'click', () => initializeCurrentMotionRun(),
      );
    }
    // 수동 조작 화면 · 새 경로 없이 같은 함수 · 같은 확인 창 · 수정 목록 58
    el.manualInitializeButton?.addEventListener('click', () => initializeCurrentMotionRun());
    if (el.motionRunStartButton) {
      el.motionRunStartButton.addEventListener(
        'click', () => startCurrentMotionRun('once'),
      );
    }
    if (el.motionRunContinuousStartButton) {
      el.motionRunContinuousStartButton.addEventListener(
        'click', () => startCurrentMotionRun('continuous'),
      );
    }
    if (el.motionRunStopButton) {
      el.motionRunStopButton.addEventListener(
        'click', () => stopCurrentMotionRun(),
      );
    }
    if (el.motionRunStopAfterButton) {
      el.motionRunStopAfterButton.addEventListener(
        'click', () => stopCurrentMotionRunAfterCycle(),
      );
    }
    if (el.motionRunRefreshButton) {
      el.motionRunRefreshButton.addEventListener('click', refreshMotionRunStatus);
    }
    // 반복 방식은 고치는 즉시 저장한다 · 전에는 「부팅 시 자동 재생」이
    // 켜져 있을 때만 저장돼서, 꺼 두면 고친 값이 다음 실행에 안 갔다 · §6-134
    el.motionAutomationRepeatMode?.addEventListener('change', () => {
      renderMotionAutomation();
      void saveMotionAutomation();
    });
    el.motionAutomationDwellSec?.addEventListener('change', () => {
      void saveMotionAutomation();
    });
    if (el.motionRunGraphAxisToggles) {
      el.motionRunGraphAxisToggles.addEventListener('click', (event) => {
        const button = event.target.closest('button');
        if (!button) return;
        event.preventDefault();
        const file = motionRunSelectedMotionFile();
        const series = Array.isArray(analysisOf(file)?.graph_series)
          ? analysisOf(file).graph_series
          : [];
        if (button.dataset.motionRunGraphAll === 'true') {
          const allVisible = series.every((item) => !motionRunGraphHiddenIds.has(String(item.motion_id)));
          motionRunGraphHiddenIds.clear();
          if (allVisible) {
            series.forEach((item) => motionRunGraphHiddenIds.add(String(item.motion_id)));
          }
        } else if (button.dataset.motionRunGraphId !== undefined) {
          const motionId = String(button.dataset.motionRunGraphId);
          if (motionRunGraphHiddenIds.has(motionId)) motionRunGraphHiddenIds.delete(motionId);
          else motionRunGraphHiddenIds.add(motionId);
        }
        renderMotionRunGraphAxisToggles();
        renderMotionRunGraph();
      });
    }
    if (el.motionRunInitialMoveTime) {
      el.motionRunInitialMoveTime.addEventListener('change', () => {
        renderMotionRunPanel();
        renderMappingPanel();
      });
    }
    el.addMotionIdButton?.addEventListener('click', addMotionId);
    el.generateMotionIdsButton?.addEventListener('click', generateMotionIdsFromMotors);
    el.resetMotionMappingButton?.addEventListener('click', resetCurrentMapping);
    if (el.motionMappingRows) {
      el.motionMappingRows.addEventListener('click', (event) => {
        const action = event.target?.dataset?.motionMappingAction;
        if (!action) return;
        const row = event.target.closest('tr[data-mapping-index]');
        if (!row) return;
        const rowIndex = Number(row.dataset.mappingIndex);
        const mappingRow = mappingDraft.mappings[rowIndex];
        if (!mappingRow) return;
        if (action === 'capture_reference') {
          captureReferencePosition(rowIndex);
        } else if (action === 'delete') {
          const deletedMotionId = String(mappingRow.motion_id || '');
          mappingDraft.mappings.splice(rowIndex, 1);
          mappingValidation = null;
          markMappingDirty();
          setMappingMessage(`조인트 이름 ${deletedMotionId} 삭제 완료`);
          renderMappingPanel();
        }
      });
      el.motionMappingRows.addEventListener('change', (event) => {
        const field = event.target?.dataset?.motionMappingField;
        if (!field) return;
        const row = event.target.closest('tr[data-mapping-index]');
        if (!row) return;
        updateMappingRow(row.dataset.mappingIndex, field, event.target.value, event.target.checked);
      });
    }
  }

  return {
    bindEvents,
    resetProjectState,
    /** 조인트 매핑에 저장 안 한 편집이 있나 · 상단 설정 상태 배지가 본다 */
    hasUnsavedMappingChanges: () => Boolean(mappingDirty),
    /** 맨 아래 「저장」이 부른다 · 편집이 없으면 아무것도 안 한다 · 검증 → 저장 */
    saveMappingIfDirty: async () => (mappingDirty ? saveCurrentMapping() : null),
    fetchFiles: async () => {
      await loadFiles();
      await loadMappings();
    },
    refreshMotionFiles: () => loadFiles(),
    openProjectFile: async (category, fileName) => {
      if (category === 'motions') await loadFiles(fileName);
      if (category === 'motion_axis_matching') await loadMappings(fileName);
    },
    refreshMappingAfterReconnect,
    render,
    renderRuntimeState,
    showTab: () => {
      renderMotionTabs();
      render();
    },
    saveCapturedPoint,
    /** 이 모터(축)에 연결된 조인트 행 · 조그의 조인트 deg 변환에 쓴다 · P4 */
    jointRowForAxis: (axis) => {
      const rows = Array.isArray(mappingDraft?.mappings) ? mappingDraft.mappings : [];
      return rows.find((row) => (
        row?.enabled !== false && Number(row?.motor_axis) === Number(axis)
      )) || null;
    },
  };
}
