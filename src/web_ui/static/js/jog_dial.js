/** 조그 썸휠 · 끌린 만큼 상대 이동 · 단위는 **모터 deg** (감속·기어비 미적용) · 2026-10-02 · 썸휠 2026-10-04
 *
 * 페이더(절대 위치·조인트 deg)와 역할을 나눈다 · 썸휠은 끝이 없는 상대
 * 이동이라 미세 조정에 쓴다 · 원형 다이얼을 눕혀 옆에서 본 모양(가로 드럼) ·
 * 원형보다 손목이 편하다는 사용자 요청.
 *
 * 입력 · 띠를 좌우로 끌기(PX_PER_TICK 픽셀 = 한 칸 · 오른쪽 = +) · 휠 한 칸 = 한 칸 ·
 * 위 ◀ ▶ 버튼 = 한 칸(길게 누르면 반복) · 초점이 있을 때 ←/→ 또는 ↓/↑ = 한 칸 ·
 * 한 칸 = 화면에서 고른 단위(모터 deg).
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
 *
 * 다이얼 OFF (2026-10-02) · 다이얼 대신 목표 위치(모터 deg)를 적고 「이동」 ·
 * 기존 절대 이동 경로(`requestAcServoAction` · `requestDynamixelAction`) ·
 * 시간은 보내지 않는다 → supervisor 가 모터 설정의 속도·가속 한계로 정한다 ·
 * 다이얼과 같은 모터 위치 · 같은 잠금(inFlight) · 같은 limit 버튼을 쓴다.
 */

import {
  requestAcServoAction,
  requestAcServoJog,
  requestDynamixelAction,
  requestDynamixelJog,
  requestMotionSafetyStop,
} from './api.js';
import { normalizeMotorTypeKey } from './format.js';
import { manualControlBlockReason } from './run_mode_state.js';

//: 한 바퀴를 몇 칸으로 나누는가 · 15° 마다 한 칸
//: 드래그 한 칸 · 눈금 간격(CSS `.jog-dial-ticks` 24px)과 같다
const PX_PER_TICK = 24;
//: ◀ ▶ 길게 누르기 · 처음 대기 · 반복 간격
const HOLD_DELAY_MS = 400;
const HOLD_REPEAT_MS = 120;
//: 한 번에 보내는 최대 이동량 · 서버 조그 상한(모터 360°)과 같다
const MAX_SEND_DEG = 360;
//: 앞 조그가 아직 돌 때 다시 보낼 간격
const RETRY_MS = 120;

//: 한 칸 크기 허용 범위 (모터 deg) · 화면 입력칸 min/max 와 같다
const STEP_MIN_DEG = 0.001;
const STEP_MAX_DEG = 360;

//: 다이얼 ON/OFF 기억 · 화면 편의값이라 브라우저에만 둔다
const DIAL_ENABLED_KEY = 'robot_web.jogDialEnabled';
//: 이만큼 안쪽이면 이미 그 위치 · 보내지 않는다 (모터 deg)
const TARGET_EPSILON_DEG = 1e-4;

function readDialEnabled() {
  try {
    return window.localStorage?.getItem(DIAL_ENABLED_KEY) !== '0';
  } catch {
    return true;
  }
}

function writeDialEnabled(enabled) {
  try {
    window.localStorage?.setItem(DIAL_ENABLED_KEY, enabled ? '1' : '0');
  } catch {
    // 저장 못 해도 이번 화면에서는 그대로 동작한다
  }
}

