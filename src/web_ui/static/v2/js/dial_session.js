/** UI v2 · 다이얼 한 번 잡기 · 목표 쌓기 · 속도 상한 · 놓을 때 (설계안 2026-10-09 · 수동 조작)
 *
 * 값은 모두 **모터 deg** · 조인트로 고르면 화면이 감속비를 곱해 넘긴다.
 * 규칙은 기존 다이얼(수정 목록 56)과 같다 ·
 *   50 ms 마다 목표 하나(임대 0.15 s 의 1/3) · 한 번에 1125 모터 deg/s × 0.05 s 까지만 다가간다
 *   보낸 만큼만 「보낸 목표」 로 친다(연결 직후 튀지 않게)
 *   입력이 200 ms 멈추고 다 보냈으면 · 도착(0.05°) 또는 1 s 지나면 놓는다 → 서버가 그 자리에 세운다
 *   목표는 모터 한계(lower/upper) 안으로 자른다 · 서버는 밖이면 거절만 한다
 */

export const SEND_PERIOD_MS = 50;
export const MAX_SPEED_DEG_S = 1125;
export const ARRIVE_DEG = 0.05;
export const IDLE_MS = 200;
export const RELEASE_AFTER_MS = 1000;
export const PX_PER_STEP = 24;
export const WHEEL_PX_PER_STEP = 100;
export const FINE_FACTOR = 0.1;

export function startSession({ axis, position, lower = -Infinity, upper = Infinity, now = 0 }) {
  return { axis, target: position, commanded: position, lower, upper, lastInputAt: now, hitLimit: '' };
}

/** 입력 하나 · delta 모터 deg · 한계에 닿으면 hitLimit */
export function addDelta(session, delta, now) {
  const wanted = session.target + Number(delta || 0);
  const clamped = Math.min(session.upper, Math.max(session.lower, wanted));
  session.hitLimit = clamped !== wanted ? (wanted > clamped ? '상한' : '하한') : '';
  session.target = clamped;
  session.lastInputAt = now;
  return session;
}

/** 이번에 보낼 목표 · 보낸 뒤에만 commanded 를 옮긴다 */
export function nextTarget(session, dtSec = SEND_PERIOD_MS / 1000, maxSpeed = MAX_SPEED_DEG_S) {
  const limit = maxSpeed * dtSec;
  const diff = session.target - session.commanded;
  return session.commanded + Math.max(-limit, Math.min(limit, diff));
}

export function markSent(session, value) {
  session.commanded = value;
}

export function pending(session) {
  return session.target - session.commanded;
}

/** 놓을 때인가 */
export function releaseDue(session, now, position) {
  if (now - session.lastInputAt < IDLE_MS) return false;
  if (Math.abs(pending(session)) > 1e-9) return false;
  const arrived = Number.isFinite(position) && Math.abs(position - session.target) < ARRIVE_DEG;
  return arrived || now - session.lastInputAt >= RELEASE_AFTER_MS;
}

/** 휠 한 번 · 픽셀로 맞춘 칸 수 · 트랙패드 잔 움직임은 모아서 한 칸 */
export function wheelPixels(event) {
  const scale = event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 800 : 1;
  return Number(event.deltaY || 0) * scale;
}
