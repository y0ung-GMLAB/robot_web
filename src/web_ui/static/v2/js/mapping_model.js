/** UI v2 · 조인트 매핑 편집 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 조인트 매핑)
 *
 * 서버 칸은 rad · 화면 초안은 deg (기존 화면 unit_view 규칙과 같은 이름 바꾸기 · 수정 목록 6).
 * 식 하나 · 모터 = 기준점 + (조인트 + offset) × scale × 방향 × 감속비 (motion_common/joint_mapping.py 와 같음).
 * offset · scale 은 화면에 안 보이지만 그대로 들고 다닌다(기존 화면과 같음).
 */

const DEG = 180 / Math.PI;
const RAD = Math.PI / 180;

/** rad 칸 → deg 칸 · 접미사만 바꾼다 */
const ANGLE_FIELDS = [
  ['reference_position_rad', 'reference_position_deg'],
  ['motion_lower_rad', 'motion_lower_deg'],
  ['motion_upper_rad', 'motion_upper_deg'],
  ['initial_motion_position_rad', 'initial_motion_position_deg'],
  ['offset_rad', 'offset_deg'],
  ['max_velocity_rad_s', 'max_velocity_deg_s'],
  ['max_acceleration_rad_s2', 'max_acceleration_deg_s2'],
];

function round(value, digits = 6) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export const INITIAL_MODES = [
  ['reference', '기준점 (0°)'],
  ['first_frame', '첫 프레임'],
  ['manual', '지정 값'],
];

export function rowToDraft(row) {
  const out = { ...row };
  for (const [rad, deg] of ANGLE_FIELDS) {
    delete out[rad];
    const value = row?.[rad];
    out[deg] = value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : round(Number(value) * DEG);
  }
  out.motion_id = String(row?.motion_id ?? '');
  out.enabled = row?.enabled !== false;
  out.invert = row?.invert === true;
  out.gear_ratio = Number(row?.gear_ratio ?? 1);
  out.scale = Number(row?.scale ?? 1);
  out.reference_enabled = row?.reference_enabled !== false;
  out.initial_mode = ['reference', 'first_frame', 'manual'].includes(row?.initial_mode) ? row.initial_mode : 'reference';
  out.motor_axis = row?.motor_axis === null || row?.motor_axis === undefined || row?.motor_axis === '' ? null : Number(row.motor_axis);
  out.motor_ref = String(row?.motor_ref || '');
  return out;
}

/** 초안 → 서버 · 최대 속도·가속은 비우면 칸을 뺀다(검사 안 함 · 5-2) */
export function draftToRow(draft) {
  const out = { ...draft };
  for (const [rad, deg] of ANGLE_FIELDS) {
    const value = draft[deg];
    delete out[deg];
    const empty = value === null || value === undefined || value === '' || !Number.isFinite(Number(value));
    if (rad.startsWith('max_')) {
      if (!empty && Number(value) > 0) out[rad] = round(Number(value) * RAD, 12);
      continue;
    }
    out[rad] = empty ? 0 : round(Number(value) * RAD, 12);
  }
  if (!out.reference_enabled) out.reference_position_rad = 0;
  out.motion_id = String(out.motion_id || '').trim();
  return out;
}

/**
 * 범위를 사람이 확인했나 · 서버 joint_mapping.range_confirmed 와 같은 규칙 · 수정 목록 97
 * 칸이 있으면 그 값 · 없으면(옛 파일) 범위로 짐작 · −180 ~ 180 그대로면 미확인
 */
export function rangeConfirmed(row) {
  if (row?.range_confirmed !== undefined && row?.range_confirmed !== null) return Boolean(row.range_confirmed);
  const lower = Number(row?.motion_lower_deg);
  const upper = Number(row?.motion_upper_deg);
  return !(Math.abs(lower - -180) < 1e-6 && Math.abs(upper - 180) < 1e-6);
}

/** 최소·최대 둘 다 기본값(±180)이 아니게 되면 저절로 확인 · 끄지는 않는다(기존 화면과 같음) */
export function autoConfirmRange(row) {
  const lower = Number(row.motion_lower_deg);
  const upper = Number(row.motion_upper_deg);
  if (Number.isFinite(lower) && Number.isFinite(upper) && lower !== -180 && upper !== 180) row.range_confirmed = true;
}

