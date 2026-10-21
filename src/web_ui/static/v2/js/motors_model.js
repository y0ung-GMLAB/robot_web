/** UI v2 · 모터·드라이브 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 모터·드라이브)
 *
 * 설정(registry · 파일)과 지금 상태(motion_state.motors · 런타임)를 번호(axis = controller_index)로 맞춘다.
 * 편집 칸은 기존 화면이 고치던 것만 · 이름 · 속도·가속 · 브레이크 · 과부하 감시 · 운영 끝 서보 끄기.
 */
import { motorErrorText, motorLoad, stuckMailboxes, stuckSlaves } from './model.js';
import { isAcPath, kindSpec, motorKind } from './motor_kinds.js';

/** 편집 칸 · [키, 이름, 단위, AC 전용, 범위] · config 아래(name 만 바깥) */
export const EDIT_FIELDS = [
  { key: 'name', label: '이름', top: true },
  { key: 'max_speed_rpm', label: '최대 속도', unit: 'rpm', ac: true, min: 1, max: 6500 },
  { key: 'profile_velocity', label: '프로파일 속도', unit: 'deg/s', min: 0 },
  { key: 'acceleration', label: '최대 가속', unit: 'deg/s²', min: 0 },
  { key: 'profile_acceleration', label: '프로파일 가속', unit: 'deg/s²', min: 0 },
  // 비우면 「드라이브 공통 설정」(아래 칸 · config/minas_base.yaml) · 이름은 공통 설정과 같은 말 · 사용자 2026-10-13
  { key: 'brake_delay_stop_ms', label: '브레이크 지연 · 멈춰 있을 때', unit: 'ms', ac: true, min: 0, max: 10000, blank: '비우면 공통 설정(기본값 150)' },
  { key: 'brake_delay_run_ms', label: '브레이크 지연 · 움직이는 중', unit: 'ms', ac: true, min: 0, max: 10000, blank: '비우면 공통 설정(기본값 0)' },
];

export function getField(motor, key) {
  const field = EDIT_FIELDS.find((f) => f.key === key);
  return field?.top ? motor?.[key] : motor?.config?.[key];
}

export function setField(motor, key, value) {
  const field = EDIT_FIELDS.find((f) => f.key === key);
  if (field?.top) motor[key] = value;
  else motor.config = { ...(motor.config || {}), [key]: value };
}

/** AC 길 · 직렬 서보(dynamixel · feetech)가 아닌 모든 모터 · 전 `motor_type !== 'dynamixel'` 과 같은 뜻 · 수정 목록 158 */
function isAc(motor) {
  return isAcPath(motorKind(motor));
}

const ABS_TEXT = { ok: ['정상', 'ok'], not_absolute: ['앱솔루트 아님', 'bad'], unknown: ['다시 읽는 중', 'warn'], multiturn_invalid: ['다회전 무효(Err40)', 'bad'] };

