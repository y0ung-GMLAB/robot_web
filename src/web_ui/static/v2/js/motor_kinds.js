/** UI v2 · 모터 종류 표 · 한 곳에서 판단 · 수정 목록 158 (docs/SERIAL_SERVO_DESIGN.md §1 · §6)
 *
 * 서버 `motion_common/motor_kinds.py` 표의 화면 사본 · 종류 = `motor_type`
 * 직렬 서보 = 종류가 분명히 dynamixel · feetech 일 때만 · 그 밖(unknown 포함)은 전처럼 AC 길 (`isAcPath`)
 * 직렬 서보(dynamixel · feetech) 공통 · 토크 켜기/끄기 · 조그 · 절대 이동 · 같은 통로 `/api/motion-test/dynamixel/*`
 * 종류별 · 재부팅(Dynamixel 만) · 검색
 */

/** 종류 표 · short = 모터 목록 짧은 이름 · power = 켜기/끄기 대상 낱말 · reset = 오류 해제 버튼 · ac = 드라이브 게인 · EEPROM · 앱솔루트 · 다회전 클리어 · 과부하율 · 브레이크 */
export const MOTOR_KINDS = Object.freeze({
  ac_servo: Object.freeze({ kind: 'ac_servo', short: 'AC', label: 'AC 서보', driverFamily: 'minas', transport: 'ethercat',
    serial: false, power: '서보', reset: '오류 초기화', reboot: false, ac: true, gearRatioEditable: true, controlPath: '/api/motion-test/ac-servo' }),
  dynamixel: Object.freeze({ kind: 'dynamixel', short: 'DXL', label: '다이나믹셀', driverFamily: 'dynamixel', transport: 'serial',
    serial: true, power: '토크', reset: '재부팅', reboot: true, ac: false, gearRatioEditable: true, controlPath: '/api/motion-test/dynamixel' }),
  feetech: Object.freeze({ kind: 'feetech', short: 'FT', label: 'Feetech', driverFamily: 'feetech', transport: 'serial',
    serial: true, power: '토크', reset: '', reboot: false, ac: false, gearRatioEditable: true, controlPath: '/api/motion-test/dynamixel' }),
  // 모르는 종류(런타임 'unknown' · 칸 없음 · cubemars · zeroerr …) · 화면 동작은 전과 같이 AC 길 · 버튼 · 글 · 통로 모두 AC 와 같음 ·
  // 전 v2 규칙 `motor_type !== 'dynamixel'` = AC 를 지킨다 (사용자 조건 · 기존 AC 동작 변화 없음)
  unknown: Object.freeze({ kind: 'unknown', short: 'AC', label: 'AC 서보', driverFamily: '', transport: '',
    serial: false, power: '서보', reset: '오류 초기화', reboot: false, ac: true, gearRatioEditable: true, controlPath: '/api/motion-test/ac-servo' }),
});

/** motor_type · driver_family 값 → 종류 · 런타임(motion_state)은 AC 를 `minas` 로 적는다 */
const TYPE_ALIASES = Object.freeze({
  ac_servo: 'ac_servo',
  minas: 'ac_servo',
  dynamixel: 'dynamixel',
  feetech: 'feetech',
});

function aliasOf(value) {
  return TYPE_ALIASES[String(value ?? '').trim().toLowerCase()] || '';
}

/**
 * 모터 하나의 종류 · `ac_servo` | `dynamixel` | `feetech` | `unknown`
 * motor_type → transport `ethercat`(EtherCAT 위 종류는 AC 서보뿐) 순서 · 그 밖은 unknown(= 화면은 AC 길)
 * driver_family 는 보지 않는다 · motor_type 이 dynamixel · feetech 일 때만 직렬 서보(전 규칙과 같게)
 */
export function motorKind(motor) {
  const byType = aliasOf(motor?.motor_type);
  if (byType) return byType;
  if (String(motor?.transport ?? '').trim().toLowerCase() === 'ethercat') return 'ac_servo';
  return 'unknown';
}

/** 종류 이름 → 표 한 줄 · 모르면 unknown 줄 */
export function kindSpec(kind) {
  return MOTOR_KINDS[kind] || MOTOR_KINDS.unknown;
}

/** 직렬 버스 서보(dynamixel · feetech) · 토크 · 조그 · 절대 이동 · 오류 표시 공통 */
export function isSerialServo(kind) {
  return kindSpec(kind).serial === true;
}

/** AC 길 · 직렬 서보가 아닌 모든 종류(unknown · 칸 없음 포함) · 전 v2 `motor_type !== 'dynamixel'` 과 같은 뜻 */
export function isAcPath(kind) {
  return !isSerialServo(kind);
}

/** 화면 줄(motorRows · 수동 조작 항목)의 종류 · kindKey 우선 · 옛 줄(ac 만 있음)은 ac=false → dynamixel · 그 밖 AC */
export function rowKind(row) {
  if (row?.kindKey && MOTOR_KINDS[row.kindKey]) return row.kindKey;
  return row?.ac === false ? 'dynamixel' : 'ac_servo';
}