/** 재생을 막는 줄 · 「사용」 이고 이름 있고 미확인 */
export function unconfirmedRows(rows) {
  return (rows || []).filter((row) => row.enabled !== false && String(row.motion_id || '').trim() && !rangeConfirmed(row));
}

export function newRow(motorAxis = null, name = '') {
  return rowToDraft({
    // ±180 은 기계 범위가 아니다 · 사람이 범위를 넣거나 확인해야 재생된다 · 수정 목록 97
    range_confirmed: false,
    motion_id: name, enabled: motorAxis !== null, motor_ref: '', motor_axis: motorAxis,
    reference_enabled: true, reference_position_rad: 0, motion_lower_rad: -Math.PI, motion_upper_rad: Math.PI,
    initial_mode: 'reference', initial_motion_position_rad: 0, initial_move_time_sec: 5, invert: false,
    offset_rad: 0, scale: 1, gear_ratio: 1,
  });
}

/**
 * 모터 고유 이름(motor_ref) · 서버 형식 그대로 · 번호가 바뀌어도 같은 드라이브를 가리킨다
 * AC · ac_servo:master:<m>:alias:<n>(alias>0) 또는 :slave:<pos> · DXL · dynamixel:port:<포트>:id:<id>
 */
/** 모터 고르기 목록에 붙일 「어느 드라이브인지」 · AC 는 슬레이브 번호와 alias · 다이나믹셀은 포트와 ID */
export function motorWhere(motor) {
  if (!motor) return '';
  if (String(motor.motor_type || '').toLowerCase() === 'dynamixel') {
    const id = Number(motor.bus_id ?? motor.node_id);
    const port = String(motor.serial_port ?? '').trim();
    return ['DXL', port, Number.isInteger(id) ? `ID ${id}` : ''].filter(Boolean).join(' · ');
  }
  const slave = Number(motor.slave_position);
  const alias = Number(motor.alias ?? motor.ethercat_alias);
  const master = Number(motor.ethercat_master_index ?? 0);
  return ['AC',
    Number.isInteger(master) && master > 0 ? `마스터 ${master}` : '',
    Number.isInteger(slave) && slave >= 0 ? `슬레이브 ${slave}` : '',
    Number.isFinite(alias) && alias > 0 ? `alias ${alias}` : ''].filter(Boolean).join(' · ');
}

export function motorRefFor(motor) {
  if (!motor) return '';
  const type = String(motor.motor_type || '').toLowerCase();
  if (type === 'ac_servo') {
    const master = Number(motor.ethercat_master_index ?? 0);
    if (!Number.isInteger(master) || master < 0) return '';
    const alias = Number(motor.alias ?? motor.ethercat_alias);
    if (Number.isFinite(alias) && alias > 0) return `ac_servo:master:${master}:alias:${alias}`;
    const slave = Number(motor.slave_position);
    return Number.isInteger(slave) && slave >= 0 ? `ac_servo:master:${master}:slave:${slave}` : '';
  }
  if (type === 'dynamixel') {
    const id = Number(motor.bus_id ?? motor.node_id);
    const port = String(motor.serial_port ?? '').trim();
    return Number.isInteger(id) && id >= 0 && port ? `dynamixel:port:${encodeURIComponent(port)}:id:${id}` : '';
  }
  return '';
}

/** 줄이 가리키는 모터 · ref 가 맞으면 그것 · 아니면 번호 (대소문자 무시 · §6-104) */
export function motorForRow(row, motors) {
  const ref = String(row.motor_ref || '').toLowerCase();
  if (ref) {
    const byRef = motors.filter((m) => m.ref && m.ref.toLowerCase() === ref);
    if (byRef.length === 1) return byRef[0];
  }
  return motors.find((m) => m.axis === row.motor_axis) || null;
}

