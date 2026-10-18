/** UI v2 · X-Touch · 페이더로 축 실시간 조종 + 녹화 · 수정 목록 156 (사용자 결정 2026-10-17 · 2026-10-18)
 *
 * X-Touch 는 이 화면을 연 PC 에 USB · 브라우저가 Web MIDI 로 읽고 쓴다(xtouch_device.js) ·
 * 페이더 값은 수동 페이더와 같은 소켓 · 출처 `xtouch` · 서버가 조인트 매핑 최대 속도·가속도로 따라간다(빈 축은 거절) ·
 * 수동 모드에서만 · 한 번에 로봇 한 대 · 이 탭이 보일 때만(다른 탭으로 가면 놓고 연결을 끊는다).
 *
 * 녹화 · 화면 버튼 또는 X-Touch REC · 3초 뒤 시작 · 선택(SELECT)한 축만 · 로봇 쪽이 램프 뒤 명령값을 기록 ·
 * 정지하면 애니메이션 목록에 저장(같은 이름이면 _2 · _3) · 화면이 끊기면 끊긴 순간까지 자동 저장.
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { toast } from '../dialog.js';
import * as act from '../actions.js';
import { ManualStream } from '../manual_stream.js';
import { jointToMotor, motorForRow, motorRefFor, motorToJoint, previewRow, rowToDraft } from '../mapping_model.js';
import { signedDeg } from '../play_model.js';
import { manualBlocker } from './manual.js';
import { MIDI_FLAG_URL, XTouchDevice, midiUnavailableReason } from '../xtouch_device.js';
import {
  CHANNELS, PHASE_LABEL, XTouchSession, channelConfig, faderMessage, lcdMessages, ledMessage, recordLed,
} from '../xtouch_model.js';

const DEG = 180 / Math.PI;
const RAD = Math.PI / 180;
const TICK_MS = 20;
const PING_MS = 500;
/** 이만큼 아무것도 안 오면 서버가 끊긴 것으로 본다(무선 멈춤) · 화면은 0.5 s 마다 ping */
const WATCHDOG_SEC = 2;
const ROUTE = '#/xtouch';

const ui = {
  rows: null, fileId: '', revision: '', message: '', name: '',
  record: { state: 'idle' }, recordAt: 0, lastSaved: null,
  dev: { status: 'off', name: '', message: '' },
};
let ctx = { state: null, changed: () => {} };
const session = new XTouchSession();
const device = new XTouchDevice({
  onEvent: (event) => onDeviceEvent(event),
  onState: (state) => {
    ui.dev = state;
    if (state.status !== 'ready') run(session.reset());
    else paintSurface();
    ctx.changed();
  },
});
const stream = new ManualStream({
  onResult: (result) => {
    if (result.success === false && result.message) { ui.message = result.message; ctx.changed(); }
  },
  onClose: (reason) => {
    if (reason) ui.message = reason;
    run(session.reset());
    ctx.changed();
  },
  onMessage: (message) => {
    if (message.type === 'pong') setRecord(message.record);
    else if (message.type === 'record') onRecordReply(message);
  },
});
let loop = null;
let lastPing = 0;
let lastOpenTry = 0;
let lastLcd = '';

/* ---------- 상태 ---------- */

function motors(state) {
  return (state?.snap?.motion_state?.motors || []).map((m) => ({
    raw: m, axis: Number(m.controller_index), ref: motorRefFor(m),
    position: m.position_rad === null || m.position_rad === undefined ? null : Number(m.position_rad) * DEG,
    lower: Number.isFinite(Number(m.lower)) ? Number(m.lower) : -Infinity,
    upper: Number.isFinite(Number(m.upper)) ? Number(m.upper) : Infinity,
  }));
}

function config(state) {
  const list = motors(state);
  return channelConfig(ui.rows || [], (row) => motorForRow(row, list)?.axis ?? null);
}

/** 수동 조작을 막는 PC 전체 이유 · 빈 글자면 됨 */
function blockedText(state) {
  const blocker = manualBlocker(state, null);
  return blocker && blocker.text !== '모터를 선택하세요' ? blocker.text : '';
}

