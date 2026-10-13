/** UI v2 · 모터·드라이브 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 모터·드라이브)
 *
 * 설정(registry · 파일)과 지금 상태(motion_state.motors · 런타임)를 번호(axis = controller_index)로 맞춘다.
 * 편집 칸은 기존 화면이 고치던 것만 · 이름 · 속도·가속 · 브레이크 · 과부하 감시 · 운영 끝 서보 끄기.
 */
import { motorErrorText, motorLoad } from './model.js';

/** 편집 칸 · [키, 이름, 단위, AC 전용, 범위] · config 아래(name 만 바깥) */
export const EDIT_FIELDS = [
  { key: 'name', label: '이름', top: true },
  { key: 'max_speed_rpm', label: '최대 속도', unit: 'rpm', ac: true, min: 1, max: 6500 },
  { key: 'profile_velocity', label: '프로파일 속도', unit: 'deg/s', min: 0 },
  { key: 'acceleration', label: '최대 가속', unit: 'deg/s²', min: 0 },
  { key: 'profile_acceleration', label: '프로파일 가속', unit: 'deg/s²', min: 0 },
  // 비우면 「모든 MINAS 드라이브 공통 설정」(아래 칸 · config/minas_base.yaml) · 이름은 공통 설정과 같은 말 · 사용자 2026-10-13
  { key: 'brake_delay_stop_ms', label: '브레이크 지연 · 멈춰 있을 때', unit: 'ms', ac: true, min: 0, max: 10000, blank: '비우면 공통 설정(기본 150)' },
  { key: 'brake_delay_run_ms', label: '브레이크 지연 · 움직이는 중', unit: 'ms', ac: true, min: 0, max: 10000, blank: '비우면 공통 설정(기본 0)' },
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

function isAc(motor) {
  return String(motor?.motor_type || '') !== 'dynamixel';
}

const ABS_TEXT = { ok: ['정상', 'ok'], not_absolute: ['앱솔루트 아님', 'bad'], unknown: ['다시 읽는 중', 'warn'], multiturn_invalid: ['다회전 무효(Err40)', 'bad'] };

/** 표 줄 · 설정 + 지금 상태 */
export function motorRows(registry, snap) {
  const runtime = new Map((snap?.motion_state?.motors || []).map((m) => [Number(m.controller_index), m]));
  const drives = new Map((snap?.motion_state?.minas_absolute?.drives || []).map((d) => [Number(d.axis), d]));
  const motors = (registry?.motors || []).filter((m) => !m.deleted);
  return motors.map((motor) => {
    const axis = Number(motor.axis ?? motor.config?.controller_index);
    const live = runtime.get(axis) || {};
    const drive = drives.get(axis);
    const ac = isAc(motor);
    let servo = live.state !== 'detected' ? ['통신 없음', 'bad'] : live.fault ? ['알람', 'bad'] : live.servo_on ? ['켜짐', 'ok'] : ['꺼짐', 'warn'];
    if (!ac && live.state === 'detected') servo = live.fault ? ['오류', 'bad'] : live.servo_on ? ['토크 켜짐', 'ok'] : ['토크 꺼짐', 'warn'];
    const position = live.position_rad === null || live.position_rad === undefined ? null : Number(live.position_rad) * 180 / Math.PI;
    const [absText, absTone] = !ac ? ['-', 'idle'] : drive ? (ABS_TEXT[drive.status] || [String(drive.status), 'warn']) : ['-', 'idle'];
    return {
      id: String(motor.id || ''),
      axis,
      name: String(motor.name || ''),
      ac,
      kind: `${ac ? 'AC' : 'DXL'}${motor.profile?.driver_model ? ` · ${motor.profile.driver_model}` : ''}`,
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
      comm: live.state === 'detected' ? '연결됨' : live.state ? `연결 안 됨 (${live.state})` : '연결 안 됨',
      masterIndex: Number(motor.identity?.ethercat_master_index ?? motor.config?.ethercat_master_index ?? 0),
      slavePosition: Number(motor.config?.position ?? motor.identity?.slave_position),
    };
  }).sort((a, b) => a.axis - b.axis);
}

/** 앱솔루트 한 줄 · 「3/3 정상」 */
export function absoluteSummary(rows) {
  const ac = rows.filter((r) => r.ac);
  const ok = ac.filter((r) => r.absolute === '정상').length;
  // 「앱솔루트 설정」 은 값이 틀린 드라이브(Pr0.15 ≠ 0 · Err40)에만 권한다 · 그 버튼은 다회전 클리어까지 가서
  // 기준점을 잃는다 · 읽기만 실패한 것(unknown)은 감시가 몇 초마다 다시 읽는다 (수정 목록 110)
  const needsSetup = ac.filter((r) => r.absoluteStatus === 'not_absolute' || r.absoluteStatus === 'multiturn_invalid').length;
  const waiting = ac.filter((r) => r.absoluteStatus === 'unknown').length;
  return { total: ac.length, ok, allOk: ac.length > 0 && ok === ac.length, needsSetup, waiting };
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
    for (const field of EDIT_FIELDS.concat([{ key: 'overload_monitor', label: '과부하율 읽기' }, { key: 'schedule_end_servo_off', label: '운영 시간이 끝나면 서보 끄기' }])) {
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
  const head = { running: '앱솔루트 설정 중', done: '앱솔루트 설정 완료', failed: '앱솔루트 설정 실패' }[job.state] || job.state;
  // 단계 이름·메시지가 머리말과 같은 말(「완료」 등)이면 한 번만
  const parts = [label, job.message, job.error].flatMap((part) => String(part || '').split(' · ')).map((part) => part.trim()).filter(Boolean);
  const unique = parts.filter((part, i) => !head.includes(part) && parts.indexOf(part) === i);
  return [`${head}${step}`, ...unique].join(' · ');
}
