/** 수동 페이더 · 모션 ID를 잡고 끌면 실시간으로 모터가 따라온다 · §6-310
 *
 * 흐름 · 슬라이더 input → 50ms(20Hz) 묶음 전송 → `/ws/manual-stream` →
 * supervisor 스트림 경로(축별 임대 0.15s · 재생이 선점 · 준비 검사) →
 * 모터 · 놓으면(change) release 가 나가 **지금 서 있는 자리**에 선다.
 *
 * 변환은 여기(화면)가 한다 · 모션축 deg → 모터 deg:
 *
 *     motor = reference + (joint + offset) × scale × sign × gear
 *
 * (`motion_mapping_manager._motion_to_motor_target` 와 같은 식) · 그래서
 * 소켓 인사에 `base_mapping_revision` 을 실어, 다른 화면이 모션축 설정을
 * 고친 뒤의 **낡은 변환표**는 서버가 그 자리에서 거절한다.
 *
 * 페이더 범위 = 매핑의 모션 최소·최대(모션 deg) · supervisor 모터
 * 리밋이 뒤를 받친다 · 잡지 않은 페이더는 실제 모터 위치를 따라간다.
 */

import { fetchMotionMapping, fetchMotionMappings } from './api.js';
import { escapeHtml } from './format.js';

//: 전송 주기 · supervisor 임대 0.15s 의 1/3 · 한 번 빠져도 임대가 산다
const SEND_PERIOD_MS = 50;

