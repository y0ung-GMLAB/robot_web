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

/* ---------- 애니메이션 ---------- */

/** 하나 올리기 · 서버가 형식을 검사하고 거절하면 그 이유 · 큰 파일은 오래 걸린다 */
export function uploadAnimation(projectId, fileName, content) {
  return api('POST', `/api/projects/${encodeURIComponent(projectId)}/files`, {
    body: { category: 'motions', file_name: fileName, content }, timeoutMs: 240000,
  });
}

export function precompute(fileId) {
  return attempt(() => api('POST', `/api/motion-files/${encodeURIComponent(fileId)}/preview-precompute`),
    (r) => r?.message || '3D 계산을 시작했습니다');
}

/** 재생 목록에 든 것은 서버가 거절한다 · 화면은 먼저 버튼을 끈다 */
export async function deleteAnimation(fileId) {
  const ok = await confirmBox({
    title: `「${fileId}」 를 지울까요?`,
    body: '이 PC 에서 지웁니다. 되돌릴 수 없습니다.',
    confirmLabel: '지우기', tone: 'danger',
  });
  if (!ok) return null;
  return attempt(() => api('DELETE', `/api/motion-files/${encodeURIComponent(fileId)}`), '지웠습니다');
}

/* ---------- 알람 정책 ---------- */

export function saveAlarmPolicy(overrides) {
  return attempt(() => api('PUT', '/api/servo-alarm-policy', { body: { overrides } }),
    (r) => r?.message || '알람 정책을 저장했습니다 · Supervisor 에 적용됨');
}

/* ---------- 장비에 적용 · 모터 재시작 (모터·드라이브 · 조인트 매핑 같이 씀) ---------- */

/** 확인만 · 기존 화면 문구 그대로(motor_config.js · 위험을 다 적는다) · reason 은 맨 앞 한 줄 */
export function confirmApplyMotorConfig(reason = '') {
  return confirmBox({
    title: '장비에 적용 · 모터 재시작',
    body: `${reason ? `${reason}\n\n` : ''}주의 · 저장된 설정을 적용하려고 Motor Manager 를 다시 시작합니다.\n`
      + '다시 시작하는 동안 AC 서보 · 다이나믹셀 통신이 잠시 끊기거나 다시 초기화될 수 있습니다.\n'
      + '지금 부하를 잡고 있는 모터는 순간적으로 토크가 풀려 부하가 풀릴 수 있습니다 · 중력 · 외력 · 기구 하중 때문에 뜻하지 않은 움직임이 생길 수 있습니다.\n'
      + '기구를 안전하게 받치고, 사람이 다가가지 못하게 하고, 움직여도 위험하지 않을 때만 하세요.\n'
      + '웹 연결은 잠깐 끊긴 뒤 저절로 다시 붙습니다.',
    confirmLabel: '적용 · 재시작', tone: 'danger',
  });
}

/** 저장된 파일을 적용(파일은 안 고침 · §6-221) · 확인은 부르는 쪽에서 */
export function applyMotorConfig() {
  return attempt(() => api('POST', '/api/motor-config/apply', { timeoutMs: 60000 }),
    (r) => r?.message || '적용했습니다 · 모터가 잠깐 멈췄다 켜집니다 · 화면이 다시 붙습니다');
}

/* ---------- 서보 · 한 축 (모터·드라이브 · 수동 조작 같이 씀) ---------- */

/**
 * 서보(AC) · 토크(DXL) 켜기/끄기 · 오류 초기화(AC) / 재부팅(DXL)
 * 운전 모드와 무관(서버 run_mode_gate) · 끄기·재부팅은 확인(수정 목록 24) · 오류 초기화 뒤 서보는 꺼진 채(수정 목록 71)
 */
export async function servoControl(motor, action) {
  const ac = motor.ac !== false;
  const label = `${motor.axis}번${motor.name ? ` · ${motor.name}` : ''}`;
  if (action === 'off') {
    const ok = await confirmBox({
      title: `${label} ${ac ? '서보' : '토크'} 끄기`,
      body: ac ? '서보를 끕니다.\n서보가 꺼지면 부하가 풀릴 수 있습니다(브레이크 없는 축은 처짐).'
        : '토크를 끕니다.\n다이나믹셀은 브레이크가 없어 관절이 처질 수 있습니다.',
      confirmLabel: '끄기', tone: 'warning',
    });
    if (!ok) return null;
  }
  if (action === 'reset' && !ac) {
    const ok = await confirmBox({ title: `${label} 재부팅`, body: '하드웨어 오류가 풀리고 토크가 꺼집니다 · 브레이크가 없어 관절이 처질 수 있습니다.\n다회전 모드 모터는 바퀴 수가 사라져 위치 표시가 바뀔 수 있습니다 · 재부팅 뒤 위치를 확인하세요.', confirmLabel: '재부팅', tone: 'warning' });
    if (!ok) return null;
  }
  const map = ac ? { on: 'servo_on', off: 'servo_off', reset: 'fault_reset' } : { on: 'torque_on', off: 'torque_off', reset: 'reboot' };
  const path = ac ? '/api/motion-test/ac-servo/control' : '/api/motion-test/dynamixel/control';
  const body = ac ? { action: map[action], scope: 'selected', axis: motor.axis } : { action: map[action], axis: motor.axis };
  return attempt(() => api('POST', path, { body, timeoutMs: 5000 }),
    action === 'reset' && ac ? '오류 초기화 · 서보는 꺼진 채 · 원인을 확인한 뒤 「서보 켜기」' : (r) => r?.message || '보냈습니다');
}

/** 움직이던 것 멈춤 · 서보는 켠 채 그 자리 · 늘 된다 */
export function motionStop() {
  return attempt(() => api('POST', '/api/safety/motion-stop'), '멈췄습니다 · 서보는 켠 채 그 자리');
}
