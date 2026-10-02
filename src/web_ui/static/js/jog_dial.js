/** 조그 다이얼 · 돌린 만큼 상대 이동 · 단위는 **모터 deg** (감속비 미적용) · 2026-10-02
 *
 * 페이더(절대 위치·조인트 deg)와 역할을 나눈다 · 다이얼은 끝이 없는 상대
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
import { manualControlBlockReason } from './run_mode_state.js';

//: 한 바퀴를 몇 칸으로 나누는가 · 15° 마다 한 칸
const DETENTS = 24;
//: 한 번에 보내는 최대 이동량 · 서버 조그 상한(모터 360°)과 같다
const MAX_SEND_DEG = 360;
//: 앞 조그가 아직 돌 때 다시 보낼 간격
const RETRY_MS = 120;

//: 한 칸 크기 허용 범위 (모터 deg) · 화면 입력칸 min/max 와 같다
const STEP_MIN_DEG = 0.001;
const STEP_MAX_DEG = 360;

export function createJogDialController({ el, getLatestState, getSelectedAxis, onCapture = null }) {
  let pendingDeg = 0;
  let inFlight = false;
  let retryTimer = null;
  let dragging = false;
  let lastAngle = null;
  let carry = 0;           // 드래그 중 한 칸이 안 된 나머지 각도
  //: 눈금 링 표시 각도 · **화면 느낌 전용** · 기준 위치가 아니다
  //: (바늘을 없앤 이유 · 상대 이동인데 바늘이 「0점」처럼 읽혔다 · 2026-10-02)
  //: 눈금 24칸이 모두 같아서 서 있을 때는 어느 쪽이 기준인지 읽히지 않는다
  let ringDeg = 0;
  //: 쌓인 양을 비울 때마다 올린다 · 이미 날아간 요청의 응답이 비운 양을
  //: 되살리지 못하게 한다 (「이전 조그」 거절 → 다시 쌓기 경로)
  let pendingEpoch = 0;
  let lastMessage = '';

  function selectedMotor() {
    const axis = Number(getSelectedAxis());
    const motors = getLatestState()?.motors;
    if (!Number.isInteger(axis) || !Array.isArray(motors)) return null;
    return motors.find((motor) => Number(motor?.controller_index) === axis) || null;
  }

  /** 입력칸 값 · 범위 밖이거나 숫자가 아니면 null (돌려도 아무것도 안 보낸다) */
  function stepDeg() {
    const value = Number(String(el.jogDialStep?.value ?? '').trim());
    if (!Number.isFinite(value) || value < STEP_MIN_DEG || value > STEP_MAX_DEG) return null;
    return value;
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
    const modeReason = manualControlBlockReason();
    if (modeReason) return modeReason;
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
    const step = stepDeg();
    if (step === null) {
      lastMessage = `한 칸 크기는 ${STEP_MIN_DEG} ~ ${STEP_MAX_DEG} deg 숫자여야 합니다`;
      render();
      return;
    }
    pendingDeg += ticks * step;
    // 드래그는 손을 따라 이미 돌렸다(onPointerMove) · 휠·방향키만 한 칸씩 돌린다
    if (!dragging) ringDeg += ticks * (360 / DETENTS);
    render();
    pump();
  }

  /** 아직 안 보낸 쌓인 양만 버린다 · 이미 움직이는 조그는 끝까지 간다
   *
   * 정지 명령을 보내지 않는다 · 날아간 요청은 그대로 두고, 그 응답이
   * 「이전 조그」 거절이어도 세대가 바뀌었으면 다시 쌓지 않는다.
   */
  function clearPending(message) {
    const had = Math.abs(pendingDeg) > 1e-9 || Boolean(retryTimer);
    pendingDeg = 0;
    pendingEpoch += 1;
    if (retryTimer) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
    if (had && message) lastMessage = message;
    render();
    return had;
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
    const epoch = pendingEpoch;
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
          // 그 사이 사람이 쌓인 양을 비웠으면(세대 바뀜) 되살리지 않는다
          if (epoch === pendingEpoch) {
            pendingDeg += delta;
            scheduleRetry();
          }
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
    // 눈금 링은 손을 그대로 따라 돈다 · 한 칸이 안 돼도 움직여야 「잡고 있다」는 느낌이 난다
    ringDeg += diff;
    paintRing();
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
    render();   // 링의 「드래그 중」 표시를 내린다
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
    const step = stepDeg() ?? 1;
    const digits = step < 0.01 ? 3 : 2;
    const sign = value > 0 ? '+' : '';
    return `${sign}${Number(value).toFixed(digits)}°`;
  }

  /** 눈금 링만 다시 그린다 · 드래그 중 매 움직임마다 불러도 가볍다 */
  function paintRing() {
    if (!el.jogDialRing) return;
    el.jogDialRing.style.transform = `rotate(${ringDeg}deg)`;
    // 드래그 중엔 손을 바로 따라가고, 휠·방향키는 한 칸을 부드럽게 넘어간다
    el.jogDialRing.classList.toggle('dragging', dragging);
  }

  function render() {
    if (!el.jogDial) return;
    const motor = selectedMotor();
    const reason = blockReason(motor);
    el.jogDial.setAttribute('aria-disabled', reason ? 'true' : 'false');
    el.jogDial.title = reason || '돌리면 모터가 그만큼 움직입니다 · 휠·방향키도 됩니다 · 단위 = 모터 deg';
    paintRing();
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
    const busy = Boolean(reason) || inFlight || Math.abs(pendingDeg) > 1e-9;
    for (const button of [el.jogDialSetReference, el.jogDialSetLower, el.jogDialSetUpper]) {
      if (button) button.disabled = busy;
    }
    // 쌓인 양이 있을 때만 · 날아가는 조그만 있으면 비울 것이 없다
    if (el.jogDialCancelPending) {
      el.jogDialCancelPending.disabled = !(Math.abs(pendingDeg) > 1e-9 || retryTimer);
    }
  }

  /** 기준점 지정 · ± limit · 이동이 끝나 서 있을 때만 · 저장은 main.js 가 맡는다 */
  async function capture(kind) {
    const motor = selectedMotor();
    const reason = blockReason(motor);
    if (reason || inFlight || Math.abs(pendingDeg) > 1e-9) {
      lastMessage = reason || '이동이 끝난 뒤에 지정하세요';
      render();
      return;
    }
    const position = positionDeg(motor);
    if (position === null || typeof onCapture !== 'function') return;
    const result = await onCapture(kind, {
      axis: Number(motor.controller_index),
      motorDeg: position,
    });
    if (result?.message) lastMessage = result.message;
    render();
  }

  function bindEvents() {
    el.jogDialCancelPending?.addEventListener('click', () => {
      clearPending('쌓인 양을 버렸습니다 · 움직이던 조그는 끝까지 갑니다');
    });
    el.jogDialSetReference?.addEventListener('click', () => capture('reference'));
    el.jogDialSetLower?.addEventListener('click', () => capture('lower'));
    el.jogDialSetUpper?.addEventListener('click', () => capture('upper'));
    if (!el.jogDial) return;
    el.jogDial.addEventListener('pointerdown', onPointerDown);
    el.jogDial.addEventListener('pointermove', onPointerMove);
    el.jogDial.addEventListener('pointerup', onPointerUp);
    el.jogDial.addEventListener('pointercancel', onPointerUp);
    el.jogDial.addEventListener('wheel', onWheel, { passive: false });
    el.jogDial.addEventListener('keydown', onKeyDown);
    el.jogDialStep?.addEventListener('input', () => {
      // 단위를 바꾸면 옛 단위로 쌓인 양은 의미가 바뀐다 · 아직 안 보낸 것은 버린다
      lastMessage = '';
      clearPending('한 칸 크기를 바꿔 쌓인 양을 비웠습니다');
    });
  }

  return {
    bindEvents,
    renderRuntimeState: render,
    /** 모터를 바꾸거나 프로젝트가 바뀌면 쌓인 양을 버린다 · 엉뚱한 모터로 가면 안 된다 */
    reset: () => {
      lastMessage = '';
      clearPending('');
    },
  };
}