export function createJogDialController({ el, getLatestState, getSelectedAxis, onCapture = null }) {
  let dialEnabled = readDialEnabled();
  //: 사람이 목표 칸을 고쳤나 · 안 고쳤으면 지금 모터 위치를 채워 둔다
  let targetTouched = false;
  let pendingDeg = 0;
  let inFlight = false;
  let retryTimer = null;
  let dragging = false;
  let lastX = null;
  let carry = 0;           // 드래그 중 한 칸이 안 된 나머지 각도
  //: 눈금 링 표시 각도 · **화면 느낌 전용** · 기준 위치가 아니다
  //: (바늘을 없앤 이유 · 상대 이동인데 바늘이 「0점」처럼 읽혔다 · 2026-10-02)
  //: 눈금 24칸이 모두 같아서 서 있을 때는 어느 쪽이 기준인지 읽히지 않는다
  let ringOffsetPx = 0;
  //: 쌓인 양을 비울 때마다 올린다 · 이미 날아간 요청의 응답이 비운 양을
  //: 되살리지 못하게 한다 (「이전 조그」 거절 → 다시 쌓기 경로)
  let pendingEpoch = 0;
  let lastMessage = '';

  function selectedMotor() {
    // 고른 게 없으면 없다 · Number(null) 은 0 이라 0번 모터가 움직였다 (2026-10-02 사용자 보고)
    const raw = getSelectedAxis();
    if (raw === null || raw === undefined || String(raw).trim() === '') return null;
    const axis = Number(raw);
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
    // 드래그는 손을 따라 이미 밀었다(onPointerMove) · 휠·방향키·화살표만 한 칸씩 민다
    if (!dragging) ringOffsetPx += ticks * PX_PER_TICK;
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
  // 다이얼 OFF · 목표 위치로 이동
  // ---------------------------------------------------------------- //

  /** 목표 칸 값 · 숫자가 아니면 null */
  function targetDeg() {
    const text = String(el.jogTargetInput?.value ?? '').trim();
    if (text === '') return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  }

  /** 모터 운전 한계(= 조인트 매핑 환산값) 밖이면 사유 · 모르면 막지 않는다 */
  function targetLimitReason(motor, target) {
    const lower = Number(motor?.lower);
    const upper = Number(motor?.upper);
    if (Number.isFinite(lower) && target < lower) {
      return `목표 ${target}° 가 하한 ${lower}° 밖입니다 · 리밋은 조인트 매핑에서 정합니다`;
    }
    if (Number.isFinite(upper) && target > upper) {
      return `목표 ${target}° 가 상한 ${upper}° 밖입니다 · 리밋은 조인트 매핑에서 정합니다`;
    }
    return '';
  }

  async function moveToTarget() {
    if (dialEnabled) return;
    const motor = selectedMotor();
    const reason = blockReason(motor);
    if (reason || inFlight) {
      lastMessage = reason || '앞 요청이 끝난 뒤에 이동하세요';
      render();
      return;
    }
    const target = targetDeg();
    if (target === null) {
      lastMessage = '목표 위치(모터 deg)를 숫자로 입력하세요';
      render();
      return;
    }
    const limitReason = targetLimitReason(motor, target);
    if (limitReason) {
      lastMessage = limitReason;
      render();
      return;
    }
    const current = positionDeg(motor);
    if (current !== null && Math.abs(target - current) < TARGET_EPSILON_DEG) {
      lastMessage = '이미 그 위치입니다';
      render();
      return;
    }
    inFlight = true;
    lastMessage = `목표 ${target}° 로 이동 요청 중`;
    render();
    try {
      const send = isDynamixel(motor) ? requestDynamixelAction : requestAcServoAction;
      // duration_sec 없음 · supervisor 가 모터 설정 속도·가속 한계로 시간을 정한다
      const response = await send({
        axis: Number(motor.controller_index),
        target_deg: target,
      });
      lastMessage = response?.success === false
        ? String(response?.message || '이동 거부')
        : `목표 ${target}° 로 이동 시작`;
    } catch (error) {
      lastMessage = `이동 실패: ${error?.message || error}`;
    } finally {
      inFlight = false;
      render();
    }
  }

  function setDialEnabled(enabled) {
    dialEnabled = Boolean(enabled);
    writeDialEnabled(dialEnabled);
    // 모드를 바꾸면 아직 안 보낸 다이얼 양은 버린다 · 목표 칸은 지금 위치에서 시작
    clearPending('');
    targetTouched = false;
    lastMessage = '';
    render();
  }

  // ---------------------------------------------------------------- //
  // 입력
  // ---------------------------------------------------------------- //

  function onPointerDown(event) {
    if (el.jogDial.getAttribute('aria-disabled') === 'true') return;
    dragging = true;
    lastX = Number(event.clientX) || 0;
    carry = 0;
    el.jogDial.setPointerCapture?.(event.pointerId);
    el.jogDial.focus();
    event.preventDefault();
  }

  function onPointerMove(event) {
    if (!dragging) return;
    const x = Number(event.clientX) || 0;
    const diff = x - lastX;
    lastX = x;
    carry += diff;
    // 눈금 띠는 손을 그대로 따라 밀린다 · 한 칸이 안 돼도 움직여야 「잡고 있다」는 느낌이 난다
    ringOffsetPx += diff;
    paintRing();
    const ticks = Math.trunc(carry / PX_PER_TICK);
    if (ticks) {
      carry -= ticks * PX_PER_TICK;
      addTicks(ticks);   // 오른쪽으로 끌면 + (▶ · ArrowRight 와 같은 방향)
    }
  }

  function onPointerUp(event) {
    dragging = false;
    lastX = null;
    carry = 0;
    el.jogDial.releasePointerCapture?.(event.pointerId);
    render();   // 띠의 「드래그 중」 표시를 내린다
  }

  /** ◀ ▶ · 누르면 한 칸 · 잡고 있으면 HOLD_DELAY_MS 뒤부터 HOLD_REPEAT_MS 마다 한 칸 */
  function bindArrow(button, direction) {
    if (!button) return;
    let holdTimer = null;
    let repeatTimer = null;
    const stop = () => {
      if (holdTimer) window.clearTimeout(holdTimer);
      if (repeatTimer) window.clearInterval(repeatTimer);
      holdTimer = null;
      repeatTimer = null;
    };
    button.addEventListener('pointerdown', (event) => {
      if (button.disabled) return;
      event.preventDefault();
      addTicks(direction);
      stop();
      holdTimer = window.setTimeout(() => {
        repeatTimer = window.setInterval(() => addTicks(direction), HOLD_REPEAT_MS);
      }, HOLD_DELAY_MS);
    });
    for (const type of ['pointerup', 'pointercancel', 'pointerleave', 'blur']) {
      button.addEventListener(type, stop);
    }
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

  /** 눈금 띠만 다시 그린다 · 드래그 중 매 움직임마다 불러도 가볍다 */
  function paintRing() {
    if (!el.jogDialRing) return;
    el.jogDialRing.style.backgroundPositionX = `${ringOffsetPx}px`;
    // 드래그 중엔 손을 바로 따라가고, 휠·방향키·화살표는 한 칸을 부드럽게 넘어간다
    el.jogDialRing.classList.toggle('dragging', dragging);
  }

  function renderTarget(motor, reason) {
    el.jogDialBlock?.classList.toggle('dial-off', !dialEnabled);
    if (el.jogDialEnabled) el.jogDialEnabled.checked = dialEnabled;
    if (el.jogDialEnabledState) el.jogDialEnabledState.textContent = dialEnabled ? 'ON' : 'OFF';
    if (!el.jogTargetInput) return;
    // 안 고쳤으면 지금 모터 위치를 채운다 · 다이얼 표시와 같은 값
    const position = positionDeg(motor);
    if (!targetTouched && document.activeElement !== el.jogTargetInput) {
      el.jogTargetInput.value = position === null ? '' : String(Math.round(position * 1000) / 1000);
    }
    el.jogTargetInput.disabled = Boolean(reason);
    if (el.jogTargetMoveButton) {
      const target = targetDeg();
      const limitReason = target === null ? '' : targetLimitReason(motor, target);
      el.jogTargetMoveButton.disabled = Boolean(reason) || inFlight || target === null || Boolean(limitReason);
      el.jogTargetMoveButton.title = reason || limitReason
        || (target === null ? '목표 위치를 입력하세요' : `모터 ${target}° 로 이동`);
    }
  }

  function render() {
    if (!el.jogDial) return;
    const motor = selectedMotor();
    const reason = blockReason(motor);
    renderTarget(motor, reason);
    el.jogDial.setAttribute('aria-disabled', reason ? 'true' : 'false');
    el.jogDial.title = reason || '좌우로 끌면 모터가 그만큼 움직입니다 · 휠·방향키·◀ ▶ 도 됩니다 · 단위 = 모터 deg';
    for (const arrow of [el.jogDialMinus, el.jogDialPlus]) {
      if (arrow) arrow.disabled = Boolean(reason);
    }
    paintRing();
    if (el.jogDialPosition) {
      const position = positionDeg(motor);
      el.jogDialPosition.textContent = position === null ? '-' : `${position.toFixed(2)}°`;
    }
    if (el.jogDialPending) {
      const pending = pendingDeg;
      el.jogDialPending.textContent = Math.abs(pending) < 1e-9
        ? (inFlight ? '이동 중' : '대기')
        : `남은 이동 ${formatDeg(pending)}`;
    }
    if (el.jogDialMessage) {
      el.jogDialMessage.textContent = reason || lastMessage || '';
    }
    const busy = Boolean(reason) || inFlight || Math.abs(pendingDeg) > 1e-9;
    for (const button of [el.jogDialSetReference, el.jogDialSetLower, el.jogDialSetUpper]) {
      if (button) button.disabled = busy;
    }
    // 「동작 취소」는 늘 누를 수 있다 · 누를 일이 생긴 순간 찾기 쉬워야 한다 (2026-10-02)
  }

  /** 동작 취소 · 남은 다이얼 이동을 버리고 움직이는 조그·이동을 멈춘다 · 서보 ON 유지
   *
   * 정지는 「모터 동작 정지」와 같은 경로(`requestMotionSafetyStop`) · 수동 모드가
   * 아니어도 막지 않는다 (정지는 모든 모드에서 된다).
   */
  async function cancelMotion() {
    clearPending('');
    lastMessage = '동작 취소 요청 중';
    render();
    try {
      const response = await requestMotionSafetyStop();
      lastMessage = response?.success === false
        ? `동작 취소 실패: ${response?.message || '정지 거부'}`
        : '동작을 취소했습니다 · 서보 ON 유지';
    } catch (error) {
      lastMessage = `동작 취소 실패: ${error?.message || error}`;
    }
    render();
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
    el.jogDialCancelPending?.addEventListener('click', cancelMotion);
    el.jogDialSetReference?.addEventListener('click', () => capture('reference'));
    el.jogDialSetLower?.addEventListener('click', () => capture('lower'));
    el.jogDialSetUpper?.addEventListener('click', () => capture('upper'));
    el.jogDialEnabled?.addEventListener('change', () => setDialEnabled(el.jogDialEnabled.checked));
    el.jogTargetInput?.addEventListener('input', () => {
      targetTouched = true;
      render();
    });
    el.jogTargetInput?.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      moveToTarget();
    });
    el.jogTargetMoveButton?.addEventListener('click', moveToTarget);
    if (!el.jogDial) return;
    el.jogDial.addEventListener('pointerdown', onPointerDown);
    el.jogDial.addEventListener('pointermove', onPointerMove);
    el.jogDial.addEventListener('pointerup', onPointerUp);
    el.jogDial.addEventListener('pointercancel', onPointerUp);
    el.jogDial.addEventListener('wheel', onWheel, { passive: false });
    el.jogDial.addEventListener('keydown', onKeyDown);
    bindArrow(el.jogDialMinus, -1);
    bindArrow(el.jogDialPlus, 1);
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
      // 다른 모터의 목표값이 남으면 엉뚱한 곳으로 간다 · 새 모터 위치로 다시 채운다
      targetTouched = false;
      clearPending('');
    },
  };
}