function sessionCtx() {
  const list = motors(ctx.state);
  return {
    now: performance.now(),
    blocked: blockedText(ctx.state),
    recording: ui.record.state === 'countdown' || ui.record.state === 'recording',
    jointOf: (axis) => {
      const item = session.config.find((c) => c?.axis === axis);
      const motor = list.find((m) => m.axis === axis);
      if (!item || !motor || motor.position === null) return null;
      return motorToJoint(item.row, motor.position);
    },
  };
}

/* ---------- 장치 → 할 일 ---------- */

function onDeviceEvent(event) {
  // 보이는 탭만 · 다른 탭에서 같은 장치를 받아도 움직이지 않게
  if (document.hidden || !location.hash.startsWith(ROUTE)) return;
  run(session.handle(event, sessionCtx()));
}

function run(actions) {
  for (const action of actions || []) {
    if (action.type === 'feedback') device.send(faderMessage(action.channel, action.value));
    else if (action.type === 'led') device.send(ledMessage(action.group, action.channel, action.state));
    else if (action.type === 'target') sendTarget(action);
    else if (action.type === 'release') stream.release(action.axes);
    else if (action.type === 'record-toggle') toggleRecord();
    else if (action.type === 'record-add') stream.send({ type: 'record_add', axes: action.axes });
    else if (action.type === 'message') { ui.message = action.text; ctx.changed(); }
  }
}

function sendTarget(action) {
  const item = session.config[action.channel];
  const motor = motors(ctx.state).find((m) => m.axis === action.axis);
  if (!item || !motor) return;
  const view = previewRow(item.row);
  const lower = Math.max(motor.lower, view.motorMin);
  const upper = Math.min(motor.upper, view.motorMax);
  const motorDeg = Math.min(upper, Math.max(lower, jointToMotor(item.row, action.joint)));
  stream.target(action.axis, motorDeg * RAD, { motion_id: action.motionId, motion_rad: action.joint * RAD, source: 'xtouch' });
}

/** 불빛 · 글씨 칸 · 연결 직후와 상태가 바뀔 때 */
function paintSurface() {
  if (!device.ready()) return;
  const recordState = recordLed(ui.record.state);
  const armed = new Set(ui.record.axes || []);
  for (let channel = 0; channel < CHANNELS; channel += 1) {
    const item = session.config[channel];
    const selected = session.channels[channel].selected;
    device.send(ledMessage('select', channel, selected ? 'on' : 'off'));
    const lit = recordState !== 'off' && (armed.size ? armed.has(item?.axis) : channel === 0);
    device.send(ledMessage('rec', channel, lit ? recordState : 'off'));
  }
  paintLcd(true);
}

function paintLcd(force = false) {
  if (!device.ready() || !device.sysex) return;
  const texts = session.config.map((item, channel) => {
    if (!item) return ['-', ''];
    const state = session.channels[channel];
    const bottom = state.selected ? { ready: 'SEL', pickup: 'MATCH', live: 'LIVE', idle: '' }[state.phase] : '';
    return [item.motionId.replace(/^f\d+_/, ''), ui.record.state === 'recording' && state.selected ? 'REC' : bottom];
  });
  const key = JSON.stringify(texts);
  if (!force && key === lastLcd) return;
  lastLcd = key;
  texts.forEach(([top, bottom], channel) => {
    for (const message of lcdMessages(device.deviceId, channel, top, bottom)) device.send(message);
  });
}

/* ---------- 주기 ---------- */

function ensureLoop() {
  if (loop) return;
  loop = setInterval(tick, TICK_MS);
}

function teardown(reason = '') {
  run(session.reset());
  paintSurface();
  stream.close();
  device.disconnect();
  if (loop) { clearInterval(loop); loop = null; }
  if (reason) ui.message = reason;
}

