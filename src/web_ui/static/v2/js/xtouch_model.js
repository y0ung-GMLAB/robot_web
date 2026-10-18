/** UI v2 · X-Touch (Extender) · 화면 없이 시험되는 부분 · 수정 목록 156 (사용자 결정 2026-10-17)
 *
 * X-Touch 는 로봇 PC 가 아니라 이 화면을 연 PC 에 꽂는다 · 브라우저가 Web MIDI 로 읽고 쓴다 ·
 * 페이더 값은 수동 페이더와 같은 소켓(/ws/manual-stream)으로 · 출처 `xtouch` = 조인트 매핑 최대 속도·가속도.
 *
 * MIDI (Mackie Control · 채널 8개 · 옛 xtouch_node.cpp 와 같은 번호)
 *   페이더       pitch bend 0xE0|ch · 0 ~ 16383 · 보내면 모터 페이더가 그 자리로 간다
 *   페이더 터치  note 104 + ch · 누름 127 · 뗌 0
 *   버튼         REC 0 + ch · SOLO 8 + ch · MUTE 16 + ch · SELECT 24 + ch · 불빛 = 같은 note (127 켬 · 1 깜빡 · 0 끔)
 *   글씨 칸      SysEx F0 00 00 66 <장치> 12 <자리> <글자…> F7 · 장치 X-Touch 14 · Extender 15 · 칸마다 7 글자 · 위 줄 0 · 아래 줄 56
 *
 * 잡기(pickup · 전신 방식) · SELECT → 페이더를 그 축 지금 값으로 보냄 → 손을 대고 페이더가 축 값 0.5° 안에 들거나
 * 지나가면 그때부터 조종 · 그 전에는 「맞추는 중」 · 놓으면 release(마지막 목표까지 간 뒤 섬) · 다음에 손 대면 다시 잡기 ·
 * SELECT 를 끄면 놓음 · 손 안 댄 동안 선택된 페이더는 축을 따라 움직인다(재생 따라감).
 *
 * 바탕 위 녹화(⑨ · `setTake`) · 바탕에 있는 조인트 채널은 선택 안 해도 재생을 따라 움직인다 ·
 * 선택하고 잡으면 「구간 덮어쓰기」(⑨-2) · 목표는 `punch`(조인트 값 · 재생 노드가 램프·잇기) · 놓으면 `punch-release` ·
 * 바탕에 없는 조인트는 「추가 녹화」 · 보통 조종과 같다(`target`).
 */

export const FADER_MAX = 16383;
export const CHANNELS = 8;
export const PICKUP_TOLERANCE_DEG = 0.5;
export const NOTE = { rec: 0, solo: 8, mute: 16, select: 24, touch: 104 };
/** 손 안 댄 페이더를 축 따라 움직이는 간격 · 이만큼 달라졌을 때만 */
export const FOLLOW_EVERY_MS = 100;
export const FOLLOW_MIN_STEP = 8;
const LCD_CHARS = 7;
const LCD_BOTTOM = 56;

/** 받은 MIDI 한 덩이 → 일 하나 · 모르는 것은 null */
export function parseMidi(data) {
  const bytes = Array.from(data || []);
  if (bytes.length < 3) return null;
  const status = bytes[0] & 0xF0;
  const channel = bytes[0] & 0x0F;
  if (status === 0xE0) {
    if (channel >= CHANNELS) return null;
    return { kind: 'fader', channel, value: (bytes[2] << 7) | bytes[1] };
  }
  if (status !== 0x90 && status !== 0x80) return null;
  const note = bytes[1];
  const down = status === 0x90 && bytes[2] > 0;
  if (note >= NOTE.touch && note < NOTE.touch + CHANNELS) return { kind: 'touch', channel: note - NOTE.touch, down };
  for (const group of ['rec', 'solo', 'mute', 'select']) {
    const start = NOTE[group];
    if (note >= start && note < start + CHANNELS) return { kind: 'button', group, channel: note - start, down };
  }
  return null;
}

export function faderMessage(channel, value) {
  const v = Math.max(0, Math.min(FADER_MAX, Math.round(value)));
  return [0xE0 | (channel & 0x0F), v & 0x7F, (v >> 7) & 0x7F];
}

