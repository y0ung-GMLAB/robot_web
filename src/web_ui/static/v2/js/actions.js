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
  }, '정지했습니다. 서보 토크 유지.');
}

/** 긴급 정지 · 서보 끔 · 잠김 */
export function emergencyStop() {
  return attempt(async () => {
    await api('POST', '/api/safety/emergency-stop');
    await api('POST', '/api/motion-run/stop').catch(() => null);
  }, '긴급 정지했습니다. 서보가 꺼졌으며 프로그램을 다시 시작해야 해제됩니다.');
}

const MODE_CONFIRM = {
  schedule: { title: '스케줄 모드로 전환할까요?', body: '운영 시간에 맞춰 재생을 시작하고 정지합니다. 지금이 운영 시간이면 곧 재생을 시작합니다.', tone: 'warning' },
  off: { title: '끔 모드로 전환할까요?', body: '모든 움직임 명령을 차단합니다. 진행 중인 재생은 이번 회차가 끝나면 정지합니다. 서보 토크는 유지됩니다.', tone: 'warning' },
};

export async function setRunMode(mode) {
  const ask = MODE_CONFIRM[mode];
  if (ask && !(await confirmBox({ ...ask, confirmLabel: '전환' }))) return null;
  return attempt(() => api('PUT', '/api/schedule/mode', { body: { run_mode: mode } }),
    `${{ schedule: '스케줄', manual: '수동', off: '끔' }[mode]} 모드로 전환했습니다`);
}

export function stopAfterCycle(group) {
  return attempt(
    () => (group
      ? api('POST', '/api/coordination/control', { body: { command: 'stop_after_cycle' } })
      : api('POST', '/api/motion-run/stop-after-cycle')),
    '이번 회차가 끝나면 정지합니다');
}

export async function updateAll() {
  const ok = await confirmBox({
    title: '모든 PC 업데이트',
    body: '같은 네트워크에 있는 모든 PC를 최신 버전으로 업데이트합니다(PC마다 몇 분 걸립니다). 업데이트하는 동안 해당 PC는 재생할 수 없고 화면 연결이 잠시 끊깁니다. 재생 중인 PC는 업데이트하지 않습니다. 운영 시간이 아닐 때 진행하세요.',
    confirmLabel: '업데이트', tone: 'warning',
  });
  if (!ok) return null;
  return attempt(() => api('POST', '/api/system/update-all', { timeoutMs: 60000 }), (r) => r?.message || '업데이트를 시작했습니다');
}

export async function faultReset() {
  return attempt(() => api('POST', '/api/motion-test/ac-servo/control', { body: { action: 'fault_reset', scope: 'all' } }),
    '오류를 초기화했습니다. 원인을 확인한 뒤 서보를 켜세요.');
}

export async function restartProgram() {
  const ok = await confirmBox({
    title: '프로그램 다시 시작',
    body: '로봇 프로그램을 다시 시작합니다. 30초 정도 화면 연결이 끊깁니다. 서보 토크는 유지됩니다.',
    confirmLabel: '다시 시작', tone: 'warning',
  });
  if (!ok) return null;
  return attempt(() => api('POST', '/api/system/program/restart', { timeoutMs: 20000 }), '다시 시작합니다. 잠시 후 자동으로 다시 연결됩니다.');
}

export function ackGroupError() {
  return attempt(() => api('POST', '/api/coordination/control', { body: { command: 'acknowledge_group_error' } }), '그룹 오류를 해제했습니다');
}

/* ---------- 공연 ---------- */

const control = (body) => api('POST', '/api/coordination/control', { body, timeoutMs: 7000 });

/** 이 PC · 시작(1회·연속) · 초기 위치로 */
export function startLocal(payload) {
  return attempt(() => api('POST', '/api/motion-run/start', { body: payload, timeoutMs: 30000 }),
    payload.run_mode === 'once' ? '1회 재생을 시작합니다. 먼저 초기 위치로 천천히 이동합니다.' : '연속 재생을 시작합니다. 먼저 초기 위치로 천천히 이동합니다.');
}

