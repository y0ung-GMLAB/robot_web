/** 조그 다이얼 · 끌린 만큼 상대 이동 · 단위는 **모터 deg** (감속·기어비 미적용) · 2026-10-02 · 가로 드럼 2026-10-04
 *
 * 페이더(절대 위치·조인트 deg)와 역할을 나눈다 · 다이얼은 끝이 없는 상대
 * 이동이라 미세 조정에 쓴다 · 원형 다이얼을 눕혀 옆에서 본 모양(가로 드럼) ·
 * 원형보다 손목이 편하다는 사용자 요청.
 *
 * 입력 · 띠를 좌우로 끌기(PX_PER_TICK 픽셀 = 한 칸 · 오른쪽 = +) · 휠 한 칸 = 한 칸 ·
 * 위 ◀ ▶ 버튼 = 한 칸(길게 누르면 반복) · 초점이 있을 때 ←/→ 또는 ↓/↑ = 한 칸 ·
 * 한 칸 = 화면에서 고른 단위(모터 deg).
 *
 * 보내는 법 (2026-10-07 · 수정 목록 56) · 페이더와 같은 **실시간 스트림** `/ws/manual-stream` ·
 * 전에는 조그를 한 번에 하나씩 보냈다 · supervisor 가 앞 조그가 끝나기 전 새 조그를
 * 거절해서(최소 0.15 s + 정지 판정) 칸마다 가다 서다 하고 늦게 따라왔다(실물 2026-10-07).
 * 지금은 처음 돌린 순간 모터 위치를 잡고, 돌린 칸만큼 목표를 옮겨 50 ms 마다 보낸다 ·
 * 한 번에 옮기는 양은 `MAX_SPEED_DEG_S` × 50 ms 로 자른다(휙 돌려도 최고속으로 튀지 않음) ·
 * 목표는 모터 운전 한계(lower/upper) 안으로 자른다(서버도 다시 자른다) ·
 * 입력이 멈추고 도착하면(또는 잠시 뒤) `release` → supervisor 가 지금 자리에 세운다.
 * 오프·스케줄 모드 · 서보 꺼짐 · 리밋은 서버가 다시 본다 · 거절은 그대로 보여 준다.
 *
 * ON/OFF 스위치 (수정 목록 52) · 끄면 다이얼만 잠근다(끌기·휠·키·◀ ▶ 무시 · 진행 중이면
 * 세움) · 칸은 숨기지 않는다(옆 칸이 밀리지 않게 · 41) · 목표 위치 입력·「이동」 은 스위치와 무관.
 *
 * 목표 위치 (2026-10-02) · 목표 위치(모터 deg)를 적고 「이동」 ·
 * 기존 절대 이동 경로(`requestAcServoAction` · `requestDynamixelAction`) ·
 * 시간은 보내지 않는다 → supervisor 가 모터 설정의 속도·가속 한계로 정한다 ·
 * 다이얼과 같은 모터 위치 · 같은 잠금(inFlight) · 같은 limit 버튼을 쓴다 ·
 * 다이얼과 늘 같이 보인다(ON/OFF 토글 삭제 · 2026-10-06) · 다이얼 양이 남아 있으면
 * 목표 이동을 막는다(두 이동이 겹치지 않게).
 */

import {
  requestAcServoAction,
  requestDynamixelAction,
  requestMotionSafetyStop,
} from './api.js';
import { normalizeMotorTypeKey } from './format.js';
import { manualControlBlockReason } from './run_mode_state.js';
import { inRadPayload } from './unit_view.js';