/** 모터 이름표 · 행이 가리키는 모터(번호 또는 ref) */
export function rowTarget(draft) {
  if (draft.motor_ref) return `ref:${draft.motor_ref.toLowerCase()}`;
  if (draft.motor_axis !== null && draft.motor_axis !== undefined && Number.isFinite(Number(draft.motor_axis))) return `axis:${Number(draft.motor_axis)}`;
  return '';
}

/** 저장 전에 화면이 먼저 막는 것 · 서버는 이름 빈 줄을 조용히 버리므로 여기서 잡는다(수정 목록 68) */
export function draftProblems(rows) {
  const problems = [];
  const names = new Map();
  const targets = new Map();
  rows.forEach((row, index) => {
    const at = `${index + 1}번 줄`;
    const name = String(row.motion_id || '').trim();
    if (!name) problems.push(`${at} · 조인트 이름이 비어 있습니다${row.motor_axis !== null ? ` (${row.motor_axis}번 모터)` : ''}`);
    else if (names.has(name)) problems.push(`${at} · 「${name}」 이름이 ${names.get(name) + 1}번 줄과 중복됩니다`);
    else names.set(name, index);
    if (!(Number(row.gear_ratio) > 0)) problems.push(`${at} · 감속·기어비는 0보다 커야 합니다`);
    if (!Number(row.scale)) problems.push(`${at} · 배율(scale)이 0입니다 · 매핑 파일을 확인하세요`);
    const lower = Number(row.motion_lower_deg);
    const upper = Number(row.motion_upper_deg);
    if (!Number.isFinite(lower) || !Number.isFinite(upper)) problems.push(`${at} · 범위를 입력하세요`);
    else if (lower > upper) problems.push(`${at} · 범위 최소가 최대보다 큽니다`);
    if (row.enabled) {
      const target = rowTarget(row);
      if (!target) problems.push(`${at} · 「사용」이 켜진 줄에 모터가 지정되지 않았습니다`);
      else if (targets.has(target)) problems.push(`${at} · ${targets.get(target) + 1}번 줄과 같은 모터를 사용합니다`);
      else targets.set(target, index);
    }
  });
  if (!rows.length) problems.push('조인트가 하나도 없습니다');
  return problems;
}

/** 모터 deg · 식 하나 */
export function jointToMotor(row, jointDeg) {
  const ref = row.reference_enabled === false ? 0 : Number(row.reference_position_deg || 0);
  const sign = row.invert ? -1 : 1;
  return ref + (Number(jointDeg) + Number(row.offset_deg || 0)) * Number(row.scale ?? 1) * sign * Number(row.gear_ratio || 1);
}

/** 모터 deg → 조인트 deg · 식을 거꾸로 · 이득이 0 이면 null */
export function motorToJoint(row, motorDeg) {
  const ref = row.reference_enabled === false ? 0 : Number(row.reference_position_deg || 0);
  const gain = Number(row.scale ?? 1) * (row.invert ? -1 : 1) * Number(row.gear_ratio || 1);
  if (!gain) return null;
  return (Number(motorDeg) - ref) / gain - Number(row.offset_deg || 0);
}

/** 고른 줄 미리보기 · 조인트 +1° → 모터 · 범위 → 모터 한계 */
export function previewRow(row) {
  const gain = Number(row.scale ?? 1) * (row.invert ? -1 : 1) * Number(row.gear_ratio || 1);
  const a = jointToMotor(row, Number(row.motion_lower_deg));
  const b = jointToMotor(row, Number(row.motion_upper_deg));
  return { perDegree: gain, motorMin: Math.min(a, b), motorMax: Math.max(a, b) };
}

const LABELS = {
  motion_id: '이름', enabled: '사용', motor_axis: '모터', gear_ratio: '감속·기어비', invert: '방향 반전',
  reference_position_deg: '기준점', motion_lower_deg: '최소', motion_upper_deg: '최대',
  max_velocity_deg_s: '최대 속도', max_acceleration_deg_s2: '최대 가속', initial_mode: '초기 위치',
  initial_motion_position_deg: '지정 값', range_confirmed: '범위 확인',
};

