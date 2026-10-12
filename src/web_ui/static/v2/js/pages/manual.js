/** UI v2 · 수동 조작 · 모터 하나씩(다이얼 · 목표 위치 · 기준점·한계 캡처 · 서보) · 페이더(전체) (설계안 2026-10-09)
 *
 * 수동 모드에서만 움직인다 · 최종 판정은 서버(run_mode_gate · 범위 미확인 manual_range_gate · supervisor) · 화면은 먼저 알린다.
 * 정지 · 서보 끄기 · 알람 해제는 늘 된다. 다이얼은 늘 꺼진 채 시작(수정 목록 84) · 켜도 다이얼만 · 자리는 그대로(41).
 * 실시간 값(위치 · 다이얼 남은 양)은 0.05초마다 그 칸 글자만 바꾼다 · 끄는 중에 화면 전체를 다시 그리지 않는다.
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import * as act from '../actions.js';
import {
  PX_PER_STEP, FINE_FACTOR, SEND_PERIOD_MS, WHEEL_PX_PER_STEP,
  addDelta, markSent, nextTarget, pending, releaseDue, startSession, wheelPixels,
} from '../dial_session.js';
import { ManualStream } from '../manual_stream.js';
import {
  autoConfirmRange, draftToRow, jointToMotor, motorForRow, motorRefFor, motorToJoint, previewRow, rowToDraft,
} from '../mapping_model.js';
import { registeredPlaylist, signedDeg } from '../play_model.js';

const DEG = 180 / Math.PI;
const RAD = Math.PI / 180;

const ui = {
  mode: 'axis', axis: null, unit: 'joint', dialOn: false, step: 1, goal: '',
  mapping: null, mappingDoc: null, fileId: '', revision: '', busy: '', message: '',
  session: null, faders: new Map(), wheelAcc: 0, dragX: null,
};
let ctx = { state: null, changed: () => {} };
let loop = null;
const stream = new ManualStream({
  onResult: (result) => {
    if (result.success === false && result.message) {
      ui.message = result.message;
      if (ui.session) endSession(false);
      ctx.changed();
    }
  },
  onClose: (reason) => {
    if (reason) ui.message = reason;
    ui.session = null;
    ui.faders.clear();
    ctx.changed();
  },
});

/* ---------- 읽기 ---------- */

export async function loadManual(state, changed) {
  ctx = { state, changed };
  try {
    const list = await api('GET', '/api/motion-mappings');
    const files = Array.isArray(list?.files) ? list.files : [];
    const fileId = files.some((f) => f.id === list?.active_file_id) ? list.active_file_id : (files[0]?.id || '');
    if (fileId) {
      const data = await api('GET', `/api/motion-mappings/${encodeURIComponent(fileId)}`);
      if (data?.mapping) {
        ui.mappingDoc = data.mapping;
        ui.mapping = (data.mapping.mappings || []).map(rowToDraft);
        ui.fileId = fileId;
        ui.revision = String(data.file?.mapping_revision || data.file?.revision || '');
      }
    } else {
      ui.mapping = [];
    }
  } catch { /* 옛 매핑 그대로 · 다음 주기에 다시 (§6-237) */ }
  changed();
}

/** 이 PC 모터 + 그 모터의 매핑 줄 */
function axes(state) {
  const motors = (state.snap?.motion_state?.motors || []).map((m) => ({
    raw: m,
    axis: Number(m.controller_index),
    ac: m.motor_type !== 'dynamixel',
    ref: motorRefFor(m),
    name: String(m.name || m.display_name || ''),
    detected: m.state === 'detected',
    servoOn: m.servo_on === true,
    fault: m.fault === true,
    position: m.position_rad === null || m.position_rad === undefined ? null : Number(m.position_rad) * DEG,
    lower: Number.isFinite(Number(m.lower)) ? Number(m.lower) : -Infinity,
    upper: Number.isFinite(Number(m.upper)) ? Number(m.upper) : Infinity,
  }));
  const rows = (ui.mapping || []).filter((row) => row.enabled !== false);
  return motors.map((motor) => {
    const row = rows.find((r) => motorForRow(r, motors) === motor) || null;
    const joint = row && motor.position !== null ? motorToJoint(row, motor.position) : null;
    return { ...motor, row, label: row?.motion_id || motor.name || `${motor.axis}번 모터`, joint };
  }).sort((a, b) => a.axis - b.axis);
}