function tick() {
  if (!location.hash.startsWith(ROUTE)) { teardown(); return; }
  if (document.hidden) {
    if (device.state.status !== 'off') teardown('다른 탭으로 가서 X-Touch 연결을 끊었습니다 · 녹화 중이었다면 그 순간까지 저장됐습니다');
    ctx.changed();
    return;
  }
  const now = performance.now();
  const blocked = blockedText(ctx.state);
  run(session.configure(config(ctx.state)));
  if (blocked) {
    if (session.selectedAxes().length) { run(session.reset()); ctx.changed(); }
    if (stream.isOpen()) stream.close();
  } else if (device.ready() && !stream.isOpen() && now - lastOpenTry > 1000) {
    lastOpenTry = now;
    stream.open({ mapping_file_id: ui.fileId, base_mapping_revision: ui.revision, watchdog_sec: WATCHDOG_SEC })
      .catch((error) => { ui.message = error.message; ctx.changed(); });
  }
  if (stream.isOpen()) {
    run(session.tick(sessionCtx()));
    if (now - lastPing >= PING_MS) { lastPing = now; stream.send({ type: 'ping' }); }
  }
  paintLcd();
}

/* ---------- 녹화 ---------- */

function setRecord(record) {
  const next = record && typeof record === 'object' ? record : { state: 'idle' };
  const changed = next.state !== ui.record.state || JSON.stringify(next.axes || []) !== JSON.stringify(ui.record.axes || []);
  ui.record = next;
  ui.recordAt = performance.now();
  if (changed) { paintSurface(); ctx.changed(); }
}

function onRecordReply(message) {
  if (message.success === false && message.message) { ui.message = message.message; toast(message.message, 'warn'); }
  if (message.state === 'saved') {
    ui.lastSaved = { file: message.file, duration: message.duration_sec, ids: message.motion_ids || [] };
    toast(message.message || '저장했습니다', 'ok');
    setRecord({ state: 'idle' });
  } else if (message.state) {
    setRecord(message);
  }
  ctx.changed();
}

function recording() {
  return ui.record.state === 'countdown' || ui.record.state === 'recording';
}

function toggleRecord() {
  if (recording()) { stopRecord(); return; }
  startRecord();
}

function startRecord() {
  const blocked = blockedText(ctx.state);
  if (blocked) { ui.message = blocked; ctx.changed(); return; }
  const axes = session.selectedAxes();
  if (!axes.length) { ui.message = '녹화할 축이 없습니다 · X-Touch 에서 SELECT 로 축을 고르세요'; ctx.changed(); return; }
  if (!stream.send({ type: 'record_start', axes, name: ui.name })) { ui.message = '로봇과 연결되지 않았습니다 · 잠시 뒤 다시'; ctx.changed(); return; }
  ui.message = '';
}

function stopRecord() {
  if (!stream.send({ type: 'record_stop' })) ui.message = '로봇과 연결되지 않았습니다 · 끊긴 순간까지 자동 저장됩니다';
  ctx.changed();
}

function cancelRecord() {
  stream.send({ type: 'record_cancel' });
}

/** 카운트다운 남은 초 · 녹화 경과 · 서버 값 + 받은 뒤 지난 시간 */
function recordText() {
  const since = (performance.now() - ui.recordAt) / 1000;
  if (ui.record.state === 'countdown') return `${Math.max(0, Math.ceil(Number(ui.record.starts_in_sec || 0) - since))}초 뒤 시작`;
  if (ui.record.state === 'recording') {
    const total = Number(ui.record.elapsed_sec || 0) + since;
    return `녹화 중 ${Math.floor(total / 60)}:${String(Math.floor(total % 60)).padStart(2, '0')}`;
  }
  return '대기';
}

/* ---------- 읽기 ---------- */

export async function loadXTouch(state, changed) {
  ctx = { state, changed };
  try {
    const list = await api('GET', '/api/motion-mappings');
    const files = Array.isArray(list?.files) ? list.files : [];
    const fileId = files.some((f) => f.id === list?.active_file_id) ? list.active_file_id : (files[0]?.id || '');
    if (fileId) {
      const data = await api('GET', `/api/motion-mappings/${encodeURIComponent(fileId)}`);
      if (data?.mapping) {
        const revision = String(data.file?.mapping_revision || data.file?.revision || '');
        // 매핑이 바뀌면 소켓의 변환표도 낡았다 · 다시 연다
        if (ui.revision && revision !== ui.revision && stream.isOpen()) stream.close();
        ui.rows = (data.mapping.mappings || []).map(rowToDraft);
        ui.fileId = fileId;
        ui.revision = revision;
      }
    } else {
      ui.rows = [];
    }
  } catch { /* 옛 매핑 그대로 · 다음 주기에 다시 */ }
  changed();
}