/** 표 줄 · 설정 + 지금 상태 */
export function motorRows(registry, snap) {
  const runtime = new Map((snap?.motion_state?.motors || []).map((m) => [Number(m.controller_index), m]));
  const drives = new Map((snap?.motion_state?.minas_absolute?.drives || []).map((d) => [Number(d.axis), d]));
  // PREOP 등에 멈춘 드라이브 · 감시 노드 판정 · 수정 목록 125
  const stuck = new Map(stuckSlaves(snap).filter((s) => s.axis !== null && s.axis !== undefined).map((s) => [Number(s.axis), s]));
  // 메일박스(SDO)만 멈춘 드라이브 · 감시 노드 판정 · 수정 목록 139 ③
  const mailbox = new Set(stuckMailboxes(snap).filter((s) => s.axis !== null && s.axis !== undefined).map((s) => Number(s.axis)));
  const motors = (registry?.motors || []).filter((m) => !m.deleted);
  return motors.map((motor) => {
    const axis = Number(motor.axis ?? motor.config?.controller_index);
    const live = runtime.get(axis) || {};
    const drive = drives.get(axis);
    const kindKey = motorKind(motor);
    const spec = kindSpec(kindKey);
    const ac = isAcPath(kindKey);
    let servo = live.state !== 'detected' ? ['통신 없음', 'bad'] : live.fault ? ['알람', 'bad'] : live.servo_on ? ['켜짐', 'ok'] : ['꺼짐', 'warn'];
    if (spec.serial && live.state === 'detected') servo = live.fault ? ['오류', 'bad'] : live.servo_on ? ['토크 켜짐', 'ok'] : ['토크 꺼짐', 'warn'];
    const position = live.position_rad === null || live.position_rad === undefined ? null : Number(live.position_rad) * 180 / Math.PI;
    const [absText, absTone] = !ac ? ['-', 'idle'] : drive ? (ABS_TEXT[drive.status] || [String(drive.status), 'warn']) : ['-', 'idle'];
    return {
      id: String(motor.id || ''),
      axis,
      name: String(motor.name || ''),
      ac,
      // 종류 · ac_servo | dynamixel | feetech | unknown · 버튼(재부팅 · 토크) 판단은 이것으로 · 158
      kindKey,
      kind: `${spec.short}${motor.profile?.driver_model ? ` · ${motor.profile.driver_model}` : ''}`,
      servo: servo[0],
      servoTone: servo[1],
      fault: live.fault === true,
      error: motorErrorText(live),
      servoOn: live.servo_on === true,
      detected: live.state === 'detected',
      position,
      load: motorLoad(live),
      absolute: absText,
      absoluteTone: absTone,
      absoluteProblem: String(drive?.problem || ''),
      absoluteStatus: ac && drive ? String(drive.status || '') : '',
      // 게인 · 드라이브 EEPROM 값 그대로(우리 부팅 목록에 없음) · 수정 목록 108 (가)
      gains: ac && drive?.gains ? drive.gains : null,
      comm: stuck.has(axis) ? `${stuck.get(axis).state} 에 멈춤 · 드라이브 제어 전원을 껐다 켜세요`
        : mailbox.has(axis) ? '메일박스 응답 없음 · 드라이브 제어 전원을 껐다 켜세요'
        : live.state === 'detected' ? '연결됨' : live.state ? `연결 안 됨 (${live.state})` : '연결 안 됨',
      masterIndex: Number(motor.identity?.ethercat_master_index ?? motor.config?.ethercat_master_index ?? 0),
      slavePosition: Number(motor.config?.position ?? motor.identity?.slave_position),
    };
  }).sort((a, b) => a.axis - b.axis);
}

/** 지령 필터 값 · 0.1 ms 단위 → 「92 (9.2 ms)」 · 못 읽었으면 「?」 · 2026-10-16 */
function filterText(value) {
  return Number.isFinite(value) ? `${value} (${(value * 0.1).toFixed(1)} ms)` : '?';
}

/** 게인 칸 글 · 「자동 · 강성 13 · 관성비 137 %」 · 못 읽었으면 「-」 · 108 */
export function gainText(gains) {
  if (!gains) return { text: '-', tone: 'idle', hint: '아직 못 읽음(드라이브가 자리 잡으면 읽음)' };
  const auto = gains.auto_tuning;
  const parts = [
    `자동조정 ${auto ?? '?'}`,   // 숫자 그대로 · 뜻(0 = 꺼짐 · 1 = 켬)은 마우스를 올리면 · 사용자 2026-10-13
    gains.stiffness === null || gains.stiffness === undefined ? null : `강성 ${gains.stiffness}`,
    gains.inertia_ratio === null || gains.inertia_ratio === undefined ? null : `관성비 ${gains.inertia_ratio} %`,
  ].filter(Boolean);
  const hint = [
    `자동조정(Pr0.02) ${auto ?? '?'}${auto === 0 ? ' = 꺼짐' : auto ? ' = 켬' : ''}`,
    `강성(Pr0.03) ${gains.stiffness ?? '?'}`,
    `관성비(Pr0.04) ${gains.inertia_ratio ?? '?'} %`,
    `추정 속도(Pr6.31) ${gains.estimation_speed ?? '?'}`,
    `지령 스무딩(Pr2.22) ${filterText(gains.command_smoothing)}`,
    `지령 FIR(Pr2.23) ${filterText(gains.command_fir)}`,
    '드라이브에 저장된 값(우리 프로그램은 쓰지 않음)',
    gains.error ? `일부 못 읽음 · ${gains.error}` : '',
  ].filter(Boolean).join('\n');
  return { text: parts.join(' · '), tone: auto === 0 ? 'warn' : 'ok', hint };
}