/** 모터 deg 한계 · 드라이브 한계와 매핑 범위(모터로 바꾼 것) 중 좁은 쪽 */
function motorLimits(item) {
  let lower = item.lower;
  let upper = item.upper;
  if (item.row) {
    const view = previewRow(item.row);
    if (Number.isFinite(view.motorMin)) lower = Math.max(lower, view.motorMin);
    if (Number.isFinite(view.motorMax)) upper = Math.min(upper, view.motorMax);
  }
  return { lower, upper };
}

function gain(item) {
  return item.row ? Number(item.row.scale ?? 1) * (item.row.invert ? -1 : 1) * Number(item.row.gear_ratio || 1) : 1;
}

/** 움직일 수 없는 이유 · 먼저 걸리는 것 하나 · 해결 버튼 종류 */
/** 서버 `motion_common.run_state.IDLE_STATES` 와 같다 · 여기 없으면 도는 중 */
const RUN_IDLE = new Set(['idle', 'off', 'ready', 'stopped', 'completed', 'motion_completed', 'error', 'blocked', 'initialized']);

export function manualBlocker(state, item) {
  const snap = state.snap || {};
  if (snap.safety_status?.emergency_latched) return { text: '긴급 정지 상태입니다. 프로그램을 다시 시작해야 해제됩니다.', fix: 'restart' };
  const mode = state.sched?.run_mode;
  if (mode && mode !== 'manual') return { text: `지금은 ${mode === 'off' ? '끔' : '스케줄'} 모드입니다. 수동 조작은 「수동」 모드에서만 할 수 있습니다.`, fix: 'mode-manual' };
  // 서버 run_mode_gate.manual_motion_block_reason 과 같은 문구 · 초기 위치 대기 · 재생 중이면 정지 뒤에만 (2026-10-12)
  const runState = String(snap.motion_run_status?.state || '');
  if (runState === 'initialized') return { text: '초기 위치에서 대기 중입니다. 「정지」를 누른 뒤 수동 조작을 하세요.', fix: 'stop' };
  if (runState && !RUN_IDLE.has(runState)) return { text: '재생 중입니다. 「정지」를 누른 뒤 수동 조작을 하세요.', fix: 'stop' };
  if (snap.mapping_range_blocker) return { text: `수동 조작 불가 · ${snap.mapping_range_blocker}`, fix: 'open-mapping' };
  if (snap.minas_absolute_blocker) return { text: String(snap.minas_absolute_blocker), fix: 'open-motors' };
  if (snap.motor_action_blocker) return { text: String(snap.motor_action_blocker) };
  if (!item) return { text: '모터를 선택하세요' };
  if (!item.detected) return { text: `${item.axis}번 모터 통신 없음` };
  if (item.fault) return { text: `${item.axis}번 모터 알람 · 오류를 초기화한 뒤 서보를 켜세요`, fix: 'reset' };
  if (item.ac && !item.servoOn) return { text: `${item.axis}번 서보가 꺼져 있습니다`, fix: 'servo-on' };
  if (!item.row) return { text: `조인트 매핑에 ${item.axis}번 모터를 쓰는 줄이 없거나 「사용」이 꺼져 있습니다. 매핑에 없는 모터는 수동 조작할 수 없습니다.`, fix: 'open-mapping' };
  return null;
}

function fixButton(blocker, item, changed) {
  const map = {
    'mode-manual': ['수동 모드로 전환', () => act.setRunMode('manual')],
    stop: ['정지', act.stopAll],
    restart: ['프로그램 다시 시작', act.restartProgram],
    'open-mapping': ['조인트 매핑 열기', () => { location.hash = '#/mapping'; }],
    'open-motors': ['모터 설정 열기', () => { location.hash = '#/maintain-motors'; }],
    reset: ['오류 초기화', async () => { await act.servoControl(item, 'reset'); changed(); }],
    'servo-on': ['서보 켜기', async () => { await act.servoControl(item, 'on'); changed(); }],
  };
  const entry = map[blocker?.fix];
  return entry ? h('button', { class: 'btn btn-warn', type: 'button', onclick: entry[1] }, entry[0]) : null;
}

/* ---------- 실시간 고리 · 50 ms ---------- */

