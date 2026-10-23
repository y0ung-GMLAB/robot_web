/** 직렬 버스 서보 · Feetech 추가 · 종류 표 한 곳 · 수정 목록 158 (docs/SERIAL_SERVO_DESIGN.md §1 · §6)
 *
 * AC 서보 · 다이나믹셀 화면 동작은 그대로 · Feetech 은 직렬 서보 공통(토크 · 조그 · 절대 이동) · 재부팅 없음 ·
 * 모르는 종류는 AC 아님 (전 v2 `motor_type !== 'dynamixel'` = AC)
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { MOTOR_KINDS, isAcPath, isSerialServo, kindSpec, motorKind, rowKind } from '../static/v2/js/motor_kinds.js';
import { absoluteSummary, motorProblems, motorRows, scanConfirmText } from '../static/v2/js/motors_model.js';
import { motorErrorText } from '../static/v2/js/model.js';
import { motorRefFor, motorWhere } from '../static/v2/js/mapping_model.js';
import { axisRows } from '../static/v2/js/play_model.js';
import { manualBlocker } from '../static/v2/js/pages/manual.js';
import { runtimeIsDynamixel } from '../static/js/motor_type_dynamixel.js';
import { normalizeMotorTypeKey } from '../static/js/format.js';
import { servoButtonLabels } from '../static/js/motion_test.js';
import { motionMotorIdentityLabel, motionMotorRef, motionMotorRefs } from '../static/js/motion_data.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('종류 표 · 짧은 이름 AC · DXL · FT · 재부팅은 다이나믹셀만 · AC 전용 칸은 AC 만', () => {
  assert.deepEqual(['ac_servo', 'dynamixel', 'feetech'].map((k) => MOTOR_KINDS[k].short), ['AC', 'DXL', 'FT']);
  assert.deepEqual(['ac_servo', 'dynamixel', 'feetech', 'unknown'].map((k) => kindSpec(k).reboot), [false, true, false, false]);
  assert.deepEqual(['ac_servo', 'dynamixel', 'feetech'].map((k) => kindSpec(k).ac), [true, false, false]);
  assert.deepEqual(['ac_servo', 'dynamixel', 'feetech', 'unknown'].map(isSerialServo), [false, true, true, false]);
  assert.deepEqual(['ac_servo', 'dynamixel', 'feetech'].map((k) => kindSpec(k).transport), ['ethercat', 'serial', 'serial']);
  // 직렬 서보는 한 통로 · 감속·기어비 편집은 모두 됨
  assert.equal(kindSpec('feetech').controlPath, kindSpec('dynamixel').controlPath);
  assert.ok(['ac_servo', 'dynamixel', 'feetech'].every((k) => kindSpec(k).gearRatioEditable));
  assert.equal(kindSpec('없는 종류'), MOTOR_KINDS.unknown);
});

test('모르는 종류 · 화면 동작은 AC 와 똑같음 · 짧은 이름 · 버튼 · 통로 · 앱솔루트 등 AC 전용 칸 (기존 AC 동작 변화 없음)', () => {
  const { kind: _a, label: _b, transport: _c, driverFamily: _d, ...acBehaviour } = MOTOR_KINDS.ac_servo;
  const { kind: _e, label: _f, transport: _g, driverFamily: _h, ...unknownBehaviour } = MOTOR_KINDS.unknown;
  assert.deepEqual(unknownBehaviour, acBehaviour);
  assert.deepEqual(['ac_servo', 'unknown', 'dynamixel', 'feetech'].map(isAcPath), [true, true, false, false]);
});

test('motorKind · 직렬 서보는 motor_type 이 dynamixel · feetech 일 때만 · 나머지는 전처럼 AC 길', () => {
  // 전 v2 규칙 · motor_type 이 'dynamixel' 이 아니면 AC
  const old = (m) => String(m?.motor_type || '') !== 'dynamixel';
  const variants = [
    { motor_type: 'ac_servo' }, { motor_type: 'minas' }, { motor_type: 'dynamixel' },
    { motor_type: 'ac_servo', transport: 'ethercat', driver_family: 'minas' },
    { motor_type: 'dynamixel', transport: 'serial', driver_family: 'dynamixel' },
    { motor_type: 'unknown', transport: 'ethercat' }, { motor_type: 'zeroerr', transport: 'ethercat' },
    // state_publisher 기본값(메타데이터 없음) · 옛 레지스트리(칸 없음) · CAN 모터
    { motor_type: 'unknown', transport: 'unknown' }, {}, null, { motor_type: '' },
    { motor_type: 'cubemars', transport: 'can' }, { transport: 'serial' },
    { motor_type: 'unknown', driver_family: 'dynamixel' },
  ];
  for (const motor of variants) assert.equal(isAcPath(motorKind(motor)), old(motor), JSON.stringify(motor));
  assert.equal(motorKind({ motor_type: 'feetech', transport: 'serial' }), 'feetech');
  assert.equal(motorKind({ motor_type: ' Feetech ' }), 'feetech');
  assert.equal(motorKind({ motor_type: 'minas' }), 'ac_servo');
  for (const motor of [{}, null, { motor_type: 'unknown' }, { motor_type: 'cubemars', transport: 'can' }]) {
    assert.equal(motorKind(motor), 'unknown', JSON.stringify(motor));
  }
  // 옛 줄(ac 만 있음)은 전과 같게 · kindKey 가 있으면 그것
  assert.equal(rowKind({ ac: true }), 'ac_servo');
  assert.equal(rowKind({ ac: false }), 'dynamixel');
  assert.equal(rowKind({}), 'ac_servo');
  assert.equal(rowKind({ ac: false, kindKey: 'feetech' }), 'feetech');
  assert.equal(rowKind({ ac: false, kindKey: 'unknown' }), 'unknown');
});

const motor = (axis, type, extra = {}) => ({ id: `m${axis}`, axis, name: `M${axis}`, motor_type: type,
  config: { controller_index: axis, profile_velocity: 100, acceleration: 200, profile_acceleration: 200, max_speed_rpm: 99999 }, ...extra });

test('모터 표 · Feetech 줄 · AC 아님 · FT · 토크 · 재부팅 없음 · AC 전용 검사 안 함', () => {
  const snap = { motion_state: { motors: [
    { controller_index: 0, motor_type: 'minas', state: 'detected', servo_on: true },
    { controller_index: 1, motor_type: 'dynamixel', state: 'detected', servo_on: true },
    { controller_index: 2, motor_type: 'feetech', state: 'detected', servo_on: true },
  ] } };
  const rows = motorRows({ motors: [
    motor(0, 'ac_servo', { profile: { driver_model: 'MINAS A6B' } }),
    motor(1, 'dynamixel', { profile: { driver_model: 'XM540-W150' } }),
    motor(2, 'feetech', { transport: 'serial', profile: { driver_model: 'STS3215' } }),
  ] }, snap);
  assert.deepEqual(rows.map((r) => [r.kindKey, r.ac, r.kind, r.servo]), [
    ['ac_servo', true, 'AC · MINAS A6B', '켜짐'],
    ['dynamixel', false, 'DXL · XM540-W150', '토크 켜짐'],
    ['feetech', false, 'FT · STS3215', '토크 켜짐'],
  ]);
  const ft = rows[2];
  assert.equal(kindSpec(ft.kindKey).power, '토크');
  assert.equal(kindSpec(ft.kindKey).reset, '', 'Feetech 재부팅 버튼 없음');
  assert.equal(kindSpec(rows[1].kindKey).reset, '재부팅');
  assert.equal(ft.absolute, '-');
  assert.equal(ft.gains, null);
  assert.equal(absoluteSummary(rows).total, 1);
  // AC 전용 칸(최대 속도 rpm)은 Feetech 에서 검사 안 함 · AC 는 그대로
  assert.deepEqual(motorProblems([motor(2, 'feetech')]).filter((p) => p.includes('최대 속도')), []);
  assert.match(motorProblems([motor(0, 'ac_servo')]).join(), /최대 속도 값은 1~6500/);
});

test('모터 표 · motor_type unknown · 칸 없음 · cubemars 줄은 전(HEAD)과 같음 · AC 이름 · 서보 글 · 앱솔루트 · 게인 · AC 검사', () => {
  const gains = { auto_tuning: 1, stiffness: 13, inertia_ratio: 100 };
  const snap = { motion_state: {
    motors: [
      { controller_index: 3, motor_type: 'unknown', transport: 'unknown', state: 'detected', servo_on: false },
      { controller_index: 4, state: 'detected', servo_on: true },
      { controller_index: 5, motor_type: 'cubemars', state: 'detected', fault: true },
    ],
    minas_absolute: { drives: [{ axis: 3, status: 'ok', gains }, { axis: 4, status: 'not_absolute' }] },
  } };
  const rows = motorRows({ motors: [
    motor(3, 'unknown', { profile: { driver_model: 'MINAS A6B' } }),
    { ...motor(4, undefined), motor_type: undefined },
    motor(5, 'cubemars'),
  ] }, snap);
  // HEAD 값 · ac = motor_type !== 'dynamixel' · kind 'AC…' · 서보 글 AC 식
  assert.deepEqual(rows.map((r) => [r.ac, r.kind, r.servo, r.absolute]), [
    [true, 'AC · MINAS A6B', '꺼짐', '정상'],
    [true, 'AC', '켜짐', '앱솔루트 아님'],
    [true, 'AC', '알람', '-'],
  ]);
  assert.deepEqual(rows[0].gains, gains);
  assert.deepEqual(absoluteSummary(rows), { total: 3, ok: 1, allOk: false, needsSetup: 1, waiting: 0, unread: 1 });
  // 버튼 · 서보 켜기/끄기 · 오류 초기화 · 통로 ac-servo (AC 와 같음)
  for (const row of rows) {
    const spec = kindSpec(row.kindKey);
    assert.deepEqual([spec.power, spec.reset, spec.controlPath, spec.short], ['서보', '오류 초기화', '/api/motion-test/ac-servo', 'AC']);
  }
  // AC 전용 칸 검사도 전처럼
  assert.match(motorProblems([motor(3, 'unknown')]).join(), /최대 속도 값은 1~6500/);
  assert.match(motorProblems([{ ...motor(4, undefined), motor_type: undefined }]).join(), /최대 속도 값은 1~6500/);
  // 0xFFFE · 직렬 서보만 · AC 길은 전과 같은 글
  assert.equal(motorErrorText({ motor_type: 'unknown', errorcode: 0xFFFE }), '오류 65534');
});

test('모터 검색 · 「직렬 서보 검색」 하나 · 다이나믹셀 + Feetech 한 번에 · 확인 창 글', () => {
  const page = read('../static/v2/js/pages/motors.js');
  assert.match(page, /serial: \{ label: '직렬 서보', path: '\/api\/motors\/scan\/dynamixel' \}/);
  assert.doesNotMatch(page, /scan\/feetech|label: 'Feetech'|label: '다이나믹셀'/);
  assert.match(page, /`\$\{spec\.label\} 검색`/);
  assert.match(scanConfirmText('serial', {}), /^직렬 서보\(다이나믹셀 · Feetech\) 모터를 검색합니다/);
  assert.match(scanConfirmText('all', {}), /^AC 서보 · 다이나믹셀 · Feetech 모터를 검색합니다/);
  assert.match(scanConfirmText('ac', {}), /^AC 서보\(EtherCAT\) 모터를 검색합니다/);
});

test('오류 글 · 0xFFFE 설정 대기(직렬 서보) · Feetech 상태 비트 · AC 는 그대로', () => {
  assert.equal(motorErrorText({ motor_type: 'feetech', errorcode_raw: 0xFFFE, errorcode: 0xFFFE, error_text: 'Error 65534' }), '설정 대기');
  assert.equal(motorErrorText({ motor_type: 'dynamixel', errorcode: 0xFFFE }), '설정 대기');
  assert.equal(motorErrorText({ motor_type: 'minas', errorcode: 0xFFFE }), '오류 65534', 'AC 는 전과 같음');
  assert.equal(motorErrorText({ motor_type: 'minas', error_text: 'Err16.0' }), 'Err16.0');
  assert.equal(motorErrorText({ motor_type: 'feetech', errorcode: 0x24 }), '오류 온도 · 과부하');
  assert.equal(motorErrorText({ motor_type: 'feetech', errorcode: 0x24, error_text: 'Overload' }), 'Overload', '서버 글 우선');
  assert.equal(motorErrorText({ motor_type: 'feetech', error_text: 'Communication unavailable', errorcode: 0 }), '통신 없음');
  assert.equal(motorErrorText({ motor_type: 'feetech', errorcode: 0 }), '');
});

test('조인트 매핑 · Feetech 고유 이름 feetech:port:<포트>:id:<n> · 위치 글 FT · AC · DXL 은 그대로', () => {
  const ft = { motor_type: 'feetech', serial_port: '/dev/serial/by-id/usb-FTDI_U2D2-if00', bus_id: 7 };
  assert.equal(motorRefFor(ft), 'feetech:port:%2Fdev%2Fserial%2Fby-id%2Fusb-FTDI_U2D2-if00:id:7');
  assert.equal(motorWhere(ft), 'FT · /dev/serial/by-id/usb-FTDI_U2D2-if00 · ID 7');
  assert.equal(motorRefFor({ motor_type: 'feetech', bus_id: 7 }), '', '포트 없으면 이름 없음');
  assert.equal(motorRefFor({ motor_type: 'dynamixel', bus_id: 3, serial_port: '/dev/ttyUSB0' }), 'dynamixel:port:%2Fdev%2FttyUSB0:id:3');
  assert.equal(motorWhere({ motor_type: 'dynamixel', serial_port: '/dev/ttyUSB0', bus_id: 5 }), 'DXL · /dev/ttyUSB0 · ID 5');
  // 런타임 AC(minas) · 이름은 전처럼 만들지 않음 · 위치 글은 AC
  assert.equal(motorRefFor({ motor_type: 'minas', slave_position: 1 }), '');
  assert.equal(motorWhere({ motor_type: 'minas', slave_position: 1 }), 'AC · 슬레이브 1');
  // 모르는 종류 · 칸 없음 · 전처럼 AC 위치 글
  assert.equal(motorWhere({ motor_type: 'unknown', slave_position: 2 }), 'AC · 슬레이브 2');
  assert.equal(motorWhere({ slave_position: 0, alias: 7 }), 'AC · 슬레이브 0 · alias 7');
  assert.equal(motorWhere({ motor_type: 'cubemars' }), 'AC');
  assert.equal(motorRefFor({ motor_type: 'unknown', slave_position: 2 }), '');
});

test('공연 축 표 · 종류 짧은 이름 · FT · 모르는 종류 · 모터 없는 줄은 전처럼 AC', () => {
  const snap = { motion_state: { motors: [
    { controller_index: 0, motor_type: 'minas' }, { controller_index: 1, motor_type: 'dynamixel' }, { controller_index: 2, motor_type: 'feetech' },
    { controller_index: 3, motor_type: 'unknown' },
  ] } };
  const mapping = { mappings: [
    { motion_id: 'a', motor_axis: 0 }, { motion_id: 'b', motor_axis: 1 }, { motion_id: 'c', motor_axis: 2 },
    { motion_id: 'd', motor_axis: 3 }, { motion_id: 'e', motor_axis: 9 },
  ] };
  assert.deepEqual(axisRows(snap, mapping).map((r) => r.motorType), ['AC', 'DXL', 'FT', 'AC', 'AC']);
});

test('수동 조작 · Feetech 은 서보 검사 없음 · 오류면 재부팅 대신 토크 · 모르는 종류는 전처럼 AC 검사', () => {
  const manual = { run_mode: 'manual' };
  const item = { axis: 2, kindKey: 'feetech', ac: false, detected: true, fault: false, servoOn: false, row: { motion_id: 'A' } };
  assert.equal(manualBlocker({ snap: {}, sched: manual }, item), null);
  const fault = manualBlocker({ snap: {}, sched: manual }, { ...item, fault: true });
  assert.equal(fault.fix, undefined, '재부팅 버튼 없음');
  assert.match(fault.text, /토크를 껐다 켜세요/);
  // 모르는 종류(런타임 'unknown') · 전처럼 AC · 서보 꺼짐이면 서보 켜기 · 알람이면 오류 초기화
  const unknown = { ...item, kindKey: 'unknown', ac: true };
  assert.equal(manualBlocker({ snap: {}, sched: manual }, unknown).fix, 'servo-on');
  assert.equal(manualBlocker({ snap: {}, sched: manual }, { ...unknown, fault: true }).fix, 'reset');
  assert.equal(manualBlocker({ snap: {}, sched: manual }, { ...unknown, servoOn: true }), null);
  // 다이나믹셀 · AC 는 전과 같게
  assert.equal(manualBlocker({ snap: {}, sched: manual }, { ...item, kindKey: 'dynamixel', fault: true }).fix, 'reset');
  assert.equal(manualBlocker({ snap: {}, sched: manual }, { ...item, kindKey: 'ac_servo', ac: true }).fix, 'servo-on');
  const page = read('../static/v2/js/pages/manual.js');
  assert.match(page, /kindKey: motorKind\(m\)/);
  assert.match(page, /ac: !isSerialServo\(motorKind\(m\)\)/);
  assert.doesNotMatch(page, /종류 확인 불가/);
});

test('서보 버튼 · 직렬 서보 한 통로 · 재부팅은 다이나믹셀만 · 그 밖은 전처럼 AC 통로', () => {
  const actions = read('../static/v2/js/actions.js');
  const control = actions.slice(actions.indexOf('export async function servoControl'), actions.indexOf('export async function servoAll'));
  assert.match(control, /const ac = !isSerialServo\(kind\);/);
  assert.match(control, /if \(action === 'reset' && !spec\.reset\)/);
  assert.doesNotMatch(control, /종류 확인 불가/);
  const all = actions.slice(actions.indexOf('export async function servoAll'), actions.indexOf('export function motionStop'));
  assert.match(all, /const ac = detected\.filter\(\(m\) => !isSerialServo\(rowKind\(m\)\)\);/);
  assert.match(all, /const dxl = detected\.filter\(\(m\) => isSerialServo\(rowKind\(m\)\)\);/);
  assert.match(all, /const failed = \[\];/);
});

test('이전 화면 · Feetech 은 다이나믹셀도 AC 도 아님 · 직렬 서보 통로 · 재부팅 없음', () => {
  assert.equal(runtimeIsDynamixel({ motor_type: 'feetech', transport: 'serial' }), false);
  assert.equal(runtimeIsDynamixel({ motor_type: 'feetech', motor_type_label: 'Feetech', transport_label: 'Serial' }), false);
  assert.equal(runtimeIsDynamixel({ motor_type: 'dynamixel' }), true);
  assert.equal(runtimeIsDynamixel({ transport: 'serial' }), true, '옛 판정 그대로');
  assert.equal(runtimeIsDynamixel({ motor_type: 'minas', transport: 'ethercat' }), false);
  assert.equal(normalizeMotorTypeKey('feetech', 'Feetech'), 'feetech');
  assert.equal(normalizeMotorTypeKey('dynamixel', ''), 'dynamixel');
  assert.equal(normalizeMotorTypeKey('minas', 'AC Servo'), 'ac_servo');
  assert.deepEqual(servoButtonLabels({ motor_type: 'feetech' }), { on: '토크 켜기', off: '토크 끄기', reset: '재부팅 없음' });
  assert.deepEqual(servoButtonLabels({ motor_type: 'dynamixel' }), { on: '토크 켜기', off: '토크 끄기', reset: '재부팅' });
  // 모르는 종류 · 칸 없음 · 전과 같음
  assert.deepEqual(servoButtonLabels({ motor_type: 'unknown' }), { on: '서보 켜기', off: '서보 끄기', reset: '오류 초기화' });
  assert.deepEqual(servoButtonLabels({}), { on: '서보 켜기', off: '서보 끄기', reset: '오류 초기화' });
  assert.equal(runtimeIsDynamixel({ motor_type: 'unknown', transport: 'unknown' }), false);
  assert.equal(normalizeMotorTypeKey('unknown', 'Unknown'), 'unknown');
  const ft = { motor_type: 'feetech', serial_port: '/dev/ttyUSB1', bus_id: 4 };
  assert.equal(motionMotorRef(ft), 'feetech:port:%2Fdev%2FttyUSB1:id:4');
  assert.deepEqual(motionMotorRefs(ft), ['feetech:port:%2Fdev%2FttyUSB1:id:4'], '옛 이름 없음');
  assert.equal(motionMotorIdentityLabel(ft), 'Feetech /dev/ttyUSB1 · ID 4');
  // 1 Mbps 고정 가정 없음 · 속도는 검색 결과 그대로
  assert.doesNotMatch(read('../static/js/motor_type_dynamixel.js'), /DYNAMIXEL_BAUDRATE|1000000/);
});

test('이전 화면 · 「직렬 서보 검색」 버튼 하나 · 결과 글은 다이나믹셀 · Feetech 따로', () => {
  const panel = read('../static/panels/05-panel-registration.html');
  assert.match(panel, /id="dynamixelScanButton"[^>]*>직렬 서보 검색</);
  assert.match(panel, /id="dynamixelScanResult"[\s\S]*id="feetechScanResult"/);
  assert.doesNotMatch(panel, /feetechScanButton/);
  const controller = read('../static/js/motor_config.js');
  assert.match(controller, /render: \(scan\) => \{ renderDynamixelScan\(scan\); renderFeetechScan\(scan\); \}/);
  assert.match(controller, /feetech_scan: scan\?\.feetech_scan \|\| latestScan\?\.feetech_scan/);
  assert.doesNotMatch(controller, /feetechScanButton|requestFeetechScan|scan\/feetech/);
  assert.doesNotMatch(read('../static/js/api.js'), /scan\/feetech/);
});
