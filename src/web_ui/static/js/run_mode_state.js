/** 운전 모드 · 화면 공용 상태 · 2026-10-02
 *
 * 주인은 `schedule_manager.js` 다 · 상태를 받을 때마다 여기에 적는다 · 수동
 * 조작 화면(조그·동작·다이얼·페이더)은 여기만 보고 「지금 손으로 움직여도
 * 되나」를 판정한다 · 판정 규칙은 서버(`run_mode_gate.manual_control_block_reason`)
 * 와 같다: **수동 모드에서만 연다** · 서버가 최종 문이고 화면은 미리 알려 줄 뿐이다.
 *
 * 아직 모드를 모르면(첫 응답 전) 막지 않는다 · 모를 때 막으면 아무것도 못 하는
 * 화면이 되고, 막혀야 할 때는 서버가 막는다.
 */

let runMode = '';
const listeners = new Set();

//: 서버 run_mode_gate.SCHEDULE_MANUAL_BLOCK_MESSAGE 와 같은 문장
const SCHEDULE_MANUAL_BLOCK_MESSAGE =
  '스케줄 모드 · 수동 조작은 「수동」 모드에서만 됩니다 (상단에서 모드를 바꾸세요)';
//: 서버 run_mode_gate.OFF_BLOCK_MESSAGE 와 같은 문장
const OFF_MANUAL_BLOCK_MESSAGE =
  '오프 모드 · 명령이 차단되어 있습니다 (상단에서 모드를 바꾸세요)';

export function setRunMode(mode) {
  const next = String(mode || '');
  if (next === runMode) return;
  runMode = next;
  listeners.forEach((listener) => {
    try {
      listener(runMode);
    } catch (error) {
      console.warn('[run_mode_state] listener failed:', error);
    }
  });
}

export function currentRunMode() {
  return runMode;
}

export function onRunModeChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 사람이 모터를 직접 움직이는 명령의 화면 쪽 문 · 막히면 사유 · 열리면 '' */
export function manualControlBlockReason() {
  if (runMode === 'schedule') return SCHEDULE_MANUAL_BLOCK_MESSAGE;
  if (runMode === 'off') return OFF_MANUAL_BLOCK_MESSAGE;
  return '';
}