/** 버튼 불빛 · on | blink | off */
export function ledMessage(group, channel, state) {
  const velocity = state === 'on' ? 127 : state === 'blink' ? 1 : 0;
  return [0x90, NOTE[group] + channel, velocity];
}

/** 글씨 칸 한 채널 · 위·아래 줄 7 글자씩 · ASCII 만 */
export function lcdMessages(deviceId, channel, top, bottom) {
  const fit = (text) => String(text ?? '').replace(/[^\x20-\x7E]/g, '?').slice(0, LCD_CHARS).padEnd(LCD_CHARS, ' ');
  const one = (offset, text) => [0xF0, 0x00, 0x00, 0x66, deviceId, 0x12, offset, ...[...fit(text)].map((c) => c.charCodeAt(0) & 0x7F), 0xF7];
  return [one(channel * LCD_CHARS, top), one(LCD_BOTTOM + channel * LCD_CHARS, bottom)];
}

/** 장치 이름으로 · Extender 면 15 · 아니면 14 */
export function lcdDeviceId(portName) {
  return /ext/i.test(String(portName || '')) ? 0x15 : 0x14;
}

export function looksLikeXTouch(portName) {
  return /x-?touch|behringer/i.test(String(portName || ''));
}

/** 페이더 0 ~ 16383 ↔ 조인트 범위 전체(맨 아래 = 최소 · 맨 위 = 최대) · deg */
export function faderToJoint(lower, upper, value) {
  const ratio = Math.max(0, Math.min(1, Number(value) / FADER_MAX));
  return lower + (upper - lower) * ratio;
}

export function jointToFader(lower, upper, joint) {
  if (!(upper > lower) || !Number.isFinite(joint)) return 0;
  return Math.round(Math.max(0, Math.min(1, (joint - lower) / (upper - lower))) * FADER_MAX);
}

/** 잡았나 · 축 값 0.5° 안이거나 지난 값과 이번 값 사이에 축 값이 있으면(지나감) */
export function pickupReached(previous, current, reference, tolerance = PICKUP_TOLERANCE_DEG) {
  if (!Number.isFinite(current) || !Number.isFinite(reference)) return false;
  if (Math.abs(current - reference) <= tolerance) return true;
  if (!Number.isFinite(previous)) return false;
  return (previous <= reference && reference <= current) || (current <= reference && reference <= previous);
}

/**
 * 조인트 매핑 줄 → 채널 · 「사용」 이고 페이더 번호가 있는 줄 · 같은 번호가 둘이면 앞 줄(저장할 때 거절된다)
 * @param rows 화면 초안 줄(deg) · @param axisOf 줄 → 모터 번호(없으면 null)
 */
export function channelConfig(rows, axisOf) {
  const out = new Array(CHANNELS).fill(null);
  for (const row of rows || []) {
    const fader = Number(row?.xtouch_fader);
    if (row?.enabled === false || !Number.isInteger(fader) || fader < 1 || fader > CHANNELS) continue;
    if (out[fader - 1]) continue;
    const lower = Number(row.motion_lower_deg);
    const upper = Number(row.motion_upper_deg);
    out[fader - 1] = {
      fader, motionId: String(row.motion_id || ''), row, axis: axisOf(row),
      lower, upper, ratesSet: Number(row.max_velocity_deg_s) > 0 && Number(row.max_acceleration_deg_s2) > 0,
    };
  }
  return out;
}

/** 채널 상태 글 · 화면 · 글씨 칸 */
export const PHASE_LABEL = { idle: '선택 안 됨', pickup: '맞추는 중', ready: '선택됨', live: '조종 중' };

/**
 * 채널 8개의 상태 · 일(event)을 받아 할 일(action) 목록을 돌려준다 · 보내기는 화면이
 *   action · {type:'feedback', channel, value} {type:'led', group, channel, state} {type:'target', channel, axis, joint, motionId}
 *            {type:'release', axes} {type:'record-toggle'} {type:'record-add', axes} {type:'message', text}
 *            {type:'punch', channel, axis, joint, motionId} {type:'punch-release', motionId}  (바탕 위 녹화의 바탕 조인트)
 * ctx · {jointOf(axis) → 지금 조인트 deg | null, blocked: 막는 이유 글('' = 됨), recording: bool}
 */