export function initializeLocal(payload) {
  return attempt(() => api('POST', '/api/motion-run/initialize', { body: payload, timeoutMs: 30000 }),
    '초기 위치로 천천히 이동합니다');
}

/** 매장 전체 · 마스터가 그룹에 시작을 건다 · 각 PC 는 자기 재생 목록 */
export function startGroup(settings) {
  return attempt(() => control({ command: 'start_group', ...settings }),
    (r) => r?.message || '그룹 전체 재생을 시작합니다. PC마다 초기 위치로 이동한 뒤 함께 시작합니다.');
}

export function initializeGroup(settings = {}) {
  return attempt(() => control({ command: 'initialize_group', ...settings }), (r) => r?.message || '그룹 전체를 초기 위치로 이동합니다');
}

/** 지금 멈춤 · 재생만 멈춘다 · 서보는 켠 채 그 자리 */
export function stopNow(group) {
  return attempt(() => (group ? control({ command: 'stop_now' }) : api('POST', '/api/motion-run/stop')),
    group ? '그룹 전체를 정지했습니다. 서보 토크 유지.' : '정지했습니다. 서보 토크 유지.');
}

export function stopGroupAfterCycle(command) {
  return attempt(() => control({ command }),
    command === 'stop_now' ? '아직 시작 전이어서 바로 정지했습니다' : '이번 회차가 끝나면 그룹 전체가 정지합니다');
}

/** 반복 설정 · 서버에 남는다(스케줄이 다음에 돌릴 때도 이것으로) · 보낸 칸만 바뀐다 */
export function saveAutomation(partial) {
  return attempt(() => api('PUT', '/api/motion-run/automation', { body: partial }));
}

/** 실행 축 사용 · 끄면 그 자리에 선다 · 다시 켜면 다음 회차부터 · 매핑 파일에는 안 남는다 */
export function setAxisMuted(motionId, muted) {
  return attempt(() => api('POST', '/api/motion-run/live-override', { body: { motion_id: motionId, muted } }),
    muted ? `${motionId} 조인트를 껐습니다. 현재 위치에서 정지합니다.` : `${motionId} 조인트를 켰습니다. 재생 중이면 다음 회차부터 적용됩니다.`);
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
    enabled ? '켰습니다' : '껐습니다. 스케줄은 삭제되지 않았습니다.');
}

export async function deleteSchedule(id, name) {
  const ok = await confirmBox({ title: `「${name}」 스케줄을 삭제할까요?`, body: '삭제하면 되돌릴 수 없습니다. 잠시 중지하려면 삭제하지 말고 끄세요.', confirmLabel: '삭제', tone: 'danger' });
  if (!ok) return null;
  return attempt(() => api('DELETE', `/api/schedule/${encodeURIComponent(id)}`), '삭제했습니다');
}

/** 운영 시간이 끝나면 · park_servo_off(기준점 → 서보 끔) | hold(그 자세로 버팀) */
export function saveEndAction(action) {
  return attempt(() => api('PUT', '/api/motion-run/automation', { body: { schedule_end_action: action } }),
    action === 'hold' ? '운영 시간이 끝나면 회차가 끝난 자세에서 정지합니다. 서보 토크 유지.' : '운영 시간이 끝나면 기준점으로 이동한 뒤 서보를 끕니다');
}

/* ---------- 매장 PC ---------- */

/** 그룹 참여 켜기 · 설정이 꺼져 있으면 설정까지 켠다(연동 서비스 한 번 다시 시작) · 수정 목록 83 */
export function joinGroup(config) {
  if (config?.enabled === true) {
    return attempt(() => api('POST', '/api/coordination/control', { body: { command: 'join' }, timeoutMs: 7000 }),
      '그룹에 참여했습니다. 같은 그룹의 PC와 함께 재생합니다.');
  }
  if (!String(config?.group_id || '').trim()) {
    toast('그룹 ID가 없습니다. 「네트워크·시간·그룹」 화면에서 그룹 ID를 입력한 뒤 켜세요.', 'warn');
    return Promise.resolve(null);
  }
  return attempt(() => api('PUT', '/api/coordination/settings', { body: { enabled: true, joined: true, group_id: config.group_id }, timeoutMs: 20000 }),
    '그룹에 참여했습니다. 같은 그룹의 PC와 함께 재생합니다.');
}