function ensureLoop() {
  if (loop) return;
  loop = setInterval(tick, SEND_PERIOD_MS);
}

function stopLoopIfIdle() {
  if (!ui.session && !ui.faders.size && loop) { clearInterval(loop); loop = null; }
}

function tick() {
  if (!location.hash.startsWith('#/manual')) { endSession(true); releaseAllFaders(); stopLoopIfIdle(); return; }
  const list = axes(ctx.state);
  const now = performance.now();
  if (ui.session) {
    const item = list.find((a) => a.axis === ui.session.axis);
    const value = nextTarget(ui.session);
    if (stream.target(ui.session.axis, value * RAD)) markSent(ui.session, value);
    if (releaseDue(ui.session, now, item?.position)) endSession(true);
  }
  for (const [axis, fader] of ui.faders) {
    const item = list.find((a) => a.axis === axis);
    if (!item?.row) continue;
    const motorDeg = jointToMotor(item.row, fader.joint);
    stream.target(axis, motorDeg * RAD, { motion_id: item.row.motion_id, motion_rad: fader.joint * RAD });
  }
  updateLive(list);
  stopLoopIfIdle();
}

/** 실시간 칸만 바꾼다 · data-live="pos|motor|pending" data-axis */
function updateLive(list) {
  for (const node of document.querySelectorAll('[data-live]')) {
    const item = list.find((a) => a.axis === Number(node.dataset.axis));
    if (!item) continue;
    const kind = node.dataset.live;
    if (kind === 'joint') node.textContent = item.joint === null ? '-' : `${signedDeg(item.joint, 2)}°`;
    else if (kind === 'motor') node.textContent = item.position === null ? '-' : `모터 ${signedDeg(item.position, 1)}°`;
    else if (kind === 'pending') {
      const left = ui.session && ui.session.axis === item.axis && item.position !== null ? ui.session.target - item.position : 0;
      node.textContent = ui.session?.axis === item.axis ? `남은 이동 ${signedDeg(left / (ui.unit === 'joint' && item.row ? gain(item) : 1), 3)}°${ui.session.hitLimit ? ` · ${ui.session.hitLimit} 도달` : ''}` : '대기';
    } else if (kind === 'slider' && !ui.faders.has(item.axis) && item.joint !== null && document.activeElement !== node) {
      node.value = String(item.joint);
    }
  }
}

/* ---------- 다이얼 ---------- */

async function dialInput(item, steps, fine = false) {
  const blocker = manualBlocker(ctx.state, item);
  if (!ui.dialOn || blocker || !item || item.position === null) return;
  const stepDeg = Number(ui.step);
  if (!(stepDeg > 0 && stepDeg <= 360)) { ui.message = '한 칸 값은 0.001 ~ 360° 사이여야 합니다'; ctx.changed(); return; }
  const motorDelta = steps * stepDeg * (fine ? FINE_FACTOR : 1) * (ui.unit === 'joint' && item.row ? gain(item) : 1);
  const now = performance.now();
  if (!ui.session || ui.session.axis !== item.axis) {
    endSession(true);
    releaseAllFaders();
    try {
      await stream.open({ mapping_file_id: ui.fileId, base_mapping_revision: ui.revision });
    } catch (error) {
      ui.message = error.message;
      ctx.changed();
      return;
    }
    const limits = motorLimits(item);
    ui.session = startSession({ axis: item.axis, position: item.position, lower: limits.lower, upper: limits.upper, now });
  }
  addDelta(ui.session, motorDelta, now);
  ui.message = '';
  ensureLoop();
}

function endSession(release) {
  if (!ui.session) return;
  if (release) stream.release([ui.session.axis]);
  ui.session = null;
}

function releaseAllFaders() {
  if (!ui.faders.size) return;
  stream.release([...ui.faders.keys()]);
  ui.faders.clear();
}

async function cancelMotion() {
  endSession(true);
  releaseAllFaders();
  await act.motionStop();
}

/* ---------- 목표 위치 · 범위 복귀 ---------- */