export class XTouchSession {
  constructor() {
    this.config = new Array(CHANNELS).fill(null);
    this.channels = Array.from({ length: CHANNELS }, () => blankChannel());
    this.punchIds = new Set();
  }

  /** 바탕 위 녹화 · 덮어쓸 수 있는 조인트 이름들 · 빈 목록 = 보통 */
  setTake(punchIds) {
    const next = new Set(punchIds || []);
    const same = next.size === this.punchIds.size && [...next].every((id) => this.punchIds.has(id));
    if (same) return [];
    // 덮어쓰기 ↔ 보통 이 바뀐 채널은 놓는다(목표 길이 다름)
    const actions = [];
    this.config.forEach((item, channel) => {
      if (item && this.channels[channel].selected && next.has(item.motionId) !== this.punchIds.has(item.motionId)) {
        actions.push(...this.deselect(channel));
      }
    });
    this.punchIds = next;
    return actions;
  }

  isPunch(channel) {
    const item = this.config[channel];
    return Boolean(item && this.punchIds.has(item.motionId));
  }

  /** 매핑이 바뀜 · 연결이 바뀐 채널은 놓는다 */
  configure(config) {
    const actions = [];
    config.forEach((item, channel) => {
      const old = this.config[channel];
      const same = old && item && old.motionId === item.motionId && old.axis === item.axis && old.lower === item.lower && old.upper === item.upper;
      if (!same && this.channels[channel].selected) actions.push(...this.deselect(channel));
    });
    this.config = config.slice(0, CHANNELS);
    while (this.config.length < CHANNELS) this.config.push(null);
    return actions;
  }

  /** 모두 놓기 · 모드가 바뀜 · 화면을 떠남 · 연결 끊김 */
  reset() {
    const actions = [];
    for (let channel = 0; channel < CHANNELS; channel += 1) {
      if (this.channels[channel].selected) actions.push(...this.deselect(channel));
    }
    return actions;
  }

  selectedAxes() {
    return this.channels.map((c, i) => (c.selected ? this.config[i]?.axis : null)).filter((axis) => Number.isInteger(axis));
  }

  handle(event, ctx) {
    if (!event) return [];
    if (event.kind === 'button' && event.group === 'rec') return event.down ? [{ type: 'record-toggle' }] : [];
    if (event.kind === 'button' && event.group === 'select') return event.down ? this.toggleSelect(event.channel, ctx) : [];
    if (event.kind === 'touch') return this.touch(event.channel, event.down);
    if (event.kind === 'fader') return this.fader(event.channel, event.value, ctx);
    return [];
  }

  toggleSelect(channel, ctx) {
    const state = this.channels[channel];
    if (state.selected) return this.deselect(channel);
    const item = this.config[channel];
    if (!item) return [{ type: 'message', text: `페이더 ${channel + 1} 에 연결된 조인트가 없습니다 · 조인트 매핑에서 「X-Touch 페이더」 칸을 채우세요` }];
    if (!Number.isInteger(item.axis)) return [{ type: 'message', text: `${item.motionId} · 연결된 모터가 없습니다` }];
    if (!item.ratesSet) return [{ type: 'message', text: `축 ${item.axis} (${item.motionId}) 속도·가속도 상한을 먼저 채우세요 · 조인트 매핑의 최대 속도·가속도` }];
    if (ctx?.blocked) return [{ type: 'message', text: ctx.blocked }];
    Object.assign(state, blankChannel(), { selected: true, phase: 'ready' });
    const actions = [{ type: 'led', group: 'select', channel, state: 'on' }];
    const joint = ctx?.jointOf?.(item.axis);
    if (Number.isFinite(joint)) actions.push(this.feedback(channel, jointToFader(item.lower, item.upper, joint), ctx?.now));
    if (ctx?.recording) actions.push({ type: 'record-add', axes: [item.axis] });
    return actions;
  }

