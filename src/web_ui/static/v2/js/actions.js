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
