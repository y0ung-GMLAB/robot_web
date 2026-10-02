/** 조그 다이얼 · 돌린 만큼 상대 이동 · 단위는 **모터 deg** (감속비 미적용) · 2026-10-02
 *
 * 페이더(절대 위치·모션축 deg)와 역할을 나눈다 · 다이얼은 끝이 없는 상대
 * 이동이라 미세 조정에 쓴다.
 *
 * 입력 · 마우스로 잡고 돌리기(한 바퀴 = DETENTS 칸) · 휠 한 칸 = 한 칸 ·
 * 초점이 있을 때 ←/→ 또는 ↓/↑ = 한 칸 · 한 칸 = 화면에서 고른 단위(모터 deg).
 *
 * 보내는 법 · supervisor 는 **앞 조그가 끝나기 전 새 조그를 거절**한다
 * (`이전 조그가 아직 돌고 있습니다`) · 그래서 돌린 양을 쌓아 두고, 앞 요청이
 * 끝나는 대로 쌓인 만큼을 한 번에 보낸다 · 빨리 돌려도 칸을 잃지 않는다 ·
 * 그 거절이 오면 쌓인 양을 지키고 잠깐 뒤 다시 보낸다 · 다른 거절(리밋·
 * 오프 모드·서보 꺼짐)은 쌓인 양을 버리고 사유를 보여 준다.
 *
 * 경로는 기존 조그 그대로(`requestAcServoJog` · `requestDynamixelJog`) ·
 * 오프 모드·리밋·서보 상태 검사는 서버가 한다 · 화면은 리밋을 넘는 양을
 * 미리 잘라 보내지 않을 뿐이다.
 */

import { requestAcServoJog, requestDynamixelJog } from './api.js';
import { normalizeMotorTypeKey } from './format.js';

//: 한 바퀴를 몇 칸으로 나누는가 · 15° 마다 한 칸
const DETENTS = 24;
//: 한 번에 보내는 최대 이동량 · 서버 조그 상한(모터 360°)과 같다
const MAX_SEND_DEG = 360;
//: 앞 조그가 아직 돌 때 다시 보낼 간격
const RETRY_MS = 120;

//: 화면 선택지와 같아야 한다 (07-panel-manual.html #jogDialStep)
const JOG_DIAL_STEPS = Object.freeze([0.01, 0.1, 1, 10, 45]);