/** 게인 알림 · 자동조정 꺼진 모터 · 드라이브끼리 강성이 다름 · 막지는 않는다(일부러 끈 것일 수 있음) · 108 (나) */
export function gainWarnings(rows) {
  const ac = rows.filter((r) => r.ac && r.gains);
  const warnings = [];
  const off = ac.filter((r) => r.gains.auto_tuning === 0).map((r) => `${r.axis}번`);
  if (off.length) warnings.push(`자동조정 꺼짐 · ${off.join(' · ')} · 부하에 맞춰 게인이 바뀌지 않습니다(벤치에서 끈 값이 남았을 수 있음)`);
  const stiff = [...new Set(ac.map((r) => r.gains.stiffness).filter((v) => v !== null && v !== undefined))];
  if (stiff.length > 1) warnings.push(`드라이브마다 강성이 다릅니다 · ${ac.map((r) => `${r.axis}번 ${r.gains.stiffness ?? '?'}`).join(' · ')}`);
  // 지령 필터가 축마다 다르면 늦게 따라가는 정도가 달라 축끼리 어긋난다 · 2026-10-16
  for (const [key, label] of [['command_smoothing', '지령 스무딩 필터'], ['command_fir', '지령 FIR 필터']]) {
    const seen = [...new Set(ac.map((r) => r.gains[key]).filter((v) => v !== null && v !== undefined))];
    if (seen.length > 1) warnings.push(`드라이브마다 ${label}가 다릅니다(축끼리 어긋남) · ${ac.map((r) => `${r.axis}번 ${filterText(r.gains[key])}`).join(' · ')}`);
  }
  return warnings;
}

/** 앱솔루트 한 줄 · 「3/3 정상」 */
export function absoluteSummary(rows) {
  const ac = rows.filter((r) => r.ac);
  const ok = ac.filter((r) => r.absolute === '정상').length;
  // 「앱솔루트 설정」 은 값이 틀린 드라이브(Pr0.15 ≠ 0 · Err40)에만 권한다 · 그 버튼은 다회전 클리어까지 가서
  // 기준점을 잃는다 · 읽기만 실패한 것(unknown)은 감시가 몇 초마다 다시 읽는다 (수정 목록 110)
  const needsSetup = ac.filter((r) => r.absoluteStatus === 'not_absolute' || r.absoluteStatus === 'multiturn_invalid').length;
  const waiting = ac.filter((r) => r.absoluteStatus === 'unknown').length;
  // 판정 자체가 없음(모터 프로그램이 이 프로젝트로 안 돎 · 감시가 아직 못 봄) · 인크리멘털일 수도 있다 · 수정 목록 120 (아)
  const unread = ac.filter((r) => !r.absoluteStatus).length;
  return { total: ac.length, ok, allOk: ac.length > 0 && ok === ac.length, needsSetup, waiting, unread };
}

/**
 * 모터 검색 확인 창 · 모터 프로그램이 검색 뒤 다시 켜지는가는 서버 규칙 그대로 · 수정 목록 118
 * 서버(scan_orchestrator) · 지금 도는 모터 프로그램이 선택한 프로젝트 것이면 검색 뒤 다시 켬 ·
 * 다른 프로젝트 것이면 정지만 하고 안 켬(옛 프로젝트 설정으로 되살리지 않게) · 이 프로젝트 설정을 「저장 후 장비에 적용」 해야 켜짐
 */
export function scanConfirmText(kind, scope = {}, { dirty = false } = {}) {
  const what = kind === 'dxl' ? '다이나믹셀' : kind === 'ft' ? 'Feetech' : kind === 'ac' ? 'AC 서보(EtherCAT)' : 'AC 서보 · 다이나믹셀 · Feetech';
  const runtime = String(scope.runtime_project_id || '');
  const restart = scope.runtime_matches_selected === true
    ? '검색하는 동안 모터 프로그램이 잠시 정지했다가 다시 시작됩니다.'
    : runtime
      ? `지금 모터 프로그램은 다른 프로젝트(${runtime}) 설정으로 돌고 있습니다. 검색하는 동안 정지하고, 검색 뒤에는 다시 켜지 않습니다. 이 프로젝트의 모터 설정을 「저장 후 장비에 적용」 하면 이 프로젝트 설정으로 켜집니다.`
      : '모터 프로그램이 돌고 있으면 검색하는 동안 정지합니다. 검색 뒤 모터 설정을 「저장 후 장비에 적용」 하면 켜집니다.';
  return `${what} 모터를 검색합니다(수십 초 걸리며, 실패하면 몇 번 다시 시도합니다).\n`
    + `${restart} 그동안 서보 토크가 해제됩니다. 브레이크 보드가 연결된 모터는 브레이크가 잡아 주지만, 브레이크가 없는 모터는 처질 수 있으니 기구를 받치고, 움직이는 모터가 없을 때 진행하세요.\n\n`
    + `검색 결과는 저장하기 전까지 화면에만 표시됩니다. ${kind === 'all' ? '' : '검색하지 않은 종류의 모터는 그대로 둡니다. '}모터 이름과 드라이브 설정값은 유지됩니다.`
    + (dirty ? '\n\n저장하지 않은 변경 내용은 검색 결과로 대체됩니다.' : '');
}