async function moveTo(item, changed) {
  const blocker = manualBlocker(ctx.state, item);
  if (blocker) { toast(blocker.text, 'warn'); return; }
  if (ui.session) { toast('다이얼로 이동 중입니다. 이동이 끝난 뒤 다시 시도하세요.', 'warn'); return; }
  const value = Number(ui.goal);
  if (ui.goal === '' || !Number.isFinite(value)) { toast('목표 위치를 숫자로 입력하세요', 'warn'); return; }
  const motorDeg = ui.unit === 'joint' && item.row ? jointToMotor(item.row, value) : value;
  const limits = motorLimits(item);
  if (motorDeg < limits.lower - 1e-6 || motorDeg > limits.upper + 1e-6) {
    toast(`범위를 벗어났습니다 · 모터 ${signedDeg(limits.lower, 1)} ~ ${signedDeg(limits.upper, 1)}°`, 'bad');
    return;
  }
  if (item.position !== null && Math.abs(motorDeg - item.position) < 1e-4) { toast('이미 목표 위치에 있습니다', 'ok'); return; }
  const path = item.ac ? '/api/motion-test/ac-servo/action' : '/api/motion-test/dynamixel/action';
  ui.busy = 'move';
  changed();
  try {
    const result = await api('POST', path, { body: { axis: item.axis, target_rad: motorDeg * RAD }, timeoutMs: 15000 });
    toast(result?.message || '천천히 이동합니다', 'ok');
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = '';
    changed();
  }
}

async function recoverRange(item, changed) {
  const bound = item.position < item.lower ? item.lower : item.upper;
  const ok = await confirmBox({ title: '범위 안으로 복귀', body: `${item.axis}번 모터가 운전 한계를 벗어나 있습니다(현재 모터 ${signedDeg(item.position, 2)}°).\n가장 가까운 한계(${signedDeg(bound, 2)}°)까지 한 번에 이동합니다. 주변에 사람이나 물건이 없는지 확인하세요.`, confirmLabel: '복귀', tone: 'warning' });
  if (!ok) return;
  try {
    const result = await api('POST', item.ac ? '/api/motion-test/ac-servo/action' : '/api/motion-test/dynamixel/action',
      { body: { axis: item.axis, target_rad: bound * RAD, range_recovery: true }, timeoutMs: 15000 });
    toast(result?.message || '복귀합니다', 'ok');
  } catch (error) { toast(error.message || String(error), 'bad'); }
  changed();
}

/* ---------- 여기를 하한 · 기준점 · 상한으로 ---------- */

async function capture(item, kind, changed) {
  if (!item.row || item.position === null) return;
  const scope = ctx.state.snap?.project_scope || {};
  if (!(scope.runtime_matches_selected && scope.motor_config_applied)) {
    toast('이 프로젝트의 모터 설정을 장비에 적용해야 캡처할 수 있습니다', 'warn');
    return;
  }
  const row = { ...item.row };
  const motorDeg = Math.round(item.position * 1e4) / 1e4;
  let text;
  if (kind === 'reference') {
    row.reference_position_deg = motorDeg;
    row.reference_enabled = true;
    text = `${row.motion_id} 기준점(조인트 0°)을 현재 모터 위치 ${signedDeg(motorDeg, 2)}°로`;
  } else {
    const joint = motorToJoint(row, motorDeg);
    if (joint === null) return;
    // 안쪽으로 반올림 · 하한은 올림 · 상한은 내림
    if (kind === 'lower') row.motion_lower_deg = Math.ceil(joint * 1e4) / 1e4;
    else row.motion_upper_deg = Math.floor(joint * 1e4) / 1e4;
    if (Number(row.motion_lower_deg) > Number(row.motion_upper_deg)) { toast('하한이 상한보다 커집니다. 위치를 확인하세요.', 'bad'); return; }
    autoConfirmRange(row);
    text = `${row.motion_id} ${kind === 'lower' ? '하한' : '상한'}을 현재 위치 ${signedDeg(joint, 3)}°로`;
  }
  const ok = await confirmBox({ title: '조인트 매핑에 저장', body: `${text} 저장합니다.\n\n저장한 뒤 운전 한계(소프트 리밋)도 새 값으로 바꿀지 이어서 확인합니다(장비에 적용 및 모터 재시작).`, confirmLabel: '저장' });
  if (!ok) return;
  const rows = ui.mapping.map((r) => (r === item.row ? row : r));
  try {
    const result = await api('POST', '/api/motion-mappings', {
      body: { file_id: ui.fileId, base_mapping_revision: ui.revision, mapping: { name: ui.mappingDoc?.name || ui.fileId.replace(/\.ya?ml$/, ''), mappings: rows.map((r) => draftToRow(r)) } },
      timeoutMs: 20000,
    });
    toast(result?.message || '저장했습니다', 'ok');
    await loadManual(ctx.state, changed);
    if (await act.confirmApplyMotorConfig('운전 한계(소프트 리밋)도 새 기준으로 바꾸려면 장비에 적용하고 모터를 재시작해야 합니다.')) await act.applyMotorConfig();
    else toast('운전 한계가 아직 적용되지 않았습니다. 「모터 설정」에서 「저장 후 장비에 적용」을 누르세요.', 'warn');
  } catch (error) {
    toast(error.message || String(error), 'bad');
  }
}