export function createJogDialController({ el, getLatestState, getSelectedAxis }) {
  let pendingDeg = 0;
  let inFlight = false;
  let retryTimer = null;
  let dragging = false;
  let lastAngle = null;
  let carry = 0;           // 드래그 중 한 칸이 안 된 나머지 각도
  let needleDeg = 0;       // 바늘 표시 각도 (돌린 만큼 따라 돈다)
  let lastMessage = '';

  function selectedMotor() {
    const axis = Number(getSelectedAxis());
    const motors = getLatestState()?.motors;
    if (!Number.isInteger(axis) || !Array.isArray(motors)) return null;
    return motors.find((motor) => Number(motor?.controller_index) === axis) || null;
  }

  function stepDeg() {
    const value = Number(el.jogDialStep?.value);
    return JOG_DIAL_STEPS.includes(value) ? value : 1;
  }

  function positionDeg(motor) {
    const value = Number(motor?.position_deg ?? motor?.position);
    return Number.isFinite(value) ? value : null;
  }

  function isDynamixel(motor) {
    // motion_test.js 의 motorTypeKey 와 같은 근거로 판정한다
    const key = normalizeMotorTypeKey(
      [motor?.motor_type, motor?.motor_type_label, motor?.transport,
        motor?.transport_label, motor?.driver_model, motor?.driver_name].join(' '),
      '',
    );
    return key === 'dynamixel';
  }

  function blockReason(motor) {
    if (!motor) return '모터를 먼저 선택하세요';
    if (String(motor.state || '') !== 'detected') return '선택 모터가 감지되지 않았습니다';
    if (motor.fault) return '선택 모터에 에러가 있습니다';
    if (!isDynamixel(motor) && motor.servo_on !== true) return '서보가 켜진 상태가 아닙니다';
    return '';
  }

  /** 리밋 안으로 자른 이동량 · 리밋을 모르면 그대로 */
  function clampToLimits(motor, delta) {
    const current = positionDeg(motor);
    if (current === null) return delta;
    const lower = Number(motor?.lower);
    const upper = Number(motor?.upper);
    let target = current + delta;
    if (Number.isFinite(lower)) target = Math.max(lower, target);
    if (Number.isFinite(upper)) target = Math.min(upper, target);
    return target - current;
  }

  // ---------------------------------------------------------------- //
  // 보내기
  // ---------------------------------------------------------------- //

  function addTicks(ticks) {
    if (!ticks) return;
    const motor = selectedMotor();
    const reason = blockReason(motor);
    if (reason) {
      lastMessage = reason;
      render();
      return;
    }
    pendingDeg += ticks * stepDeg();
    needleDeg += ticks * (360 / DETENTS);
    render();
    pump();
  }

  async function pump() {
    if (inFlight || retryTimer || Math.abs(pendingDeg) < 1e-9) return;
    const motor = selectedMotor();
    const reason = blockReason(motor);
    if (reason) {
      pendingDeg = 0;
      lastMessage = reason;
      render();
      return;
    }
    let delta = Math.max(-MAX_SEND_DEG, Math.min(MAX_SEND_DEG, pendingDeg));
    const clamped = clampToLimits(motor, delta);
    if (Math.abs(clamped) < 1e-9) {
      pendingDeg = 0;
      lastMessage = delta > 0 ? '상한에 닿았습니다' : '하한에 닿았습니다';
      render();
      return;
    }
    if (clamped !== delta) {
      // 리밋에서 남는 양은 버린다 · 계속 쌓이면 리밋에 붙은 채 헛돈다
      lastMessage = '리밋까지만 이동합니다';
      pendingDeg = clamped;
      delta = clamped;
    }
    pendingDeg -= delta;
    inFlight = true;
    render();
    try {
      const send = isDynamixel(motor) ? requestDynamixelJog : requestAcServoJog;
      const response = await send({
        axis: Number(motor.controller_index),
        relative_deg: delta,
      });
      if (response?.success === false) {
        const message = String(response?.message || '조그 거부');
        if (message.includes('이전 조그')) {
          // 앞 조그가 아직 돈다 · 이번 양을 되돌려 쌓고 잠깐 뒤 다시
          pendingDeg += delta;
          scheduleRetry();
        } else {
          pendingDeg = 0;
          lastMessage = message;
        }
      } else if (!lastMessage.startsWith('리밋')) {
        lastMessage = `${formatDeg(delta)} 보냄`;
      }
    } catch (error) {
      pendingDeg = 0;
      lastMessage = `조그 실패: ${error?.message || error}`;
    } finally {
      inFlight = false;
      render();
      if (!retryTimer) pump();
    }
  }

  function scheduleRetry() {
    if (retryTimer) return;
    retryTimer = window.setTimeout(() => {
      retryTimer = null;
      pump();
    }, RETRY_MS);
  }

  // ---------------------------------------------------------------- //
  // 입력
  // ---------------------------------------------------------------- //

  function angleOf(event) {
    const rect = el.jogDial.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    return (Math.atan2(event.clientY - cy, event.clientX - cx) * 180) / Math.PI;
  }

  function onPointerDown(event) {
    if (el.jogDial.getAttribute('aria-disabled') === 'true') return;
    dragging = true;
    lastAngle = angleOf(event);
    carry = 0;
    el.jogDial.setPointerCapture?.(event.pointerId);
    el.jogDial.focus();
    event.preventDefault();
  }

  function onPointerMove(event) {
    if (!dragging) return;
    const angle = angleOf(event);
    let diff = angle - lastAngle;
    if (diff > 180) diff -= 360;
    if (diff < -180) diff += 360;
    lastAngle = angle;
    carry += diff;
    const per = 360 / DETENTS;
    const ticks = Math.trunc(carry / per);
    if (ticks) {
      carry -= ticks * per;
      addTicks(ticks);   // 시계 방향 = + (화면 좌표계에서 각도가 커지는 쪽)
    }
  }

  function onPointerUp(event) {
    dragging = false;
    lastAngle = null;
    carry = 0;
    el.jogDial.releasePointerCapture?.(event.pointerId);
  }

  function onWheel(event) {
    if (el.jogDial.getAttribute('aria-disabled') === 'true') return;
    event.preventDefault();
    addTicks(event.deltaY < 0 ? 1 : -1);
  }

  function onKeyDown(event) {
    const plus = event.key === 'ArrowRight' || event.key === 'ArrowUp';
    const minus = event.key === 'ArrowLeft' || event.key === 'ArrowDown';
    if (!plus && !minus) return;
    event.preventDefault();
    addTicks(plus ? 1 : -1);
  }

  // ---------------------------------------------------------------- //
  // 화면
  // ---------------------------------------------------------------- //

  function formatDeg(value) {
    const digits = stepDeg() < 0.1 ? 2 : (stepDeg() < 1 ? 1 : 0);
    const sign = value > 0 ? '+' : '';
    return `${sign}${Number(value).toFixed(Math.max(digits, 2))}°`;
  }

  function render() {
    if (!el.jogDial) return;
    const motor = selectedMotor();
    const reason = blockReason(motor);
    el.jogDial.setAttribute('aria-disabled', reason ? 'true' : 'false');
    el.jogDial.title = reason || '돌리면 모터가 그만큼 움직입니다 · 휠·방향키도 됩니다 · 단위 = 모터 deg';
    if (el.jogDialNeedle) {
      el.jogDialNeedle.style.transform = `rotate(${needleDeg}deg)`;
    }
    if (el.jogDialPosition) {
      const position = positionDeg(motor);
      el.jogDialPosition.textContent = position === null ? '-' : `${position.toFixed(2)}°`;
    }
    if (el.jogDialPending) {
      const pending = pendingDeg;
      el.jogDialPending.textContent = Math.abs(pending) < 1e-9
        ? (inFlight ? '이동 중' : '대기')
        : `보낼 양 ${formatDeg(pending)}`;
    }
    if (el.jogDialMessage) {
      el.jogDialMessage.textContent = reason || lastMessage || '';
    }
  }

  function bindEvents() {
    if (!el.jogDial) return;
    el.jogDial.addEventListener('pointerdown', onPointerDown);
    el.jogDial.addEventListener('pointermove', onPointerMove);
    el.jogDial.addEventListener('pointerup', onPointerUp);
    el.jogDial.addEventListener('pointercancel', onPointerUp);
    el.jogDial.addEventListener('wheel', onWheel, { passive: false });
    el.jogDial.addEventListener('keydown', onKeyDown);
    el.jogDialStep?.addEventListener('change', render);
  }

  return {
    bindEvents,
    renderRuntimeState: render,
    /** 모터를 바꾸거나 프로젝트가 바뀌면 쌓인 양을 버린다 · 엉뚱한 모터로 가면 안 된다 */
    reset: () => {
      pendingDeg = 0;
      lastMessage = '';
      if (retryTimer) {
        window.clearTimeout(retryTimer);
        retryTimer = null;
      }
      render();
    },
  };
}