//: 한 바퀴를 몇 칸으로 나누는가 · 15° 마다 한 칸
//: 드래그 한 칸 · 눈금 간격(CSS `.jog-dial-ticks` 24px)과 같다
const PX_PER_TICK = 24;
//: ◀ ▶ 길게 누르기 · 처음 대기 · 반복 간격
const HOLD_DELAY_MS = 400;
const HOLD_REPEAT_MS = 120;
//: 스트림 전송 주기 · 페이더와 같다 · supervisor 임대 0.15 s 의 1/3
const SEND_PERIOD_MS = 50;
//: 한 번에 옮기는 목표의 상한 속도 · supervisor 기본 조그 속도(모터 deg/s) · 56
const MAX_SPEED_DEG_S = 1125;
//: 이만큼 안쪽이면 도착 · 놓는다 (모터 deg)
const ARRIVE_DEG = 0.05;
//: 목표에 다 보낸 뒤 이만큼 지나도 도착이 안 보이면 놓는다(서버가 지금 자리에 세움)
const RELEASE_AFTER_MS = 1000;
//: 휠 · 이만큼 굴리면 한 칸 (px) · 트랙패드가 한 번에 수십 칸 가지 않게 · 56
const WHEEL_PX_PER_TICK = 100;
//: Shift · 한 칸의 1/10
const FINE_FACTOR = 0.1;
//: 스위치 상태 · 브라우저마다 기억 · 옛 키 그대로(41 전 「썸휠 ON/OFF」)
const ENABLED_KEY = 'robot_web.jogDialEnabled';

//: 한 칸 크기 허용 범위 (모터 deg) · 화면 입력칸 min/max 와 같다
const STEP_MIN_DEG = 0.001;
const STEP_MAX_DEG = 360;

//: 이만큼 안쪽이면 이미 그 위치 · 보내지 않는다 (모터 deg)
const TARGET_EPSILON_DEG = 1e-4;