/**
 * 앱솔루트 한 줄 글 · 모르는 것은 모른다고 · 수정 목록 120 (아)
 * 전에는 값을 못 읽은 채(검색 직후 · 모터 프로그램 꺼짐)에도 「앱솔루트 설정은 필요 없음」 이라 해서 인크리멘털 드라이브를 놓쳤다
 */
export function absoluteLine(abs) {
  if (!abs.total) return 'AC 서보 없음';
  const head = `앱솔루트 ${abs.ok}/${abs.total} 정상`;
  if (abs.allOk) return `${head} · 전원을 껐다 켜도 위치가 유지됩니다`;
  if (abs.needsSetup) return `${head} · ${abs.needsSetup}대 앱솔루트 설정 필요 · 정상이 아니면 모든 모터 동작이 차단됩니다`;
  const why = abs.unread && !abs.waiting
    ? `${abs.unread}대 아직 못 읽음(모터 프로그램이 이 프로젝트 설정으로 돌아야 읽습니다 · 「저장 후 장비에 적용」)`
    : `${abs.waiting + abs.unread}대 드라이브 응답을 기다리며 다시 읽는 중`;
  return `${head} · ${why} · 읽은 뒤 인크리멘털이면 「앱솔루트 설정」 이 나타납니다 · 확인될 때까지 모터 동작이 차단됩니다`;
}

/** 저장 전 검사 · 서버도 같은 것을 거절한다(수정 목록 37 · §6-217) */
/** EtherCAT 주소 겹침 · 서버 저장 검사(motor_profile_validation)와 같은 규칙 · 저장을 누르기 전에 보이게 (2026-10-12)
 *  Alias 1 이상은 같은 Master 안에서 겹치면 안 된다 · Alias 0 은 Slave 번호로 찾으니 Slave 번호가 겹치면 안 된다 */
function addressProblems(motors) {
  const problems = [];
  const seen = new Map();
  for (const motor of motors || []) {
    if (motor.deleted || !isAc(motor)) continue;
    const identity = motor.identity || {};
    const config = motor.config || {};
    // 주소 정보가 하나도 없으면 여기서 판정하지 않는다(서버가 「식별 정보 불완전」 으로 따로 말한다)
    if (![identity.ethercat_alias, identity.slave_position, config.alias, config.position].some((v) => v !== undefined && v !== null && v !== '')) continue;
    const master = Number(identity.ethercat_master_index ?? config.ethercat_master_index ?? 0) || 0;
    const alias = Number(identity.ethercat_alias ?? config.alias ?? 0) || 0;
    const position = Number(identity.slave_position ?? config.position ?? 0) || 0;
    const key = alias ? `m${master}:a${alias}` : `m${master}:p${position}`;
    const other = seen.get(key);
    if (other !== undefined) {
      problems.push(alias
        ? `${motor.axis}번 · EtherCAT Alias ${alias}가 ${other}번과 같습니다. 그 모터 줄을 눌러 「Alias 쓰기」로 다른 값이나 0으로 바꾸세요`
        : `${motor.axis}번 · Alias 0 · Slave ${position}이 ${other}번과 같습니다. 「전체 검색」으로 실제 Slave 번호를 다시 받으세요`);
    } else {
      seen.set(key, motor.axis);
    }
  }
  return problems;
}

