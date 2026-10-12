/** UI v2 · 화면이 보여 줄 것을 서버 상태에서 뽑는다 · DOM 을 모른다 (시험은 이것만 본다)
 *
 * 원칙 1 · 상태는 한 문장으로 · 원칙 2 · 문제마다 해결 버튼 (설계안 2026-10-09)
 * 입력 · `snap` = `/ws/status` 한 장 · `sched` = `GET /api/schedule/status` · `connected` = 소켓 살아 있나
 */

export const RUN_MODE_LABEL = { schedule: '스케줄', manual: '수동', off: '끔' };

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
  if (mode === 'off') return '끔 · 명령 차단';
  if (mode === 'schedule') return sched?.active_schedule_id ? '스케줄 운영 중' : '운영 시간 외';
  return '상태 확인 중';
}

/** 모터 오류 글 · 서버 칸은 error_text(영문)·errorcode(숫자) · 없으면 빈 글 */
export function motorErrorText(motor) {
  const text = String(motor?.error_text || '').trim();
  if (text && text !== 'No error') {
    return text === 'Communication unavailable' ? '통신 없음' : text.replace(/^Error\s+/i, '오류 ');
  }
  const code = Number(motor?.errorcode);
  return Number.isFinite(code) && code !== 0 ? `오류 ${code}` : '';
}

/** 과부하율 % · 서버 칸 overload_ratio_pct · 없으면 null */
export function motorLoad(motor) {
  const value = motor?.overload_ratio_pct;
  return value === null || value === undefined || !Number.isFinite(Number(value)) ? null : Number(value);
}

export function networkPcs(snap) {
  const list = snap?.coordination?.runtime?.network_pcs;
  return Array.isArray(list) ? list : [];
}

