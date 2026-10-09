/** UI v2 · 화면이 보여 줄 것을 서버 상태에서 뽑는다 · DOM 을 모른다 (시험은 이것만 본다)
 *
 * 원칙 1 · 상태는 한 문장으로 · 원칙 2 · 문제마다 해결 버튼 (설계안 2026-10-09)
 * 입력 · `snap` = `/ws/status` 한 장 · `sched` = `GET /api/schedule/status` · `connected` = 소켓 살아 있나
 */

export const RUN_MODE_LABEL = { schedule: '자동', manual: '수동', off: '끔' };

const RUNNING_STATES = new Set(['running', 'verifying', 'waiting']);
const MOVING_STATES = new Set(['running', 'verifying', 'waiting', 'initializing', 'recovering']);

export function runMode(sched) {
  const mode = String(sched?.run_mode || '');
  return mode in RUN_MODE_LABEL ? mode : '';
}

/** 운전 모드 + 운영 시간 · 한 마디 */
export function modePhrase(sched) {
  const mode = runMode(sched);
  if (mode === 'manual') return '수동';
  if (mode === 'off') return '끔 · 명령 막힘';
  if (mode === 'schedule') return sched?.active_schedule_id ? '자동 운영 중' : '운영 시간 외';
  return '상태 확인 중';
}

export function networkPcs(snap) {
  const list = snap?.coordination?.runtime?.network_pcs;
  return Array.isArray(list) ? list : [];
}

export function pcName(pc) {
  return String(pc?.display_name || pc?.pc_id || '-');
}

/** 확인할 일 · 나쁜 것(bad)이 먼저 · action.kind 는 화면이 버튼으로 바꾼다 */
export function collectIssues(snap, sched, { connected = true } = {}) {
  const issues = [];
  const bad = (title, detail = '', action = null) => issues.push({ tone: 'bad', title, detail, action });
  const warn = (title, detail = '', action = null) => issues.push({ tone: 'warn', title, detail, action });
  if (!connected) {
    bad('이 PC 서버와 연결이 끊겼습니다', '프로그램이 다시 뜨는 중일 수 있습니다 · 저절로 다시 붙습니다');
    return issues;
  }
  if (!snap) return issues;
  const safety = snap.safety_status || {};
  if (safety.emergency_latched) {
    bad('긴급 정지로 잠겨 있습니다', '모터 명령이 모두 막혔습니다 · 프로그램을 다시 시작해야 풀립니다',
      { kind: 'restart-program', label: '프로그램 다시 시작' });
  }
  const watchdog = String(snap.supervisor_watchdog?.message || '');
  if (watchdog) bad('모터 제어가 응답하지 않습니다', watchdog);
  const absolute = String(snap.minas_absolute_blocker || '');
  if (absolute) {
    bad('앱솔루트 미확인 · 모터를 움직일 수 없습니다', absolute,
      { kind: 'open', target: 'maintain-motors', label: '정비에서 설정' });
  }
  const motors = Array.isArray(snap.motion_state?.motors) ? snap.motion_state.motors : [];
  const faulted = motors.filter((m) => m && m.fault);
  if (faulted.length) {
    const names = faulted.map((m) => `${m.controller_index}번${m.error_code ? ` (${m.error_code})` : ''}`).join(' · ');
    bad(`모터 알람 · ${names}`, '걸린 것이 없는지 보고 오류 초기화',
      { kind: 'fault-reset', label: '오류 초기화' });
  }
  const run = snap.motion_run_status || {};
  if (String(run.state || '') === 'error') {
    bad('재생이 오류로 멈췄습니다', String(run.message || ''));
  }
  const group = snap.coordination?.runtime?.coordination_error || {};
  if (group.active) {
    bad('그룹 오류', String(group.message || ''), { kind: 'ack-group-error', label: '확인하고 풀기' });
  }
  const failure = sched?.last_failure || {};
  const failCount = Number(failure.count) || 0;
  if (failCount > 0) {
    const entry = [`스케줄 시작 거부 ${failCount}회`, String(failure.message || '이유를 알려 주지 않았습니다')];
    if (failCount >= 3) bad(...entry); else warn(...entry);
  }
  const unreadable = Array.isArray(sched?.unreadable_schedules) ? sched.unreadable_schedules.filter(Boolean) : [];
  if (unreadable.length) {
    warn(`시각을 읽을 수 없는 스케줄 ${unreadable.length}`, unreadable.join(' · '), { kind: 'open', target: 'schedule', label: '스케줄 고치기' });
  }
  const pcs = networkPcs(snap);
  const differing = pcs.filter((pc) => !pc.is_local && pc.role !== 'speaker' && (pc.version_differs || pc.protocol_mismatch));
  if (differing.length) {
    warn(`${differing.map(pcName).join(' · ')} 버전이 다릅니다`, '다음 그룹 시작에서 빠집니다',
      { kind: 'update-all', label: '모든 PC 업데이트' });
  }
  const offline = pcs.filter((pc) => !pc.is_local && pc.online === false);
  if (offline.length) {
    warn(`${offline.map(pcName).join(' · ')} 연결 안 됨`, 'PC 가 꺼졌거나 Wi-Fi 가 끊겼습니다');
  }
  return issues.sort((a, b) => (a.tone === b.tone ? 0 : a.tone === 'bad' ? -1 : 1));
}