export function motorProblems(motors) {
  const problems = addressProblems(motors);
  const names = new Map();
  for (const motor of motors || []) {
    if (motor.deleted) continue;
    const at = `${motor.axis}번`;
    const name = String(motor.name || '').trim();
    if (!name) problems.push(`${at} · 이름이 비어 있습니다`);
    else if (names.has(name)) problems.push(`${at} · 「${name}」 이름이 ${names.get(name)}번과 중복됩니다`);
    else names.set(name, motor.axis);
    for (const field of EDIT_FIELDS) {
      if (field.top || (field.ac && !isAc(motor))) continue;
      const raw = getField(motor, field.key);
      if (raw === null || raw === undefined || raw === '') continue;
      const value = Number(raw);
      if (!Number.isFinite(value)) problems.push(`${at} · ${field.label} 값이 숫자가 아닙니다`);
      else if ((field.min !== undefined && value < field.min) || (field.max !== undefined && value > field.max)) {
        problems.push(`${at} · ${field.label} 값은 ${field.min}~${field.max ?? '∞'} ${field.unit} 범위여야 합니다`);
      }
    }
    const config = motor.config || {};
    const pv = Number(config.profile_velocity);
    const rpm = Number(config.max_speed_rpm);
    if (isAc(motor) && pv > 0 && rpm > 0 && pv > rpm * 6 + 1e-6) problems.push(`${at} · 프로파일 속도 ${pv} deg/s가 최대 속도 ${rpm} rpm (${rpm * 6} deg/s)보다 큽니다`);
    const pa = Number(config.profile_acceleration);
    const acc = Number(config.acceleration);
    if (pa > 0 && acc > 0 && pa > acc + 1e-6) problems.push(`${at} · 프로파일 가속 ${pa}가 최대 가속 ${acc}보다 큽니다`);
  }
  return problems;
}

/** 저장 안 한 변경 · 사람이 읽는 줄 */
export function motorChanges(saved, draft) {
  const before = new Map((saved || []).map((m) => [m.id, m]));
  const after = new Set((draft || []).map((m) => m.id));
  const out = [];
  // 검색 제안으로 빠진 · 새로 든 모터 · 번호가 바뀐 모터도 변경이다 · 수정 목록 100
  for (const old of saved || []) {
    if (!after.has(old.id)) out.push(`${old.axis}번 ${old.name || ''} 삭제`.replace('  ', ' '));
  }
  for (const motor of draft || []) {
    const old = before.get(motor.id);
    if (!old) { out.push(`${motor.axis}번 ${motor.name || ''} 추가`.replace('  ', ' ')); continue; }
    if (Number(old.axis) !== Number(motor.axis)) out.push(`${motor.name || motor.id} 번호 ${old.axis} → ${motor.axis}`);
    for (const field of EDIT_FIELDS.concat([{ key: 'overload_monitor', label: '과부하율 읽기' }, { key: 'schedule_end_servo_off', label: '스케줄 모드에서 운영 시간이 끝나면 서보 끄기' }])) {
      const a = field.top ? old[field.key] : old.config?.[field.key];
      const b = field.top ? motor[field.key] : motor.config?.[field.key];
      const same = (a ?? '') === (b ?? '') || (Number.isFinite(Number(a)) && Number.isFinite(Number(b)) && a !== '' && b !== '' && Number(a) === Number(b));
      if (!same) out.push(`${motor.axis}번 ${field.label} ${a ?? '-'} → ${b ?? '-'}`);
    }
  }
  return out;
}

/** 앱솔루트 설정 일 · 상태 한 줄 */
export function absoluteJobText(job) {
  if (!job || !job.state || job.state === 'idle') return '';
  const step = job.step_count ? ` · ${job.step_index ?? 0}/${job.step_count}` : '';
  const label = job.step_label ? ` · ${job.step_label}` : '';
  // 다회전을 클리어하고 끝나면 「완료」 가 아니라 기준점 다시 지정 대기 · 클리어한 축을 다 다시 지정하면 완료 · 수정 목록 140
  const head = { running: job.resumed ? '앱솔루트 설정 이어서 하는 중' : '앱솔루트 설정 중', done: '앱솔루트 설정 완료', failed: '앱솔루트 설정 실패', reference_pending: '앱솔루트 설정 · 기준점 다시 지정 대기' }[job.state] || job.state;
  // 단계 이름·메시지가 머리말과 같은 말(「완료」 등)이면 한 번만
  const parts = [label, job.message, job.error].flatMap((part) => String(part || '').split(' · ')).map((part) => part.trim()).filter(Boolean);
  const unique = parts.filter((part, i) => !head.includes(part) && parts.indexOf(part) === i);
  return [`${head}${step}`, ...unique].join(' · ');
}