/* ---------- 그리기 ---------- */

function rangeBar(item) {
  if (!item.row) return null;
  const lower = Number(item.row.motion_lower_deg);
  const upper = Number(item.row.motion_upper_deg);
  const span = upper - lower || 1;
  const pos = item.joint === null ? null : Math.max(0, Math.min(1, (item.joint - lower) / span));
  const zero = Math.max(0, Math.min(1, (0 - lower) / span));
  return h('div', { class: 'range-bar', 'aria-hidden': 'true' },
    h('div', { class: 'range-zero', style: { left: `${zero * 100}%` } }),
    pos === null ? null : h('div', { class: 'range-pos', style: { left: `${pos * 100}%` } }),
    h('div', { class: 'range-labels mono' }, h('span', { text: `${signedDeg(lower, 1)}° 하한` }), h('span', { text: '0 기준점' }), h('span', { text: `${signedDeg(upper, 1)}° 상한` })));
}

function axisPanel(state, changed, item) {
  const blocker = manualBlocker(state, item);
  const disabled = Boolean(blocker);
  const jointUnit = ui.unit === 'joint' && Boolean(item.row);
  const scope = state.snap?.project_scope || {};
  const canCapture = Boolean(item.row) && scope.runtime_matches_selected === true && scope.motor_config_applied === true && !ui.session;
  const outside = item.position !== null && (item.position < item.lower || item.position > item.upper);
  const dial = h('div', {
    class: `dial${ui.dialOn && !disabled ? '' : ' locked'}`, tabindex: '0', role: 'slider',
    'aria-label': '다이얼 (드래그, 휠, ← → 키)', 'aria-disabled': String(!ui.dialOn || disabled),
    onpointerdown: (e) => { if (!ui.dialOn || disabled) return; ui.dragX = e.clientX; e.currentTarget.setPointerCapture(e.pointerId); },
    onpointermove: (e) => {
      if (ui.dragX === null) return;
      const moved = e.clientX - ui.dragX;
      const steps = Math.trunc(moved / PX_PER_STEP);
      if (steps) { ui.dragX += steps * PX_PER_STEP; dialInput(item, steps, e.shiftKey); }
    },
    onpointerup: () => { ui.dragX = null; },
    onpointercancel: () => { ui.dragX = null; },
    onwheel: (e) => {
      if (!ui.dialOn || disabled) return;
      e.preventDefault();
      ui.wheelAcc += wheelPixels(e);
      const steps = Math.trunc(ui.wheelAcc / WHEEL_PX_PER_STEP);
      if (steps) { ui.wheelAcc -= steps * WHEEL_PX_PER_STEP; dialInput(item, -steps, e.shiftKey); }
    },
    onkeydown: (e) => {
      const dir = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
      if (dir) { e.preventDefault(); dialInput(item, dir, e.shiftKey); }
    },
  }, h('span', { class: 'dial-ticks', 'aria-hidden': 'true' }), h('span', { class: 'dial-hint', text: ui.dialOn ? (disabled ? '조작 불가' : '드래그 · 휠 · ← → 키 (Shift: 1/10 단위)') : '다이얼이 꺼져 있습니다. 위 스위치로 켜세요.' }));
  const hold = (dir) => {
    let timer = null;
    const stop = () => { clearTimeout(timer); clearInterval(timer); timer = null; };
    return {
      onpointerdown: () => { dialInput(item, dir); timer = setTimeout(() => { timer = setInterval(() => dialInput(item, dir), 120); }, 400); },
      onpointerup: stop, onpointerleave: stop, onpointercancel: stop,
    };
  };
  return h('section', { class: 'card axis-panel', 'aria-label': `${item.label} 조작` },
    blocker ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: blocker.text }), fixButton(blocker, item, changed)) : null,
    h('div', { class: 'card-head' }, h('h2', { text: `${item.label} · 현재 위치` }),
      h('div', { class: 'segmented', role: 'group', 'aria-label': '단위' },
        [['joint', '조인트 °'], ['motor', '모터 °']].map(([value, label]) => h('button', {
          class: 'seg', type: 'button', disabled: value === 'joint' && !item.row, 'aria-pressed': String((jointUnit ? 'joint' : 'motor') === value),
          onclick: () => { endSession(true); ui.unit = value; changed(); },
        }, label)))),
    h('div', { class: 'big-pos' },
      h('strong', { class: 'mono', 'data-live': 'joint', 'data-axis': String(item.axis), text: item.joint === null ? '-' : `${signedDeg(item.joint, 2)}°` }),
      h('span', { class: 'mono muted', 'data-live': 'motor', 'data-axis': String(item.axis), text: item.position === null ? '-' : `모터 ${signedDeg(item.position, 1)}°` })),
    rangeBar(item),
    h('div', { class: 'row' },
      ['lower', 'reference', 'upper'].map((kind) => h('button', { class: 'btn btn-mini', type: 'button', disabled: !canCapture,
        title: canCapture ? { lower: '현재 위치를 하한점으로 지정합니다', reference: '현재 위치를 기준점(조인트 0°)으로 지정합니다', upper: '현재 위치를 상한점으로 지정합니다' }[kind] : '조인트 매핑 줄이 있고 모터 설정이 장비에 적용된 상태에서, 다이얼 이동이 끝나 있을 때 사용할 수 있습니다.',
        onclick: () => capture(item, kind, changed) }, { lower: '하한점 지정', reference: '기준점 지정', upper: '상한점 지정' }[kind]))),
    h('p', { class: 'muted small', text: '변경하면 조인트 매핑에 저장되고, 이어서 장비에 적용(모터 재시작)할지 확인합니다.' }),
    outside ? h('div', { class: 'blocker bad' }, dot('bad'), h('span', { class: 'grow', text: '운전 한계를 벗어나 있습니다. 다이얼과 목표 위치 이동을 사용할 수 없습니다.' }),
      h('button', { class: 'btn btn-warn', type: 'button', onclick: () => recoverRange(item, changed) }, '범위 안으로 복귀')) : null,
    h('div', { class: 'field' },
      h('div', { class: 'row' }, h('strong', { text: '움직이기' }),
        h('label', { class: `switch${ui.dialOn ? ' on' : ''}` },
          h('input', { type: 'checkbox', role: 'switch', checked: ui.dialOn, 'aria-label': '다이얼',
            onchange: (e) => { ui.dialOn = e.target.checked; if (!ui.dialOn) endSession(true); changed(); } }),
          h('span', { class: 'switch-track', 'aria-hidden': 'true' })),
        h('span', { class: ui.dialOn ? 'tone-text-ok' : 'muted', text: `다이얼 ${ui.dialOn ? 'ON' : 'OFF'}` })),
      h('div', { class: 'dial-row' },
        h('button', { class: 'btn btn-icon', type: 'button', disabled: !ui.dialOn || disabled, 'aria-label': '한 칸 −', ...hold(-1) }, '◀'),
        dial,
        h('button', { class: 'btn btn-icon', type: 'button', disabled: !ui.dialOn || disabled, 'aria-label': '한 칸 +', ...hold(1) }, '▶')),
      h('div', { class: 'row' },
        h('label', { class: 'inline' }, '한 칸', h('input', { class: 'input num-input mono', type: 'number', min: '0.001', max: '360', step: 'any', value: String(ui.step),
          oninput: (e) => { ui.step = Number(e.target.value); }, onchange: () => { endSession(true); changed(); } }), jointUnit ? '조인트 °' : '모터 °'),
        h('span', { class: 'mono muted small grow', 'data-live': 'pending', 'data-axis': String(item.axis), text: '대기' }))),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: `목표 위치로 이동 (${jointUnit ? '조인트' : '모터'} °)` }),
      h('div', { class: 'row' },
        h('input', { class: 'input mono num-input wide', type: 'number', step: 'any', value: ui.goal, 'aria-label': '목표 위치',
          oninput: (e) => { ui.goal = e.target.value; }, onchange: () => changed() }),
        h('button', { class: 'btn btn-primary', type: 'button', disabled: disabled || ui.busy === 'move' || Boolean(ui.session), onclick: () => moveTo(item, changed) }, '천천히 이동'),
        h('button', { class: 'btn btn-danger', type: 'button', title: '다이얼 · 목표 위치 이동을 모두 멈춥니다', onclick: cancelMotion }, '동작 취소'))),
    h('div', { class: 'field servo-box' },
      h('span', { class: 'field-label', text: `서보 · ${item.label}` }),
      h('div', { class: 'row' },
        dot(item.fault ? 'bad' : item.servoOn ? 'ok' : 'warn'),
        h('span', { class: 'grow', text: `${item.servoOn ? '켜짐' : '꺼짐'} · ${item.fault ? '알람' : '알람 없음'}` }),
        item.servoOn
          ? h('button', { class: 'btn btn-mini', type: 'button', onclick: async () => { endSession(true); await act.servoControl(item, 'off'); changed(); } }, item.ac ? '서보 끄기' : '토크 끄기')
          : h('button', { class: 'btn btn-mini', type: 'button', disabled: item.fault || !item.detected, onclick: async () => { await act.servoControl(item, 'on'); changed(); } }, item.ac ? '서보 켜기' : '토크 켜기'),
        h('button', { class: 'btn btn-mini', type: 'button', onclick: async () => { await act.servoControl(item, 'reset'); changed(); } }, item.ac ? `오류 초기화${item.fault ? '' : ' (알람 없음)'}` : '재부팅'))),
    ui.message ? h('p', { class: 'tone-text-warn small', text: ui.message }) : null);
}