export function createManualFaderController({ el, getLatestState }) {
  let mapping = null;        // { fileId, revision, rows }
  let refreshing = false;
  let panelWasVisible = false;
  let socket = null;
  let socketReady = false;
  let helloWaiters = [];
  let sendTimer = null;
  const activeAxes = new Map();   // axis → { row, jointDeg }
  let renderedSignature = '';

  // ------------------------------------------------------------------ //
  // 매핑 → 페이더 행
  // ------------------------------------------------------------------ //

  function rowsFromMapping(draft) {
    const rows = Array.isArray(draft?.mappings) ? draft.mappings : [];
    return rows
      .filter((row) => row?.enabled !== false)
      .map((row) => {
        const axis = Number(row?.motor_axis);
        const lower = Number(row?.motion_lower_deg);
        const upper = Number(row?.motion_upper_deg);
        return {
          motionId: String(row?.motion_id || ''),
          axis,
          lower,
          upper,
          gear: numberOr(row?.gear_ratio, 1),
          scale: numberOr(row?.scale, 1),
          sign: row?.invert ? -1 : 1,
          offset: numberOr(row?.offset_deg, 0),
          reference: row?.reference_enabled === false
            ? 0
            : numberOr(row?.reference_position_deg, 0),
        };
      })
      .filter((row) => (
        row.motionId
        && Number.isInteger(row.axis) && row.axis >= 0
        && Number.isFinite(row.lower) && Number.isFinite(row.upper)
        && row.upper > row.lower
      ));
  }

  function jointToMotor(row, jointDeg) {
    return row.reference + (jointDeg + row.offset) * row.scale * row.sign * row.gear;
  }

  function motorToJoint(row, motorDeg) {
    const factor = row.scale * row.sign * row.gear;
    if (!factor) return null;
    return (motorDeg - row.reference) / factor - row.offset;
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const listing = await fetchMotionMappings();
      const fileId = String(listing?.active_file_id || '');
      if (!fileId) {
        mapping = null;
        setMessage('모션축 설정이 없습니다 · 모터 관리 화면에서 먼저 만드세요');
        render();
        return;
      }
      const payload = await fetchMotionMapping(fileId);
      if (payload?.success === false || !payload?.mapping) {
        // 못 읽었으면 들고 있던 것을 유지한다 · §6-237 과 같은 이유
        if (!mapping) setMessage('모션축 설정을 아직 못 읽었습니다 · 잠시 후 다시 시도하세요');
        return;
      }
      mapping = {
        fileId: payload.file?.id || fileId,
        revision: String(
          payload.file?.mapping_revision || payload.file?.revision || '',
        ),
        rows: rowsFromMapping(payload.mapping),
      };
      disconnect();
      setMessage(mapping.rows.length
        ? '페이더를 잡는 동안만 전송합니다 · 놓으면 그 자리에 섭니다'
        : '모션 범위(최소·최대)가 설정된 모션 ID가 없습니다');
      render();
    } catch (error) {
      if (!mapping) setMessage(`모션축 설정 확인 실패: ${error?.message || error}`);
    } finally {
      refreshing = false;
    }
  }

  // ------------------------------------------------------------------ //
  // 소켓
  // ------------------------------------------------------------------ //

  function ensureSocket() {
    if (socket && socketReady) return Promise.resolve(true);
    if (socket) {
      return new Promise((resolve) => helloWaiters.push(resolve));
    }
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(`${protocol}://${location.host}/ws/manual-stream`);
    const waiters = new Promise((resolve) => helloWaiters.push(resolve));
    socket.onopen = () => {
      socket.send(JSON.stringify({
        type: 'hello',
        mapping_file_id: mapping?.fileId || '',
        base_mapping_revision: mapping?.revision || '',
      }));
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
        helloWaiters.splice(0).forEach((resolve) => resolve(true));
        return;
      }
      if (payload?.type === 'error') {
        setMessage(payload.message || '서버가 페이더 연결을 거절했습니다');
        return; // 서버가 곧 닫는다 · onclose 가 정리한다
      }
      if (payload?.type === 'result' && payload.success === false) {
        const axisText = payload.axis ?? payload.axes ?? '';
        setMessage(`모터 ${axisText}: ${payload.message || '거부됨'}`);
      }
    };
    socket.onclose = () => {
      socket = null;
      socketReady = false;
      helloWaiters.splice(0).forEach((resolve) => resolve(false));
      stopSending();   // 끊기면 서버가 만진 축을 현재 위치에 세운다
    };
    socket.onerror = () => {};
    return waiters;
  }

  function disconnect() {
    stopSending();
    if (socket) socket.close();
    socket = null;
    socketReady = false;
  }

  function sendNow(payload) {
    if (socket && socketReady && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  function startSending() {
    if (sendTimer) return;
    sendTimer = window.setInterval(() => {
      if (!activeAxes.size) {
        stopSending();
        return;
      }
      activeAxes.forEach((entry, axis) => {
        sendNow({
          type: 'target',
          axis,
          target_deg: jointToMotor(entry.row, entry.jointDeg),
          motion_id: entry.row.motionId,
          motion_deg: entry.jointDeg,
        });
      });
    }, SEND_PERIOD_MS);
  }

  function stopSending() {
    if (sendTimer) {
      window.clearInterval(sendTimer);
      sendTimer = null;
    }
    activeAxes.clear();
  }

  // ------------------------------------------------------------------ //
  // 화면
  // ------------------------------------------------------------------ //

  function setMessage(text) {
    if (el.manualFaderMessage) el.manualFaderMessage.textContent = text;
  }

  function motorForAxis(axis) {
    const motors = getLatestState()?.motors;
    if (!Array.isArray(motors)) return null;
    return motors.find((motor) => Number(motor?.controller_index) === axis) || null;
  }

  function faderBlockReason(motor) {
    if (!motor) return '런타임에서 이 모터를 찾지 못했습니다';
    if (String(motor.state || '') !== 'detected') return '모터가 감지되지 않았습니다';
    if (motor.fault) return '모터에 에러가 있습니다';
    if (motor.servo_on !== true && String(motor.motor_type || '') !== 'dynamixel') {
      return '서보가 켜진 상태가 아닙니다';
    }
    return '';
  }

  function render() {
    if (!el.manualFaderList) return;
    const rows = mapping?.rows || [];
    const signature = JSON.stringify([mapping?.fileId, mapping?.revision,
      rows.map((row) => [row.motionId, row.axis, row.lower, row.upper])]);
    if (signature === renderedSignature) return;
    renderedSignature = signature;
    if (!rows.length) {
      el.manualFaderList.innerHTML = '';
      return;
    }
    el.manualFaderList.innerHTML = rows.map((row) => `
      <div class="manual-fader-row" data-fader-axis="${row.axis}">
        <div class="manual-fader-label">
          <strong>${escapeHtml(row.motionId)}</strong>
          <span>모터 ${row.axis}</span>
        </div>
        <input type="range" class="manual-fader-slider"
          aria-label="${escapeHtml(row.motionId)} 모션 각도 (deg)"
          min="${row.lower}" max="${row.upper}" step="0.05" value="${row.lower}"
          data-fader-slider="${row.axis}">
        <div class="manual-fader-value mono">
          <span data-fader-joint="${row.axis}">-</span>°
          <small>(모터 <span data-fader-motor="${row.axis}">-</span>°)</small>
        </div>
      </div>`).join('');
  }

  /** 잡지 않은 페이더는 실제 위치를 따라간다 · 잡은 것은 손이 주인이다 */
  function renderRuntimeState() {
    const host = el.manualFaderList?.closest('[data-workspace-panel]');
    const visible = Boolean(host) && !host.classList.contains('hidden');
    if (visible && !panelWasVisible && !refreshing) refresh();
    panelWasVisible = visible;
    if (!visible || !mapping?.rows?.length) return;
    render();
    mapping.rows.forEach((row) => {
      const slider = el.manualFaderList.querySelector(`[data-fader-slider="${row.axis}"]`);
      const jointOut = el.manualFaderList.querySelector(`[data-fader-joint="${row.axis}"]`);
      const motorOut = el.manualFaderList.querySelector(`[data-fader-motor="${row.axis}"]`);
      if (!slider) return;
      const motor = motorForAxis(row.axis);
      const reason = faderBlockReason(motor);
      slider.disabled = Boolean(reason);
      slider.title = reason || '';
      const motorDeg = Number(motor?.position_deg ?? motor?.position);
      const active = activeAxes.get(row.axis);
      const jointDeg = active
        ? active.jointDeg
        : (Number.isFinite(motorDeg) ? motorToJoint(row, motorDeg) : null);
      if (jointDeg === null || !Number.isFinite(jointDeg)) return;
      if (!active) slider.value = String(clamp(jointDeg, row.lower, row.upper));
      if (jointOut) jointOut.textContent = jointDeg.toFixed(2);
      if (motorOut) {
        motorOut.textContent = (active
          ? jointToMotor(row, jointDeg)
          : (Number.isFinite(motorDeg) ? motorDeg : NaN)
        ).toFixed(1);
      }
    });
  }

  // ------------------------------------------------------------------ //
  // 입력 · input = 잡는 중 · change = 놓음
  // ------------------------------------------------------------------ //

  async function onSliderInput(axis, value) {
    const row = mapping?.rows?.find((entry) => entry.axis === axis);
    if (!row) return;
    const jointDeg = clamp(Number(value), row.lower, row.upper);
    if (!Number.isFinite(jointDeg)) return;
    activeAxes.set(axis, { row, jointDeg });
    if (!(await ensureSocket())) return;
    startSending();
  }

  function onSliderRelease(axis) {
    if (!activeAxes.has(axis)) return;
    activeAxes.delete(axis);
    sendNow({ type: 'release', axes: [axis] });
    if (!activeAxes.size) stopSending();
  }

  function bindEvents() {
    const list = el.manualFaderList;
    if (!list) return;
    list.addEventListener('input', (event) => {
      const axis = faderAxisOf(event.target);
      if (axis !== null) onSliderInput(axis, event.target.value);
    });
    list.addEventListener('change', (event) => {
      const axis = faderAxisOf(event.target);
      if (axis !== null) onSliderRelease(axis);
    });
    window.addEventListener('beforeunload', () => disconnect());
  }

  function faderAxisOf(target) {
    const raw = target?.dataset?.faderSlider;
    if (raw === undefined) return null;
    const axis = Number(raw);
    return Number.isInteger(axis) && axis >= 0 ? axis : null;
  }

  return {
    bindEvents,
    renderRuntimeState,
    refresh,
    onProjectChange: () => {
      mapping = null;
      renderedSignature = '';
      disconnect();
      if (el.manualFaderList) el.manualFaderList.innerHTML = '';
      setMessage('모션축 설정 확인 중');
    },
  };
}

function numberOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, lower, upper) {
  return Math.min(upper, Math.max(lower, value));
}
