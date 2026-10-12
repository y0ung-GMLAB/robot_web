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
  { key: 'brake_delay_stop_ms', label: '브레이크 · 정지', unit: 'ms', ac: true, min: 0, max: 10000 },
  { key: 'brake_delay_run_ms', label: '브레이크 · 동작', unit: 'ms', ac: true, min: 0, max: 10000 },
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

const ABS_TEXT = { ok: ['정상', 'ok'], not_absolute: ['앱솔루트 아님', 'bad'], unknown: ['확인 안 됨', 'warn'], multiturn_invalid: ['다회전 무효(Err40)', 'bad'] };

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
      comm: String(live.state || '없음'),
      masterIndex: Number(motor.identity?.ethercat_master_index ?? motor.config?.ethercat_master_index ?? 0),
      slavePosition: Number(motor.config?.position ?? motor.identity?.slave_position),
    };
  }).sort((a, b) => a.axis - b.axis);
}

/** 앱솔루트 한 줄 · 「3/3 정상」 */
export function absoluteSummary(rows) {
  const ac = rows.filter((r) => r.ac);
  const ok = ac.filter((r) => r.absolute === '정상').length;
  return { total: ac.length, ok, allOk: ac.length > 0 && ok === ac.length };
}

/** 저장 전 검사 · 서버도 같은 것을 거절한다(수정 목록 37 · §6-217) */
export function motorProblems(motors) {
  const problems = [];
  const names = new Map();
  for (const motor of motors || []) {
    if (motor.deleted) continue;
    const at = `${motor.axis}번`;
    const name = String(motor.name || '').trim();
    if (!name) problems.push(`${at} · 이름이 비었습니다`);
    else if (names.has(name)) problems.push(`${at} · 이름 「${name}」 이 ${names.get(name)}번과 겹칩니다`);
    else names.set(name, motor.axis);
    for (const field of EDIT_FIELDS) {
      if (field.top || (field.ac && !isAc(motor))) continue;
      const raw = getField(motor, field.key);
      if (raw === null || raw === undefined || raw === '') continue;
      const value = Number(raw);
      if (!Number.isFinite(value)) problems.push(`${at} · ${field.label} 숫자가 아닙니다`);
      else if ((field.min !== undefined && value < field.min) || (field.max !== undefined && value > field.max)) {
        problems.push(`${at} · ${field.label} 은 ${field.min}~${field.max ?? '∞'} ${field.unit}`);
      }
    }
    const config = motor.config || {};
    const pv = Number(config.profile_velocity);
    const rpm = Number(config.max_speed_rpm);
    if (isAc(motor) && pv > 0 && rpm > 0 && pv > rpm * 6 + 1e-6) problems.push(`${at} · 프로파일 속도 ${pv} deg/s 가 최대 속도 ${rpm} rpm (${rpm * 6} deg/s) 보다 큽니다`);
    const pa = Number(config.profile_acceleration);
    const acc = Number(config.acceleration);
    if (pa > 0 && acc > 0 && pa > acc + 1e-6) problems.push(`${at} · 프로파일 가속 ${pa} 가 최대 가속 ${acc} 보다 큽니다`);
  }
  return problems;
}

/** 저장 안 한 변경 · 사람이 읽는 줄 */
export function motorChanges(saved, draft) {
  const before = new Map((saved || []).map((m) => [m.id, m]));
  const out = [];
  for (const motor of draft || []) {
    const old = before.get(motor.id);
    if (!old) continue;
    for (const field of EDIT_FIELDS.concat([{ key: 'overload_monitor', label: '과부하 감시' }, { key: 'schedule_end_servo_off', label: '운영 끝 서보 끄기' }])) {
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
  const head = { running: '앱솔루트 설정 중', done: '앱솔루트 설정 끝', failed: '앱솔루트 설정 실패' }[job.state] || job.state;
  return `${head}${step}${label}${job.message ? ` · ${job.message}` : ''}${job.error ? ` · ${job.error}` : ''}`;
}