function faderView(state, changed, list) {
  const usable = list.filter((item) => item.row);
  const blocker = manualBlocker(state, usable[0] || null);
  const grab = async (item, joint) => {
    if (manualBlocker(state, item)) return;
    if (ui.session) endSession(true);
    if (!ui.faders.has(item.axis)) {
      try { await stream.open({ mapping_file_id: ui.fileId, base_mapping_revision: ui.revision }); } catch (error) { ui.message = error.message; changed(); return; }
    }
    ui.faders.set(item.axis, { joint });
    ensureLoop();
  };
  const letGo = (item) => {
    if (!ui.faders.has(item.axis)) return;
    stream.release([item.axis]);
    ui.faders.delete(item.axis);
  };
  return h('section', { class: 'card', 'aria-label': '전체 페이더' },
    blocker && blocker.fix !== 'servo-on' && blocker.fix !== 'reset' ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: blocker.text }), fixButton(blocker, null, changed)) : null,
    h('p', { class: 'muted small', text: '페이더를 드래그하는 동안에만 모터가 따라 움직이고, 손을 떼면 그 위치에서 정지합니다. 범위는 조인트 매핑의 최소·최대입니다.' }),
    usable.length ? h('ul', { class: 'list fader-list' }, usable.map((item) => {
      const own = manualBlocker(state, item);
      return h('li', { class: 'fader-row' },
        h('span', { class: 'fader-name' }, h('strong', { text: item.label }), h('small', { class: 'muted', text: ` ${item.axis}번` })),
        h('span', { class: 'mono muted small', text: `${signedDeg(Number(item.row.motion_lower_deg), 1)}°` }),
        h('input', { class: 'fader', type: 'range', min: String(item.row.motion_lower_deg), max: String(item.row.motion_upper_deg), step: '0.05',
          value: String(item.joint ?? 0), disabled: Boolean(own), 'aria-label': `${item.label} 페이더`, 'data-live': 'slider', 'data-axis': String(item.axis),
          oninput: (e) => grab(item, Number(e.target.value)), onchange: () => letGo(item) }),
        h('span', { class: 'mono muted small', text: `${signedDeg(Number(item.row.motion_upper_deg), 1)}°` }),
        h('span', { class: 'mono fader-value', 'data-live': 'joint', 'data-axis': String(item.axis), text: item.joint === null ? '-' : `${signedDeg(item.joint, 2)}°` }),
        own ? h('span', { class: 'chip chip-warn', title: own.text, text: '조작 불가' }) : null);
    })) : h('p', { class: 'muted', text: '「사용」이 켜진 조인트 매핑 줄에 연결된 모터가 없습니다' }),
    ui.message ? h('p', { class: 'tone-text-warn small', text: ui.message }) : null);
}