/* ---------- 그리기 ---------- */

const DEV_TONE = { ready: 'ok', connecting: 'warn', off: 'idle', missing: 'warn', busy: 'bad', denied: 'bad', unavailable: 'bad' };
const DEV_TEXT = { ready: '연결됨', connecting: '연결 중', off: '연결 안 됨', missing: '장치 없음', busy: '다른 곳에서 쓰는 중', denied: '권한 없음', unavailable: '이 주소에서 MIDI 불가' };

function connectCard(state, changed) {
  const unavailable = midiUnavailableReason();
  const blocker = manualBlocker(state, null);
  const blocked = blockedText(state);
  return h('section', { class: 'card', 'aria-label': 'X-Touch 연결' },
    h('div', { class: 'card-head' }, h('h2', { text: '연결' })),
    h('div', { class: 'row' },
      dot(DEV_TONE[ui.dev.status] || 'idle'),
      h('span', { class: 'grow', text: `${DEV_TEXT[ui.dev.status] || ui.dev.status}${ui.dev.name ? ` · ${ui.dev.name}` : ''}${ui.dev.status === 'ready' && !device.sysex ? ' · 글씨 칸 권한 없음(조종은 됨)' : ''}` }),
      ui.dev.status === 'ready' || ui.dev.status === 'connecting'
        ? h('button', { class: 'btn', type: 'button', onclick: () => { teardown(); changed(); } }, '연결 끊기')
        : h('button', { class: 'btn btn-primary', type: 'button', disabled: Boolean(unavailable), onclick: async () => {
          ui.message = '';
          if (await device.connect()) { ensureLoop(); paintSurface(); }
          changed();
        } }, 'X-Touch 연결')),
    ui.dev.message ? h('p', { class: 'tone-text-warn small', text: ui.dev.message }) : null,
    unavailable ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: unavailable })) : null,
    unavailable ? h('ol', { class: 'small muted' },
      h('li', { text: `이 PC 크롬 주소창에 ${MIDI_FLAG_URL} 입력` }),
      h('li', { text: `「Insecure origins treated as secure」 칸에 ${location.origin} 추가 · Enabled` }),
      h('li', { text: '크롬 다시 시작 → 이 화면 → 「X-Touch 연결」 → MIDI 권한 허용' })) : null,
    blocked ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: `X-Touch 입력을 무시합니다 · ${blocked}` }),
      blocker?.fix === 'mode-manual' ? h('button', { class: 'btn btn-warn', type: 'button', onclick: () => act.setRunMode('manual') }, '수동 모드로 전환') : null,
      blocker?.fix === 'stop' ? h('button', { class: 'btn btn-warn', type: 'button', onclick: act.stopAll }, '정지') : null) : null,
    h('p', { class: 'muted small', text: '한 번에 로봇 한 대 · 이 탭이 보일 때만 움직입니다(다른 탭으로 가면 놓고 연결을 끊습니다). SELECT 로 축을 고르면 페이더가 그 축 위치로 가고, 손을 대고 축 값에 맞추면(0.5° 안 또는 지나감) 그때부터 따라갑니다. 손을 떼면 마지막 목표까지 가서 섭니다. 속도·가속도는 조인트 매핑의 최대 값입니다.' }));
}