export function createJogDialController({ el, getLatestState, getSelectedAxis, onCapture = null }) {
  //: 사람이 목표 칸을 고쳤나 · 안 고쳤으면 지금 모터 위치를 채워 둔다
  let targetTouched = false;
  //: 목표 위치 「이동」 요청 중
  let inFlight = false;
  let dragging = false;
  let lastX = null;
  let carry = 0;           // 드래그 중 한 칸이 안 된 나머지 픽셀
  let wheelCarry = 0;      // 휠 · 한 칸이 안 된 나머지 픽셀
  //: 눈금 띠 표시 위치 · **화면 느낌 전용** · 기준 위치가 아니다
  let ringOffsetPx = 0;
  let lastMessage = '';
  let enabled = loadEnabled();

  //: 스트림 한 번(잡은 순간부터 놓을 때까지)
  //:   axis · anchor(잡은 순간 모터 위치) · target(돌린 만큼 옮긴 목표) · commanded(보낸 목표)
  //:   lastInputAt · sentAllAt(commanded 가 target 에 닿은 시각)
  let session = null;
  let sendTimer = null;
  let socket = null;
  let socketReady = false;

  function loadEnabled() {
    try {
      return window.localStorage?.getItem(ENABLED_KEY) !== '0';
    } catch {
      return true;
    }
  }

  function saveEnabled(value) {
    try {
      window.localStorage?.setItem(ENABLED_KEY, value ? '1' : '0');
    } catch {
      // 기억 못 해도 지금 화면에서는 된다
    }
  }

  function selectedMotor() {
    // 고른 게 없으면 없다 · Number(null) 은 0 이라 0번 모터가 움직였다 (2026-10-02 사용자 보고)
    const raw = getSelectedAxis();
    if (raw === null || raw === undefined || String(raw).trim() === '') return null;
    const axis = Number(raw);
    const motors = getLatestState()?.motors;
    if (!Number.isInteger(axis) || !Array.isArray(motors)) return null;
    return motors.find((motor) => Number(motor?.controller_index) === axis) || null;
  }

  function motorForAxis(axis) {
    const motors = getLatestState()?.motors;
    if (!Array.isArray(motors)) return null;
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

  /** 다이얼만의 사유 · 스위치가 꺼졌으면 잠금 (목표 위치 이동은 무관) */
  function dialBlockReason(motor) {
    if (!enabled) return '다이얼 OFF · 위 스위치로 켜세요';
    return blockReason(motor);
  }

  /** 모터 운전 한계 안으로 · 모르면 그대로 */
  function clampToLimits(motor, target) {
    const lower = Number(motor?.lower);
    const upper = Number(motor?.upper);
    let out = target;
    if (Number.isFinite(lower)) out = Math.max(lower, out);
    if (Number.isFinite(upper)) out = Math.min(upper, out);
    return out;
  }

  // ---------------------------------------------------------------- //
  // 스트림
  // ---------------------------------------------------------------- //

  function ensureSocket() {
    if (socket) return;
    const Socket = globalThis.WebSocket;
    if (typeof Socket !== 'function') {
      lastMessage = '이 브라우저에서 실시간 연결을 열 수 없습니다';
      return;
    }
    const protocol = globalThis.location?.protocol === 'https:' ? 'wss' : 'ws';
    socket = new Socket(`${protocol}://${globalThis.location?.host || ''}/ws/manual-stream`);
    socketReady = false;
    socket.onopen = () => {
      // 다이얼은 모터 deg 를 바로 보낸다 · 조인트 매핑 변환이 없어 개정 확인이 필요 없다
      socket?.send(JSON.stringify({ type: 'hello' }));
    };
    socket.onmessage = (event) => {
      let payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (payload?.type === 'hello_ok') {
        socketReady = true;
        return;
      }
      if (payload?.type === 'error') {
        lastMessage = payload.message || '서버가 다이얼 연결을 거절했습니다';
        render();
        return;   // 서버가 곧 닫는다 · onclose 가 정리한다
      }
      if (payload?.type === 'result' && payload.success === false) {
        // 거절(리밋 · 서보 꺼짐 · 모드 등) · 이번 돌림은 끝낸다 · 서버가 세운다
        lastMessage = String(payload.message || '다이얼 이동 거부');
        endSession(true);
      }
    };
    socket.onclose = () => {
      socket = null;
      socketReady = false;
      // 끊기면 서버가 만진 축을 지금 자리에 세운다 · 화면도 이번 돌림을 끝낸다
      if (session) {
        session = null;
        stopTimer();
        render();
      }
    };
    socket.onerror = () => {};
  }

  function send(payload) {
    if (!socket || !socketReady || socket.readyState !== 1) return false;
    // 화면은 모터 deg · 서버에는 rad · 수정 목록 6-4
    socket.send(JSON.stringify(inRadPayload(payload)));
    return true;
  }

  function startTimer() {
    if (sendTimer) return;
    sendTimer = window.setInterval(tickStream, SEND_PERIOD_MS);
  }

  function stopTimer() {
    if (sendTimer) {
      window.clearInterval(sendTimer);
      sendTimer = null;
    }
  }

  /** 50 ms 마다 · 보낸 목표를 돌린 목표 쪽으로 속도 상한만큼 옮겨 보낸다 */
  function tickStream() {
    if (!session) {
      stopTimer();
      return;
    }
    const motor = motorForAxis(session.axis);
    const reason = blockReason(motor);
    if (reason) {
      lastMessage = reason;
      endSession(true);
      return;
    }
    const now = Date.now();
    const maxStep = MAX_SPEED_DEG_S * (SEND_PERIOD_MS / 1000);
    const diff = session.target - session.commanded;
    const next = session.commanded + Math.max(-maxStep, Math.min(maxStep, diff));
    // **보낸 것만** 앞으로 간다 · 연결 전에 혼자 앞서 나가면 연결 직후 큰 목표가 한 번에 간다(튐)
    if (!send({ type: 'target', axis: session.axis, target_deg: next })) {
      render();
      return;
    }
    session.commanded = next;
    if (Math.abs(session.target - session.commanded) < 1e-9) {
      if (!session.sentAllAt) session.sentAllAt = now;
    } else {
      session.sentAllAt = 0;
    }
    // 입력이 멈췄고 목표를 다 보냈으면 · 도착했거나 잠시 지나면 놓는다
    const position = positionDeg(motor);
    const arrived = position !== null && Math.abs(position - session.target) < ARRIVE_DEG;
    const idle = now - session.lastInputAt > SEND_PERIOD_MS * 4;
    if (session.sentAllAt && idle && (arrived || now - session.sentAllAt > RELEASE_AFTER_MS)) {
      endSession(true);
      return;
    }
    render();
  }

  /** 이번 돌림을 끝낸다 · `release` 면 서버가 지금 자리에 세운다 */
  function endSession(release) {
    if (!session) return;
    const axis = session.axis;
    session = null;
    stopTimer();
    if (release) send({ type: 'release', axes: [axis] });
    render();
  }

  // ---------------------------------------------------------------- //
  // 입력 → 목표
  // ---------------------------------------------------------------- //

  function addTicks(ticks, fine = false) {
    if (!ticks) return;
    const motor = selectedMotor();
    const reason = dialBlockReason(motor);
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
    const axis = Number(motor.controller_index);
    if (session && session.axis !== axis) endSession(true);
    if (!session) {
      const position = positionDeg(motor);
      if (position === null) {
        lastMessage = '모터 위치를 아직 모릅니다';
        render();
        return;
      }
      session = {
        axis, anchor: position, target: position, commanded: position,
        lastInputAt: Date.now(), sentAllAt: 0,
      };
      lastMessage = '';
    }
    const wanted = session.target + ticks * step * (fine ? FINE_FACTOR : 1);
    const bounded = clampToLimits(motor, wanted);
    if (Math.abs(bounded - wanted) > 1e-9) {
      lastMessage = wanted > bounded ? '상한에 닿았습니다' : '하한에 닿았습니다';
    }
    session.target = bounded;
    session.lastInputAt = Date.now();
    session.sentAllAt = 0;
    // 드래그는 손을 따라 이미 밀었다(onPointerMove) · 휠·방향키·화살표만 한 칸씩 민다
    if (!dragging) ringOffsetPx += ticks * PX_PER_TICK;
    ensureSocket();
    startTimer();
    render();
  }

  // ---------------------------------------------------------------- //
  // 목표 위치로 이동
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
    const motor = selectedMotor();
    const reason = blockReason(motor);
    if (reason || inFlight || hasPending()) {
      lastMessage = reason || '앞 이동이 끝난 뒤에 이동하세요';
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
      const sendAction = isDynamixel(motor) ? requestDynamixelAction : requestAcServoAction;
      // duration_sec 없음 · supervisor 가 모터 설정 속도·가속 한계로 시간을 정한다
      const response = await sendAction({
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

  /** 다이얼이 아직 모터를 몰고 있나 (돌린 목표에 도착해 놓기 전까지) */
  function hasPending() {
    return Boolean(session);
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
      addTicks(ticks, Boolean(event.shiftKey));   // 오른쪽으로 끌면 +
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
      const fine = Boolean(event.shiftKey);
      addTicks(direction, fine);
      stop();
      holdTimer = window.setTimeout(() => {
        repeatTimer = window.setInterval(() => addTicks(direction, fine), HOLD_REPEAT_MS);
      }, HOLD_DELAY_MS);
    });
    for (const type of ['pointerup', 'pointercancel', 'pointerleave', 'blur']) {
      button.addEventListener(type, stop);
    }
  }

  /** 휠 · 굴린 양(`deltaY`)을 픽셀로 맞춰 쌓는다 · 트랙패드의 잔 이벤트가 한 칸씩 되지 않게 · 56 */
  function onWheel(event) {
    if (el.jogDial.getAttribute('aria-disabled') === 'true') return;
    event.preventDefault();
    const mode = Number(event.deltaMode) || 0;   // 0 px · 1 줄 · 2 쪽
    const scale = mode === 1 ? 40 : (mode === 2 ? 800 : 1);
    wheelCarry += -Number(event.deltaY || 0) * scale;   // 위로 굴리면 +
    const ticks = Math.trunc(wheelCarry / WHEEL_PX_PER_TICK);
    if (ticks) {
      wheelCarry -= ticks * WHEEL_PX_PER_TICK;
      addTicks(ticks, Boolean(event.shiftKey));
    }
  }

  function onKeyDown(event) {
    const plus = event.key === 'ArrowRight' || event.key === 'ArrowUp';
    const minus = event.key === 'ArrowLeft' || event.key === 'ArrowDown';
    if (!plus && !minus) return;
    event.preventDefault();
    // 잠금 검사는 addTicks 가 한다(스위치 OFF 포함) · 52
    addTicks(plus ? 1 : -1, Boolean(event.shiftKey));
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

  function renderSwitch() {
    const button = el.jogDialEnabledSwitch;
    if (!button) return;
    button.setAttribute('aria-checked', enabled ? 'true' : 'false');
    button.textContent = enabled ? '다이얼 ON' : '다이얼 OFF';
    button.classList.toggle('on', enabled);
    el.jogDial?.classList.toggle('locked', !enabled);
  }

  function renderTarget(motor, reason) {
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
      el.jogTargetMoveButton.disabled = Boolean(reason) || inFlight || hasPending()
        || target === null || Boolean(limitReason);
      el.jogTargetMoveButton.title = reason || limitReason
        || (target === null ? '목표 위치를 입력하세요' : `모터 ${target}° 로 이동`);
    }
  }

  function render() {
    if (!el.jogDial) return;
    const motor = selectedMotor();
    const reason = blockReason(motor);
    const dialReason = dialBlockReason(motor);
    renderSwitch();
    renderTarget(motor, reason);
    el.jogDial.setAttribute('aria-disabled', dialReason ? 'true' : 'false');
    el.jogDial.title = dialReason || '좌우로 끌면 모터가 그만큼 움직입니다 · 휠·방향키·◀ ▶ 도 됩니다 · Shift = 1/10 칸 · 단위 = 모터 deg';
    for (const arrow of [el.jogDialMinus, el.jogDialPlus]) {
      if (arrow) arrow.disabled = Boolean(dialReason);
    }
    paintRing();
    if (el.jogDialPosition) {
      const position = positionDeg(motor);
      el.jogDialPosition.textContent = position === null ? '-' : `${position.toFixed(2)}°`;
    }
    if (el.jogDialPending) {
      let text = inFlight ? '이동 중' : '대기';
      if (session) {
        const position = positionDeg(motorForAxis(session.axis));
        const left = position === null ? session.target - session.commanded : session.target - position;
        text = Math.abs(left) < ARRIVE_DEG ? '이동 중' : `남은 이동 ${formatDeg(left)}`;
      }
      el.jogDialPending.textContent = text;
    }
    if (el.jogDialMessage) {
      el.jogDialMessage.textContent = reason || lastMessage || '';
    }
    const busy = Boolean(reason) || inFlight || hasPending();
    for (const button of [el.jogDialSetReference, el.jogDialSetLower, el.jogDialSetUpper]) {
      if (button) button.disabled = busy;
    }
    // 「동작 취소」는 늘 누를 수 있다 · 누를 일이 생긴 순간 찾기 쉬워야 한다 (2026-10-02)
  }

  /** 동작 취소 · 다이얼이 몰던 것을 놓고 움직이는 이동을 멈춘다 · 서보 ON 유지
   *
   * 정지는 「모터 동작 정지」와 같은 경로(`requestMotionSafetyStop`) · 수동 모드가
   * 아니어도 막지 않는다 (정지는 모든 모드에서 된다).
   */
  async function cancelMotion() {
    endSession(true);
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
    if (reason || inFlight || hasPending()) {
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

  function setEnabled(value) {
    enabled = Boolean(value);
    saveEnabled(enabled);
    if (!enabled) {
      // 끄면 잠근다 · 돌리던 것은 지금 자리에 세운다 · 칸은 그대로 둔다(41)
      endSession(true);
      wheelCarry = 0;
      carry = 0;
      lastMessage = '';
    }
    render();
  }

  function bindEvents() {
    el.jogDialCancelPending?.addEventListener('click', cancelMotion);
    el.jogDialEnabledSwitch?.addEventListener('click', () => setEnabled(!enabled));
    el.jogDialSetReference?.addEventListener('click', () => capture('reference'));
    el.jogDialSetLower?.addEventListener('click', () => capture('lower'));
    el.jogDialSetUpper?.addEventListener('click', () => capture('upper'));
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
      // 단위를 바꾸면 돌리던 것은 지금 자리에 세운다 · 새 단위로 다시 돌린다
      lastMessage = session ? '한 칸 크기를 바꿔 지금 자리에 세웠습니다' : '';
      endSession(true);
      render();
    });
    window.addEventListener?.('beforeunload', () => {
      endSession(true);
      socket?.close();
    });
  }

  return {
    bindEvents,
    renderRuntimeState: render,
    /** 모터를 바꾸거나 프로젝트가 바뀌면 돌리던 것을 세운다 · 엉뚱한 모터로 가면 안 된다 */
    reset: () => {
      lastMessage = '';
      // 다른 모터의 목표값이 남으면 엉뚱한 곳으로 간다 · 새 모터 위치로 다시 채운다
      targetTouched = false;
      endSession(true);
      // 돌리던 것이 없어도 다시 그린다 · 새 모터가 골라졌다(안 그리면 「모터를 먼저 선택하세요」 가 남음)
      render();
    },
  };
}