export function renderManual(state, { changed }) {
  ctx = { state, changed };
  const list = axes(state);
  if (ui.axis === null || !list.some((a) => a.axis === ui.axis)) ui.axis = list[0]?.axis ?? null;
  const item = list.find((a) => a.axis === ui.axis) || null;
  const playlist = registeredPlaylist(ui.mappingDoc);
  // 초기 위치 이동은 PC 전체 판정만 · 고른 모터 사정은 상관없다
  const pcBlocker = manualBlocker(state, null);
  const initDisabled = Boolean(pcBlocker && pcBlocker.text !== '모터를 선택하세요') || !ui.fileId;
  const initialize = async () => {
    const ok = await confirmBox({ title: '초기 위치로', body: `재생 목록 1번(${playlist[0] || '없음'}) 애니메이션의 초기 위치로 천천히 이동합니다.`, confirmLabel: '이동' });
    if (!ok) return;
    endSession(true);
    await act.initializeLocal({ motion_file_id: playlist[0] || '', mapping_file_id: ui.fileId, initial_move_time_sec: null, run_mode: 'once', repeat_mode: 'direct', dwell_sec: 0, target_cycle_count: 0 });
  };
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '수동 조작' }),
      h('nav', { class: 'row part-jumps', 'aria-label': '구획 바로 가기' },
        [['part-faders', '① 전체 페이더'], ['part-axis', '② 모터 개별']].map(([id, label]) => h('a', { class: 'btn btn-mini', href: '#/manual',
          onclick: (event) => { event.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, label))),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn', type: 'button', disabled: initDisabled, title: initDisabled && pcBlocker ? pcBlocker.text : '',
        onclick: initialize }, '초기 위치로')),
    !list.length ? h('section', { class: 'card' }, h('p', { class: 'muted', text: '인식된 모터가 없습니다' })) : [
      // 한 페이지에 두 구획(사용자 2026-10-12 · 모터 설정과 같게) · 한쪽을 잡으면 다른 쪽 세션은 놓는다
      h('section', { class: 'setup-part', id: 'part-faders', 'aria-label': '전체 페이더' },
        h('div', { class: 'part-head' }, h('h2', { text: '① 전체 페이더' })),
        faderView(state, changed, list)),
      h('section', { class: 'setup-part', id: 'part-axis', 'aria-label': '모터 개별' },
        h('div', { class: 'part-head' }, h('h2', { text: '② 모터 개별' })),
        h('p', { class: 'muted small', text: '모터 하나를 골라 다이얼 · 목표 위치로 움직입니다.' }),
        h('div', { class: 'manual-grid' },
          h('section', { class: 'card axis-list', 'aria-label': '모터' },
            h('ul', { class: 'list' }, list.map((a) => h('li', {},
              h('button', { class: `axis-pick${a.axis === ui.axis ? ' on' : ''}`, type: 'button', 'aria-pressed': String(a.axis === ui.axis),
                onclick: () => { if (ui.axis !== a.axis) { endSession(true); ui.axis = a.axis; ui.goal = ''; ui.message = ''; changed(); } } },
              h('span', { class: 'axis-pick-head' }, h('strong', { text: a.label }),
                h('span', { class: 'mono', 'data-live': 'joint', 'data-axis': String(a.axis), text: a.joint === null ? '-' : `${signedDeg(a.joint, 2)}°` })),
              h('span', { class: 'axis-pick-meta' }, dot(a.fault ? 'bad' : a.servoOn ? 'ok' : 'warn'),
                h('span', { class: 'muted small', text: `${a.fault ? '알람' : a.servoOn ? '서보 켜짐' : '서보 꺼짐'} · ${a.axis}번 · ${a.ac ? 'AC' : 'DXL'}${a.row ? ` · 1:${a.row.gear_ratio}` : ' · 매핑 없음'}` }))))))),
          item ? axisPanel(state, changed, item) : null))
    ],
  ];
}