/** 접속한 PC 이름 · 「이 PC」 대신 · 단독/전체를 나눠 말해야 할 때만 */
export function localName(state) {
  const snap = state?.snap;
  return String(snap?.system_info?.hostname || snap?.coordination?.config?.pc_id || '현재 PC');
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
    bad('서버와 연결이 끊겼습니다', '프로그램이 다시 시작되는 중일 수 있습니다. 잠시 후 자동으로 다시 연결됩니다.');
    return issues;
  }
  if (!snap) return issues;
  const safety = snap.safety_status || {};
  if (safety.emergency_latched) {
    bad('긴급 정지 상태입니다', '모든 모터 명령이 차단되었습니다. 프로그램을 다시 시작해야 해제됩니다.',
      { kind: 'restart-program', label: '프로그램 다시 시작' });
  }
  const watchdog = String(snap.supervisor_watchdog?.message || '');
  if (watchdog) bad('모터 제어가 응답하지 않습니다', watchdog);
  const absolute = String(snap.minas_absolute_blocker || '');
  if (absolute) {
    bad('앱솔루트 방식이 확인되지 않아 모터를 움직일 수 없습니다', absolute,
      { kind: 'open', target: 'maintain-motors', label: '모터 설정 열기' });
  }
  // 조인트 범위 미확인 · 재생·초기 이동·수동 조작이 막혀 있다 · 판정은 서버 · 수정 목록 97
  const range = String(snap.mapping_range_blocker || '');
  if (range) {
    bad('조인트 범위가 확인되지 않아 재생과 수동 조작이 차단되어 있습니다', range,
      { kind: 'open', target: 'mapping', label: '조인트 매핑 열기' });
  }
  const motors = Array.isArray(snap.motion_state?.motors) ? snap.motion_state.motors : [];
  const faulted = motors.filter((m) => m && m.fault);
  if (faulted.length) {
    const names = faulted.map((m) => `${m.controller_index}번${motorErrorText(m) ? ` (${motorErrorText(m)})` : ''}`).join(' · ');
    bad(`모터 알람 · ${names}`, '기구에 걸린 것이 없는지 확인한 뒤 오류를 초기화하세요',
      { kind: 'fault-reset', label: '오류 초기화' });
  }
  const run = snap.motion_run_status || {};
  if (String(run.state || '') === 'error') {
    bad('재생이 오류로 멈췄습니다', String(run.message || ''));
  }
  const group = snap.coordination?.runtime?.coordination_error || {};
  if (group.active) {
    bad('그룹 오류', String(group.message || ''), { kind: 'ack-group-error', label: '그룹 오류 해제' });
  }
  const failure = sched?.last_failure || {};
  const failCount = Number(failure.count) || 0;
  if (failCount > 0) {
    const entry = [`스케줄 시작 거부됨 (${failCount}회)`, String(failure.message || '거부 사유가 전달되지 않았습니다')];
    if (failCount >= 3) bad(...entry); else warn(...entry);
  }
  const unreadable = Array.isArray(sched?.unreadable_schedules) ? sched.unreadable_schedules.filter(Boolean) : [];
  if (unreadable.length) {
    warn(`시각을 읽을 수 없는 스케줄 ${unreadable.length}개`, unreadable.join(' · '), { kind: 'open', target: 'schedule', label: '스케줄 수정' });
  }
  const pcs = networkPcs(snap);
  const differing = pcs.filter((pc) => !pc.is_local && pc.role !== 'speaker' && (pc.version_differs || pc.protocol_mismatch));
  if (differing.length) {
    warn(`${differing.map(pcName).join(' · ')} 버전이 다릅니다`, '다음 그룹 재생에서 제외됩니다',
      { kind: 'update-all', label: '모든 PC 업데이트' });
  }
  const offline = pcs.filter((pc) => !pc.is_local && pc.online === false);
  if (offline.length) {
    warn(`${offline.map(pcName).join(' · ')} 연결 안 됨`, 'PC가 꺼져 있거나 Wi-Fi 연결이 끊겼을 수 있습니다');
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
  if (runMode(sched) === 'manual') return { tone: 'info', text: '수동 · 스케줄 동작 안 함', issues };
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
  const scope = group ? (count ? `그룹 전체 ${count}대` : '그룹 전체') : '단독';
  const cycle = Number(run.current_cycle) || 0;
  const progress = run.progress || {};
  const elapsed = Number(progress.elapsed_sec) || 0;
  const duration = Number(progress.duration_sec) || 0;
  const ratio = duration > 0 ? Math.min(1, Math.max(0, elapsed / duration)) : 0;
  const continuous = String(run.run_mode || '') === 'continuous';
  let title = '대기 상태';
  if (RUNNING_STATES.has(state)) title = `${file || '애니메이션'} 재생 중`;
  else if (state === 'initializing') title = '초기 위치로 천천히 이동 중';
  else if (state === 'recovering') title = '자동 복구 중';
  else if (state === 'initialized') title = '초기 위치에서 대기 중';
  else if (state === 'error') title = '오류로 정지';
  // 대기·오류일 땐 범위가 의미 없다 · 움직이거나 초기 위치에서 기다릴 때만
  const parts = MOVING_STATES.has(state) || state === 'initialized' ? [scope] : [];
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
    // null 은 0 이 아니다 · 매핑 없는 모터는 조인트 값이 비어 온다
    const joint = m.motion_actual_rad === null || m.motion_actual_rad === undefined ? NaN : Number(m.motion_actual_rad);
    const motor = m.position_rad === null || m.position_rad === undefined ? NaN : Number(m.position_rad);
    const deg = Number.isFinite(joint) ? (joint * 180) / Math.PI : (Number.isFinite(motor) ? (motor * 180) / Math.PI : null);
    const load = motorLoad(m);
    let tone = 'ok';
    let note = '';
    if (m.fault) { tone = 'bad'; note = `알람${motorErrorText(m) ? ` ${motorErrorText(m)}` : ''}`; }
    else if (!m.servo_on) { tone = 'warn'; note = '서보 꺼짐'; }
    return {
      name: String(m.motion_id || m.name || m.display_name || `${m.controller_index}번 모터`),
      index: m.controller_index,
      tone,
      value: deg === null ? '-' : `${deg >= 0 ? '+' : '−'}${Math.abs(deg).toFixed(2)}°`,
      unit: Number.isFinite(joint) ? '조인트' : '모터',
      note: note || (Number.isFinite(load) ? `과부하율 ${Math.round(load)}%` : ''),
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
    else if (pc.role !== 'speaker' && pc.joined === false) { tone = 'info'; note = '그룹 미참여'; }
    return { name: pcName(pc), local: Boolean(pc.is_local), tone, note, url: String(pc.web_url || '') };
  });
}

export const DAY_CODES = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];

export function toMinutes(text) {
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
