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

/* ---------- 스케줄 ---------- */

export function saveSchedule(payload) {
  return attempt(() => api('POST', '/api/schedule/save', { body: payload }), '스케줄을 저장했습니다');
}

export function setScheduleEnabled(id, enabled) {
  return attempt(() => api('POST', `/api/schedule/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`),
    enabled ? '켰습니다' : '껐습니다 · 지우지는 않았습니다');
}

export async function deleteSchedule(id, name) {
  const ok = await confirmBox({ title: `「${name}」 을 지울까요?`, body: '되돌릴 수 없습니다. 잠깐 쉬게 하려면 지우지 말고 끄세요.', confirmLabel: '지우기', tone: 'danger' });
  if (!ok) return null;
  return attempt(() => api('DELETE', `/api/schedule/${encodeURIComponent(id)}`), '지웠습니다');
}

/** 운영 시간이 끝나면 · park_servo_off(기준점 → 서보 끔) | hold(그 자세로 버팀) */
export function saveEndAction(action) {
  return attempt(() => api('PUT', '/api/motion-run/automation', { body: { schedule_end_action: action } }),
    action === 'hold' ? '운영 시간이 끝나면 회차 끝난 자세로 버팁니다(서보 켠 채)' : '운영 시간이 끝나면 기준점으로 가서 서보를 끕니다');
}

/* ---------- 매장 PC ---------- */

/** 그룹 참여 켜기 · 설정이 꺼져 있으면 설정까지 켠다(연동 서비스 한 번 다시 시작) · 수정 목록 83 */
export function joinGroup(config) {
  if (config?.enabled === true) {
    return attempt(() => api('POST', '/api/coordination/control', { body: { command: 'join' }, timeoutMs: 7000 }),
      '그룹 참여 · 같은 그룹 PC 들과 같이 재생합니다');
  }
  if (!String(config?.group_id || '').trim()) {
    toast('그룹 ID 가 없습니다 · 네트워크·시간 화면에서 그룹 ID 를 넣은 뒤 켜세요', 'warn');
    return Promise.resolve(null);
  }
  return attempt(() => api('PUT', '/api/coordination/settings', { body: { enabled: true, joined: true, group_id: config.group_id }, timeoutMs: 20000 }),
    '그룹 참여 · 같은 그룹 PC 들과 같이 재생합니다');
}

export async function leaveGroup() {
  const ok = await confirmBox({
    title: '그룹 참여 끄기',
    body: '이 PC 혼자 재생합니다(스케줄도 이 PC 혼자 돕니다).\n프로그램을 다시 켜도 꺼진 채로 있습니다 · 다시 같이 돌리려면 「그룹 참여」 를 켜세요.',
    confirmLabel: '끄기', tone: 'warning',
  });
  if (!ok) return null;
  return attempt(() => api('POST', '/api/coordination/control', { body: { command: 'leave' }, timeoutMs: 7000 }), '그룹에서 빠졌습니다 · 이 PC 혼자');
}

/** 필수 명단 · 그룹 시작 때 빠지면 「미접속」 으로 적고 나머지로 시작 */
export async function saveRoster(list) {
  const ok = await confirmBox({
    title: '필수 명단 다시 정하기',
    body: `지금 보이는 ${list.length}대로 정합니다.\n${list.join(' · ')}\n\n그룹 시작 때 이 중 빠진 PC 는 「미접속」 으로 적고 나머지로 시작합니다. 연동 서비스가 한 번 다시 시작합니다.`,
    confirmLabel: '정하기',
  });
  if (!ok) return null;
  return attempt(() => api('PUT', '/api/coordination/settings', { body: { required_peers: list }, timeoutMs: 20000 }), '필수 명단을 저장했습니다');
}
