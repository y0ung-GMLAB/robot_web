/** UI v2 · 버튼이 하는 일 · 위험한 것은 확인 창 (정지 두 개는 확인 없음 · 지금 UI 결정 그대로) */
import { api } from './net.js';
import { confirmBox, toast } from './dialog.js';

async function attempt(work, done) {
  try {
    const result = await work();
    if (done) toast(typeof done === 'function' ? done(result) : done, 'ok');
    return result;
  } catch (error) {
    toast(error.message || String(error), 'bad');
    return null;
  }
}

/** 정지 · 서보는 켠 채 그 자리 */
export function stopAll() {
  return attempt(async () => {
    await api('POST', '/api/safety/motion-stop');
    await api('POST', '/api/motion-run/stop').catch(() => null);
  }, '멈췄습니다 · 서보는 켠 채 그 자리');
}

/** 긴급 정지 · 서보 끔 · 잠김 */
export function emergencyStop() {
  return attempt(async () => {
    await api('POST', '/api/safety/emergency-stop');
    await api('POST', '/api/motion-run/stop').catch(() => null);
  }, '긴급 정지 · 서보 꺼짐 · 프로그램을 다시 시작해야 풀립니다');
}

const MODE_CONFIRM = {
  schedule: { title: '자동으로 바꿀까요?', body: '스케줄이 운영 시간에 맞춰 재생을 시작하고 멈춥니다. 운영 시간 안이면 곧 움직이기 시작합니다.', tone: 'warning' },
  off: { title: '끔으로 바꿀까요?', body: '모든 움직임 명령이 막힙니다. 돌던 재생은 이번 회차가 끝나면 멈춥니다. 서보는 켠 채 그 자리를 지킵니다.', tone: 'warning' },
};

export async function setRunMode(mode) {
  const ask = MODE_CONFIRM[mode];
  if (ask && !(await confirmBox({ ...ask, confirmLabel: '바꾸기' }))) return null;
  return attempt(() => api('PUT', '/api/schedule/mode', { body: { run_mode: mode } }),
    `${{ schedule: '자동', manual: '수동', off: '끔' }[mode]} 으로 바꿨습니다`);
}

export function stopAfterCycle(group) {
  return attempt(
    () => (group
      ? api('POST', '/api/coordination/control', { body: { command: 'stop_after_cycle' } })
      : api('POST', '/api/motion-run/stop-after-cycle')),
    '이번 회차가 끝나면 멈춥니다');
}

export async function updateAll() {
  const ok = await confirmBox({
    title: '모든 PC 업데이트',
    body: '같은 망의 PC 전부를 최신 코드로 바꿉니다(PC 마다 몇 분). 그동안 그 PC 는 재생이 멈추고 화면이 잠깐 끊깁니다. 재생 중인 PC 는 거절합니다. 운영 시간 밖에 하세요.',
    confirmLabel: '업데이트', tone: 'warning',
  });
  if (!ok) return null;
  return attempt(() => api('POST', '/api/system/update-all', { timeoutMs: 60000 }), (r) => r?.message || '업데이트를 시작했습니다');
}

export async function faultReset() {
  return attempt(() => api('POST', '/api/motion-test/ac-servo/control', { body: { action: 'fault_reset', scope: 'all' } }),
    '오류 초기화 · 원인을 확인한 뒤 서보를 켜세요');
}

export async function restartProgram() {
  const ok = await confirmBox({
    title: '프로그램 다시 시작',
    body: '이 PC 의 로봇 프로그램을 다시 띄웁니다. 30초쯤 화면이 끊깁니다. 모터는 서보를 켠 채 그 자리를 지킵니다.',
    confirmLabel: '다시 시작', tone: 'warning',
  });
  if (!ok) return null;
  return attempt(() => api('POST', '/api/system/program/restart', { timeoutMs: 20000 }), '다시 시작합니다 · 저절로 다시 붙습니다');
}

export function ackGroupError() {
  return attempt(() => api('POST', '/api/coordination/control', { body: { command: 'acknowledge_group_error' } }), '그룹 오류를 풀었습니다');
}

/* ---------- 공연 ---------- */

const control = (body) => api('POST', '/api/coordination/control', { body, timeoutMs: 7000 });

/** 이 PC · 시작(1회·연속) · 초기 위치로 */
export function startLocal(payload) {
  return attempt(() => api('POST', '/api/motion-run/start', { body: payload, timeoutMs: 30000 }),
    payload.run_mode === 'once' ? '1회 시작 · 먼저 첫 자세로 천천히 갑니다' : '연속 시작 · 먼저 첫 자세로 천천히 갑니다');
}

export function initializeLocal(payload) {
  return attempt(() => api('POST', '/api/motion-run/initialize', { body: payload, timeoutMs: 30000 }),
    '첫 자세로 천천히 갑니다');
}

/** 매장 전체 · 마스터가 그룹에 시작을 건다 · 각 PC 는 자기 재생 목록 */
export function startGroup(settings) {
  return attempt(() => control({ command: 'start_group', ...settings }),
    (r) => r?.message || '매장 전체 시작 · PC 마다 첫 자세로 간 뒤 같이 시작합니다');
}

export function initializeGroup() {
  return attempt(() => control({ command: 'initialize_group' }), (r) => r?.message || '매장 전체 · 첫 자세로 갑니다');
}

/** 지금 멈춤 · 재생만 멈춘다 · 서보는 켠 채 그 자리 */
export function stopNow(group) {
  return attempt(() => (group ? control({ command: 'stop_now' }) : api('POST', '/api/motion-run/stop')),
    group ? '매장 전체를 멈췄습니다' : '멈췄습니다');
}

export function stopGroupAfterCycle(command) {
  return attempt(() => control({ command }),
    command === 'stop_now' ? '아직 출발 전이라 바로 멈췄습니다' : '이번 회차가 끝나면 매장 전체가 멈춥니다');
}

/** 반복 설정 · 서버에 남는다(스케줄이 다음에 돌릴 때도 이것으로) · 보낸 칸만 바뀐다 */
export function saveAutomation(partial) {
  return attempt(() => api('PUT', '/api/motion-run/automation', { body: partial }));
}

/** 실행 축 사용 · 끄면 그 자리에 선다 · 다시 켜면 다음 회차부터 · 매핑 파일에는 안 남는다 */
export function setAxisMuted(motionId, muted) {
  return attempt(() => api('POST', '/api/motion-run/live-override', { body: { motion_id: motionId, muted } }),
    muted ? `${motionId} 끔 · 그 자리에 섭니다` : `${motionId} 켬 · 돌던 중이면 다음 회차부터`);
}

/** 재생 목록 저장 · 목록 통째로 · 첫 줄이 등록 파일 */
export function savePlaylist(mappingId, list) {
  return attempt(() => api('POST', '/api/motion-mappings/motion-file', {
    body: { file_id: mappingId, motion_file_id: list[0] || '', motion_playlist: list },
  }), '재생 목록을 저장했습니다');
}