  deselect(channel) {
    const state = this.channels[channel];
    const item = this.config[channel];
    const actions = [{ type: 'led', group: 'select', channel, state: 'off' }];
    if (state.sent && Number.isInteger(item?.axis)) actions.push(this.releaseAction(channel));
    Object.assign(state, blankChannel());
    return actions;
  }

  touch(channel, down) {
    const state = this.channels[channel];
    state.touched = down;
    if (!state.selected) return [];
    if (down) {
      state.phase = 'pickup';
      state.reference = null;
      return [];
    }
    const actions = [];
    const item = this.config[channel];
    if (state.phase === 'live' && state.dirty) actions.push(this.target(channel));
    if (state.phase === 'live' && Number.isInteger(item?.axis)) actions.push(this.releaseAction(channel));
    state.phase = 'ready';
    state.lastFollowAt = 0;
    return actions;
  }

  fader(channel, value, ctx) {
    const state = this.channels[channel];
    const item = this.config[channel];
    const previous = state.value;
    state.value = value;
    // 손 안 댄 움직임(내가 보낸 것 · 터치 감지 실패)은 조종에 쓰지 않는다
    if (!state.selected || !state.touched || !item) return [];
    if (ctx?.blocked) return [];
    const joint = faderToJoint(item.lower, item.upper, value);
    if (state.phase === 'pickup') {
      const reference = ctx?.jointOf?.(item.axis);
      state.reference = Number.isFinite(reference) ? reference : null;
      const before = Number.isFinite(previous) ? faderToJoint(item.lower, item.upper, previous) : NaN;
      if (!pickupReached(before, joint, state.reference)) return [];
      state.phase = 'live';
    }
    if (state.phase !== 'live') return [];
    state.goal = joint;
    state.dirty = true;
    return [];
  }

  releaseAction(channel) {
    const item = this.config[channel];
    return this.isPunch(channel) ? { type: 'punch-release', motionId: item.motionId } : { type: 'release', axes: [item.axis] };
  }

  /** 주기 · 쌓인 목표 보내기(채널마다 마지막 값 하나) · 손 안 댄 선택 페이더는 축 따라 · 바탕 조인트는 선택 안 해도 */
  tick(ctx) {
    const actions = [];
    const now = Number(ctx?.now ?? 0);
    this.channels.forEach((state, channel) => {
      const item = this.config[channel];
      if (!item || (!state.selected && !this.isPunch(channel))) return;
      if (state.phase === 'live' && state.dirty) actions.push(this.target(channel));
      if (state.touched || now - state.lastFollowAt < FOLLOW_EVERY_MS) return;
      const joint = ctx?.jointOf?.(item.axis);
      if (!Number.isFinite(joint)) return;
      const value = jointToFader(item.lower, item.upper, joint);
      if (state.lastFeedback === null || Math.abs(value - state.lastFeedback) >= FOLLOW_MIN_STEP) actions.push(this.feedback(channel, value, now));
    });
    return actions;
  }

  target(channel) {
    const state = this.channels[channel];
    const item = this.config[channel];
    state.dirty = false;
    state.sent = true;
    return { type: this.isPunch(channel) ? 'punch' : 'target', channel, axis: item.axis, joint: state.goal, motionId: item.motionId };
  }

  /** 모터 페이더를 보냄 · 보낸 값을 지금 페이더 자리로 친다(장치는 모터로 움직인 값을 돌려주지 않는다) */
  feedback(channel, value, now = 0) {
    const state = this.channels[channel];
    state.lastFeedback = value;
    state.lastFollowAt = Number(now) || 0;
    state.value = value;
    return { type: 'feedback', channel, value };
  }
}

function blankChannel() {
  return {
    selected: false, touched: false, phase: 'idle', value: null, goal: null, dirty: false, sent: false,
    reference: null, lastFeedback: null, lastFollowAt: 0,
  };
}

/** 녹화 버튼 불빛 · 카운트다운 깜빡 · 녹화 중 켬 */
export function recordLed(state) {
  if (state === 'countdown') return 'blink';
  if (state === 'recording') return 'on';
  return 'off';
}