/** 상단 가운데 한 문장 · tone = ok | warn | bad | info */
export function headline(snap, sched, options = {}) {
  const issues = collectIssues(snap, sched, options);
  const mode = modePhrase(sched);
  const first = issues[0];
  if (first && first.tone === 'bad') return { tone: 'bad', text: first.title, issues };
  if (issues.length) return { tone: 'warn', text: `${mode} · 확인할 일 ${issues.length}개`, issues };
  if (runMode(sched) === 'manual') return { tone: 'info', text: '수동 · 스케줄이 손대지 않음', issues };
  return { tone: 'ok', text: `정상 · ${mode}`, issues };
}

export function formatClock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function stripJson(name) {
  return String(name || '').replace(/\.json$/i, '');
}

/** 홈 「지금」 카드 */
export function runSummary(snap) {
  const run = snap?.motion_run_status || {};
  const state = String(run.state || '');
  const file = stripJson(run.motion_file_id);
  const group = Boolean(run.group_execution);
  const participants = snap?.coordination?.runtime?.execution?.participants;
  const count = Array.isArray(participants) ? participants.length : 0;
  const scope = group ? (count ? `매장 전체 ${count}대` : '매장 전체') : '이 PC';
  const cycle = Number(run.current_cycle) || 0;
  const progress = run.progress || {};
  const elapsed = Number(progress.elapsed_sec) || 0;
  const duration = Number(progress.duration_sec) || 0;
  const ratio = duration > 0 ? Math.min(1, Math.max(0, elapsed / duration)) : 0;
  const continuous = String(run.run_mode || '') === 'continuous';
  let title = '서 있음';
  if (RUNNING_STATES.has(state)) title = `${file || '애니메이션'} 재생 중`;
  else if (state === 'initializing') title = '첫 자세로 천천히 가는 중';
  else if (state === 'recovering') title = '자동 복구 중';
  else if (state === 'initialized') title = '첫 자세에 서 있음';
  else if (state === 'error') title = '오류로 멈춤';
  const parts = [scope];
  if (cycle > 0 && MOVING_STATES.has(state)) parts.push(`${cycle}회차`);
  if (continuous && MOVING_STATES.has(state)) parts.push('연속');
  return {
    state,
    moving: MOVING_STATES.has(state),
    title,
    subtitle: parts.join(' · '),
    group,
    ratio,
    timeText: duration > 0 && MOVING_STATES.has(state) ? `${formatClock(elapsed)} / ${formatClock(duration)}` : '',
  };
}

/** 이 PC 모터 · 조인트 값이 있으면 조인트 deg, 없으면 모터 deg */
export function motorChips(snap) {
  const motors = Array.isArray(snap?.motion_state?.motors) ? snap.motion_state.motors : [];
  return motors.map((m) => {
    const joint = Number(m.motion_actual_rad);
    const motor = Number(m.position_rad);
    const deg = Number.isFinite(joint) ? (joint * 180) / Math.PI : (Number.isFinite(motor) ? (motor * 180) / Math.PI : null);
    const load = Number(m.overload_percent ?? m.torque_percent);
    let tone = 'ok';
    let note = '';
    if (m.fault) { tone = 'bad'; note = `알람${m.error_code ? ` ${m.error_code}` : ''}`; }
    else if (!m.servo_on) { tone = 'warn'; note = '서보 꺼짐'; }
    return {
      name: String(m.name || m.display_name || `${m.controller_index}번 모터`),
      index: m.controller_index,
      tone,
      value: deg === null ? '-' : `${deg >= 0 ? '+' : '−'}${Math.abs(deg).toFixed(2)}°`,
      unit: Number.isFinite(joint) ? '조인트' : '모터',
      note: note || (Number.isFinite(load) ? `부하 ${Math.round(load)}%` : ''),
    };
  });
}

/** 매장 PC 줄 · 이 PC 가 맨 위 */
export function pcRows(snap) {
  return networkPcs(snap).map((pc) => {
    let tone = 'ok';
    let note = pc.role === 'speaker' ? '스피커' : (pc.is_master ? '마스터' : '슬레이브');
    if (pc.online === false) { tone = 'bad'; note = '연결 안 됨'; }
    else if (pc.version_differs || pc.protocol_mismatch) { tone = 'warn'; note = '버전 다름'; }
    else if (pc.role !== 'speaker' && pc.joined === false) { tone = 'info'; note = '그룹 참여 꺼짐'; }
    return { name: pcName(pc), local: Boolean(pc.is_local), tone, note, url: String(pc.web_url || '') };
  });
}

const DAY_CODES = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];

function toMinutes(text) {
  const match = /^(\d{1,2}):(\d{2})/.exec(String(text || ''));
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

/** 오늘 도는 구간 · [{name, start, end(분)}] · 자정 넘김은 오늘 몫만 */
export function todayWindows(items, now = new Date()) {
  const day = DAY_CODES[now.getDay()];
  const ymd = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const out = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item || item.enabled === false) continue;
    const type = String(item.repeat_type || 'daily');
    if (type === 'weekly' && !(item.repeat_days || []).includes(day)) continue;
    if (type === 'once' && item.run_date !== ymd) continue;
    const start = toMinutes(item.start_time);
    let end = toMinutes(item.stop_time);
    if (start === null) continue;
    if (end === null && Number(item.duration_sec) > 0) end = start + Math.round(Number(item.duration_sec) / 60);
    if (end === null) continue;
    out.push({ name: String(item.schedule_name || '스케줄'), start, end: end > start ? end : 24 * 60,
      text: `${String(item.start_time).slice(0, 5)} – ${String(item.stop_time || '').slice(0, 5)}` });
  }
  return out.sort((a, b) => a.start - b.start);
}