function same(a, b) {
  if (typeof a === 'number' || typeof b === 'number') {
    const x = Number(a);
    const y = Number(b);
    if (!Number.isFinite(x) && !Number.isFinite(y)) return true;
    return Math.abs(x - y) < 1e-6;
  }
  return (a ?? '') === (b ?? '');
}

/** 저장 안 한 변경 · 사람이 읽는 줄 · 줄 더함/뺌/칸 바뀜 */
export function changeSummary(saved, draft) {
  const out = [];
  const byKey = (rows) => rows.map((row, index) => ({ row, key: row._key ?? `i${index}` }));
  const before = new Map(byKey(saved).map(({ row, key }) => [key, row]));
  const after = byKey(draft);
  for (const { row, key } of after) {
    const old = before.get(key);
    const name = row.motion_id || '(이름 없음)';
    if (!old) { out.push(`${name} 추가`); continue; }
    before.delete(key);
    for (const field of Object.keys(LABELS)) {
      if (!same(old[field], row[field])) out.push(`${name} ${LABELS[field]} ${fmt(old[field])} → ${fmt(row[field])}`);
    }
  }
  for (const row of before.values()) out.push(`${row.motion_id || '(이름 없음)'} 삭제`);
  return out;
}

function fmt(value) {
  if (value === true) return '켬';
  if (value === false) return '끔';
  if (value === null || value === undefined || value === '') return '-';
  return String(value);
}

/** 서버 충돌 문구 · 다른 화면에서 먼저 바꿈 (§6-243) */
export function isRevisionConflict(message) {
  return /화면을 불러온 뒤 변경됐습니다|버전 정보가 없습니다/.test(String(message || ''));
}

/**
 * 같은 줄 찾기 · 객체가 아니라 조인트 이름 + 모터로 · 수정 목록 117
 * 화면은 매핑을 15초마다 다시 불러 새 객체를 만든다 · 그 사이 그린 칸의 줄은 옛 객체라 === 로는 못 찾는다
 * 이름·모터 둘 다 맞는 줄 · 없으면 이름만 맞는 줄이 하나일 때 그것 · 없으면 −1
 */
export function findRowIndex(rows, target) {
  const name = String(target?.motion_id || '').trim();
  if (!name) return -1;
  const sameName = (row) => String(row?.motion_id || '').trim() === name;
  const where = rowTarget(target);
  const exact = (rows || []).findIndex((row) => sameName(row) && rowTarget(row) === where);
  if (exact >= 0) return exact;
  const byName = (rows || []).map((row, index) => (sameName(row) ? index : -1)).filter((index) => index >= 0);
  return byName.length === 1 ? byName[0] : -1;
}

/** 줄 하나에 칸 몇 개만 바꾼 새 목록 · 못 찾으면 null · 지금 목록의 줄 위에 바꾼다(옛 사본으로 덮지 않게) */
export function patchRow(rows, target, patch) {
  const index = findRowIndex(rows, target);
  if (index < 0) return null;
  const row = { ...rows[index], ...patch };
  return { index, row, rows: rows.map((r, i) => (i === index ? row : r)) };
}

/**
 * 저장 뒤 확인 · 서버가 돌려준 줄(rad)에 바꾼 칸이 들어갔나 · 다른 칸을 사람이 읽는 글로 · 빈 목록이면 맞음 (수정 목록 117)
 * 「저장했습니다」 만 믿지 않는다 · 파일에 안 들어갔으면 실패로 알린다
 */
export function savedMismatch(serverRows, target, patch) {
  const rows = (serverRows || []).map(rowToDraft);
  const index = findRowIndex(rows, target);
  if (index < 0) return [`「${String(target?.motion_id || '')}」 줄을 저장된 매핑에서 찾지 못했습니다`];
  const saved = rows[index];
  const out = [];
  for (const [field, want] of Object.entries(patch)) {
    if (!(field in LABELS)) continue;
    const ok = typeof want === 'number' ? Math.abs(Number(saved[field]) - want) < 1e-4 : same(saved[field], want);
    if (!ok) out.push(`${LABELS[field]} · 보낸 값 ${fmt(want)} · 파일 값 ${fmt(saved[field])}`);
  }
  return out;
}