export async function leaveGroup() {
  const ok = await confirmBox({
    title: '그룹 참여 끄기',
    body: '다른 PC와 상관없이 단독으로 재생합니다(스케줄도 단독으로 실행됩니다).\n프로그램을 다시 시작해도 꺼진 상태로 유지됩니다. 다시 함께 재생하려면 「그룹 참여」를 켜세요.',
    confirmLabel: '끄기', tone: 'warning',
  });
  if (!ok) return null;
  return attempt(() => api('POST', '/api/coordination/control', { body: { command: 'leave' }, timeoutMs: 7000 }), '그룹에서 나왔습니다. 이제 단독으로 재생합니다.');
}

/** 필수 명단 · 그룹 시작 때 빠지면 「미접속」 으로 적고 나머지로 시작 */
export async function saveRoster(list) {
  const ok = await confirmBox({
    title: '필수 명단 다시 지정',
    body: `현재 연결된 ${list.length}대를 필수 명단으로 지정합니다.\n${list.join(' · ')}\n\n그룹을 시작할 때 이 중 빠진 PC는 「미접속」으로 기록하고 나머지 PC로 시작합니다. 연동 서비스가 한 번 다시 시작됩니다.`,
    confirmLabel: '지정',
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
    title: `「${fileId}」 애니메이션을 삭제할까요?`,
    body: '삭제하면 되돌릴 수 없습니다.',
    confirmLabel: '삭제', tone: 'danger',
  });
  if (!ok) return null;
  return attempt(() => api('DELETE', `/api/motion-files/${encodeURIComponent(fileId)}`), '삭제했습니다');
}

/* ---------- 알람 정책 ---------- */

export function saveAlarmPolicy(overrides) {
  return attempt(() => api('PUT', '/api/servo-alarm-policy', { body: { overrides } }),
    (r) => r?.message || '드라이브 알람 등급을 저장하고 모터 프로그램에 적용했습니다');
}

/* ---------- 장비에 적용 · 모터 재시작 (모터·드라이브 · 조인트 매핑 같이 씀) ---------- */

/** 확인만 · 기존 화면 문구 그대로(motor_config.js · 위험을 다 적는다) · reason 은 맨 앞 한 줄 */
export function confirmApplyMotorConfig(reason = '') {
  return confirmBox({
    title: '장비에 적용 및 모터 재시작',
    body: `${reason ? `${reason}\n\n` : ''}주의: 저장된 설정을 적용하기 위해 모터 프로그램을 다시 시작합니다.\n`
      + '다시 시작하는 동안 AC 서보와 다이나믹셀 통신이 잠시 끊기거나 다시 초기화될 수 있습니다.\n'
      + '브레이크 보드가 연결된 모터는 토크가 해제되는 동안 브레이크가 잡아 줍니다. 브레이크가 없는 모터는 순간적으로 토크가 해제되어 부하를 놓칠 수 있습니다. 중력, 외력, 기구 하중 때문에 예상하지 못한 움직임이 생길 수 있습니다.\n'
      + '브레이크가 없는 모터가 부하를 지탱하고 있다면 기구를 안전하게 받치고 사람이 접근하지 못하게 한 뒤, 움직여도 위험하지 않을 때만 진행하세요.\n'
      + '웹 연결은 잠시 끊겼다가 자동으로 다시 연결됩니다.',
    confirmLabel: '적용 및 재시작', tone: 'danger',
  });
}