/**
 * 앱솔루트 설정 확인 창에 늘 적는 규칙 · 수정 목록 140 (사용자 결정 2026-10-14)
 * 다회전 클리어는 4/7 에서 Err40(다회전 무효)인 드라이브만 · 없으면 클리어 안 함 · 기준점 그대로
 */
export function absoluteClearRule() {
  return '대상 모터의 서보를 끄고 모터 프로그램을 잠시 정지합니다. 다회전 클리어는 4/7에서 Err40(다회전 무효)인 드라이브만 합니다. '
    + 'Err40이 없으면 클리어하지 않고 기준점도 그대로입니다(전원 재투입도 한 번). '
    + '클리어하는 축은 엔코더 회전 수가 0이 되어 위치 값이 바뀌므로, 감속 있는 축은 기준점을 눈으로 다시 맞춰야 합니다 · 모든 프로젝트. '
    + '다시 지정해 저장하기 전까지 재생·초기 위치 이동·스케줄·그룹 참가가 막힙니다.';
}

/** 앞서 실패한 앱솔루트 설정 「이어서 하기」 · 서버가 남긴 기록(job.resume · 웹을 다시 켜도 남음) · 진행 중엔 없음 · 수정 목록 134
 *  inline · 방금 실패한 그 작업 · 위 줄이 이미 실패 이유를 보여 주므로 버튼만 붙인다 · 아니면 따로 한 줄 */
export function absoluteResumeView(job) {
  const r = job?.resume;
  if (!r || !r.from_index || job?.state === 'running') return null;
  const count = r.step_count || 7;
  const drives = (r.targets || []).map((t) => t.label).filter(Boolean).join(', ');
  // 4/7 · 5/7 부터면 Err40 을 다시 읽어 그 드라이브만 클리어 · 6/7 부터는 클리어한 드라이브가 있을 때만 남는다 · 140 ⑤
  const note = `${drives || '대상 드라이브'} · ${r.from_index <= 5 ? '다회전 클리어를 아직 하지 않았습니다 · Err40 인 드라이브만 클리어합니다' : r.from_index === 6 ? '다회전 클리어는 했고 전원 재투입·확인이 남았습니다' : '최종 확인이 남았습니다'}`;
  const inline = job?.state === 'failed' && job?.step === r.failed_step;
  return {
    inline,
    note,
    text: [`앱솔루트 설정 실패 · ${r.failed_index}/${count} · ${r.failed_label}`, r.error, note].filter(Boolean).join(' · '),
    label: `이어서 하기 (${r.from_index}/${count} 부터)`,
  };
}

/** 이어서 하기 확인 창 · 미리보기(서버) 그대로 · 134 · 클리어는 Err40 인 드라이브만 · 클리어한 축만 기준점 다시 지정 · 140 */
export function absoluteResumeConfirm(preview) {
  const p = preview || {};
  const count = p.step_count || 7;
  const from = p.from_index || 1;
  const steps = (p.steps || []).map((s, i) => `${from + i}. ${s}`);
  const cycles = (p.steps || []).filter((s) => String(s).includes('전원')).length;
  const clear = p.clear_done
    ? `다회전 클리어는 이미 했습니다(${(p.cleared || []).map((t) => t.label).filter(Boolean).join(', ') || '대상 드라이브'}). 엔코더 회전 수가 0으로 초기화되어 위치 값이 바뀌었으므로 끝나면 그 축의 기준점을 다시 지정해 저장해야 합니다. 그 전에는 모든 프로젝트에서 재생·초기 위치 이동·스케줄·그룹 참가가 막힙니다.`
    : absoluteClearRule();
  return {
    title: `앱솔루트 설정 이어서 하기 (${from}/${count} 부터)`,
    body: [
      `앞서 ${p.failed_index ?? '?'}/${count} ${p.failed_label || ''}에서 멈춘 작업을 같은 드라이브로 이어서 합니다.${p.error ? `\n실패 이유 · ${p.error}` : ''}`,
      `대상\n${(p.targets || []).map((t) => `· ${t.label || t.axis}`).join('\n')}`,
      steps.join('\n'),
      `${cycles ? `중간에 드라이브 전원을 ${cycles === 1 ? '한 번' : '최대 두 번'} 더 껐다 켜야 합니다(화면에 안내가 나옵니다 · 두 번째는 클리어할 때만). ` : ''}${clear}`,
    ].join('\n\n'),
    confirmLabel: '이어서 하기',
    tone: 'danger',
  };
}