function channelCard(state) {
  const list = motors(state);
  const rows = session.config;
  return h('section', { class: 'card', 'aria-label': '채널' },
    h('div', { class: 'card-head' }, h('h2', { text: '페이더 · 축' })),
    rows.some(Boolean) ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['페이더', '조인트', '모터', '상태', '현재', '목표'].map((text) => h('th', { scope: 'col', text })))),
      h('tbody', {}, rows.map((item, channel) => {
        if (!item) return h('tr', { class: 'muted-row' }, h('td', { class: 'mono', text: String(channel + 1) }), h('td', { colspan: '5', class: 'muted', text: '연결 안 됨' }));
        const motor = list.find((m) => m.axis === item.axis);
        const joint = motor && motor.position !== null ? motorToJoint(item.row, motor.position) : null;
        const ch = session.channels[channel];
        const phase = ch.selected ? (ch.touched && ch.phase === 'pickup' ? '맞추는 중 · 축 값으로 페이더를 옮기세요' : PHASE_LABEL[ch.phase]) : PHASE_LABEL.idle;
        return h('tr', { class: ch.selected ? 'selected' : '' },
          h('td', { class: 'mono', text: String(item.fader) }),
          h('td', {}, h('strong', { text: item.motionId })),
          h('td', { class: 'mono', text: Number.isInteger(item.axis) ? `${item.axis}번` : '없음' }),
          h('td', {}, item.ratesSet ? h('span', { class: `chip chip-${ch.phase === 'live' ? 'ok' : ch.selected ? 'warn' : 'idle'}`, text: phase })
            : h('span', { class: 'chip chip-bad', text: '속도·가속도 상한 없음' })),
          h('td', { class: 'mono', text: joint === null ? '-' : `${signedDeg(joint, 2)}°` }),
          h('td', { class: 'mono', text: ch.phase === 'live' && Number.isFinite(ch.goal) ? `${signedDeg(ch.goal, 2)}°` : '-' }));
      })))) : h('p', { class: 'muted', text: '페이더가 연결된 조인트가 없습니다 · 「모터 설정 → ① 조인트 매핑」 에서 「X-Touch 페이더」 칸에 1 ~ 8 을 넣고 저장하세요.' }),
    ui.message ? h('p', { class: 'tone-text-warn small', text: ui.message }) : null);
}

function recordCard(state, changed) {
  const live = recording();
  const ready = stream.isOpen() && !blockedText(state);
  const axes = live ? (ui.record.axes || []) : session.selectedAxes();
  const names = axes.map((axis) => session.config.find((c) => c?.axis === axis)?.motionId || `${axis}번`);
  return h('section', { class: 'card', 'aria-label': '녹화' },
    h('div', { class: 'card-head' }, h('h2', { text: '녹화' })),
    h('div', { class: 'row' },
      h('label', { class: 'inline' }, '이름', h('input', { class: 'input mono', type: 'text', value: ui.name, placeholder: 'xtouch_날짜_시각', disabled: live,
        'aria-label': '녹화 이름', oninput: (e) => { ui.name = e.target.value; } })),
      live
        ? [h('button', { class: 'btn btn-primary', type: 'button', onclick: stopRecord }, '정지 · 저장'),
          h('button', { class: 'btn', type: 'button', onclick: cancelRecord }, '취소')]
        : h('button', { class: 'btn btn-danger', type: 'button', disabled: !ready || !axes.length, title: !ready ? '수동 모드 · X-Touch 연결 뒤' : !axes.length ? 'SELECT 로 축을 고르세요' : '',
          onclick: () => { startRecord(); changed(); } }, '● 녹화 시작')),
    h('p', { class: 'mono', text: `${recordText()} · 축 ${names.length ? names.join(', ') : '없음'}` }),
    ui.lastSaved ? h('p', { class: 'small' }, `마지막 저장 · ${ui.lastSaved.file} · ${Number(ui.lastSaved.duration || 0).toFixed(2)} s · `,
      h('a', { href: '#/animations', text: '애니메이션 목록' })) : null,
    h('p', { class: 'muted small', text: 'X-Touch 의 REC 버튼으로도 시작·정지합니다. 시작하면 3초 뒤부터 기록합니다. 고른 축만, 모터가 실제로 받은 명령값을 20 ms 마다 기록해 애니메이션 목록에 저장합니다(같은 이름이면 _2, _3). 녹화 중 연결이 끊기면 축은 그 자리에 서고, 끊긴 순간까지 자동 저장합니다. 녹화할 축은 조인트 매핑의 최대 속도·가속도가 있어야 합니다.' }));
}

export function renderXTouch(state, { changed }) {
  ctx = { state, changed };
  run(session.configure(config(state)));
  return [
    h('div', { class: 'page-head' }, h('h1', { text: 'X-Touch' })),
    connectCard(state, changed),
    channelCard(state),
    recordCard(state, changed),
  ];
}