/** 저장된 파일을 적용(파일은 안 고침 · §6-221) · 확인은 부르는 쪽에서 */
export function applyMotorConfig() {
  return attempt(() => api('POST', '/api/motor-config/apply', { timeoutMs: 60000 }),
    (r) => r?.message || '적용했습니다. 모터 프로그램이 다시 시작되고 화면이 다시 연결됩니다.');
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
      body: ac ? '서보를 끕니다.\n브레이크 보드가 연결된 모터는 브레이크가 잡아 주지만, 브레이크가 없는 모터는 부하를 지탱하지 못해 처질 수 있습니다.'
        : '토크를 끕니다.\n다이나믹셀은 브레이크가 없어 관절이 처질 수 있습니다.',
      confirmLabel: '끄기', tone: 'warning',
    });
    if (!ok) return null;
  }
  if (action === 'reset' && !ac) {
    const ok = await confirmBox({ title: `${label} 재부팅`, body: '하드웨어 오류가 해제되고 토크가 꺼집니다. 브레이크가 없어 관절이 처질 수 있습니다.\n다회전 모드 모터는 회전 수 정보가 사라져 위치 표시가 바뀔 수 있습니다. 재부팅한 뒤 위치를 확인하세요.', confirmLabel: '재부팅', tone: 'warning' });
    if (!ok) return null;
  }
  const map = ac ? { on: 'servo_on', off: 'servo_off', reset: 'fault_reset' } : { on: 'torque_on', off: 'torque_off', reset: 'reboot' };
  const path = ac ? '/api/motion-test/ac-servo/control' : '/api/motion-test/dynamixel/control';
  const body = ac ? { action: map[action], scope: 'selected', axis: motor.axis } : { action: map[action], axis: motor.axis };
  return attempt(() => api('POST', path, { body, timeoutMs: 5000 }),
    action === 'reset' && ac ? '오류를 초기화했습니다. 서보는 꺼진 상태입니다. 원인을 확인한 뒤 「서보 켜기」를 누르세요.' : (r) => r?.message || '명령을 보냈습니다');
}

/**
 * 서보 · 모두 켜기/끄기 (사용자 2026-10-12 · 모터 설정 화면)
 * AC 는 서버 scope 'all'(감지된 AC 축 전부) 한 번 · 다이나믹셀은 감지된 축마다 · 끄기는 확인 창
 */
export async function servoAll(motors, action) {
  const detected = (motors || []).filter((m) => m.detected);
  const ac = detected.filter((m) => m.ac !== false);
  const dxl = detected.filter((m) => m.ac === false);
  if (!detected.length) { toast('감지된 모터가 없습니다. 「전체 검색」을 먼저 하세요.', 'warn'); return null; }
  if (action === 'off') {
    const ok = await confirmBox({
      title: `모든 서보 끄기 · ${detected.length}대`,
      body: '감지된 모든 모터의 서보(토크)를 끕니다.\n브레이크 보드가 연결된 모터는 브레이크가 잡아 주지만, 브레이크가 없는 모터는 부하를 지탱하지 못해 처질 수 있습니다. 기구를 받치고 주변에 사람이 없는지 확인하세요.',
      confirmLabel: '모두 끄기', tone: 'warning',
    });
    if (!ok) return null;
  }
  const failed = [];
  if (ac.length) {
    try {
      const r = await api('POST', '/api/motion-test/ac-servo/control', { body: { action: action === 'on' ? 'servo_on' : 'servo_off', scope: 'all' }, timeoutMs: 5000 });
      if (r && r.success === false) failed.push(`AC 서보 · ${r.message === 'detected AC Servo axis not found' ? '감지된 AC 서보가 없습니다' : r.message || '실패'}`);
    } catch (error) { failed.push(`AC 서보 · ${error.message || error}`); }
  }
  for (const m of dxl) {
    try {
      const r = await api('POST', '/api/motion-test/dynamixel/control', { body: { action: action === 'on' ? 'torque_on' : 'torque_off', axis: m.axis }, timeoutMs: 5000 });
      if (r && r.success === false) failed.push(`${m.axis}번 · ${r.message || '실패'}`);
    } catch (error) { failed.push(`${m.axis}번 · ${error.message || error}`); }
  }
  const verb = action === 'on' ? '켰습니다' : '껐습니다';
  if (failed.length) toast(`일부 모터가 안 됐습니다 · ${failed.join(' · ')}`, 'bad');
  else toast(`모든 서보를 ${verb} (${detected.length}대).`, 'ok');
  return failed.length === 0;
}

/** 움직이던 것 멈춤 · 서보는 켠 채 그 자리 · 늘 된다 */
export function motionStop() {
  return attempt(() => api('POST', '/api/safety/motion-stop'), '정지했습니다. 서보 토크 유지.');
}
