/** UI v2 · 조인트 매핑 · rad↔deg · 막는 것 · 식 · 바뀐 것 · 모터 고유 이름 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  changeSummary, draftProblems, draftToRow, isRevisionConflict, jointToMotor, motorForRow, motorRefFor, newRow, previewRow, rowToDraft,
} from '../static/v2/js/mapping_model.js';

const R = Math.PI / 180;
const serverRow = {
  motion_id: 'Neck_Pitch', enabled: true, motor_ref: 'ac_servo:master:0:alias:100', motor_axis: 0, gear_ratio: 150, invert: false,
  offset_rad: 0, scale: 1, reference_position_rad: 30 * R, reference_enabled: true, motion_lower_rad: -10 * R, motion_upper_rad: 13 * R,
  initial_mode: 'first_frame', initial_motion_position_rad: 0, initial_move_time_sec: 5, max_velocity_rad_s: 9 * R,
};

test('rad → deg → rad · 같은 값으로 돌아온다 · 빈 최대 속도·가속은 칸을 뺀다', () => {
  const draft = rowToDraft(serverRow);
  assert.equal(draft.motion_lower_deg, -10);
  assert.equal(draft.reference_position_deg, 30);
  assert.equal(draft.max_velocity_deg_s, 9);
  assert.equal(draft.max_acceleration_deg_s2, null);
  const back = draftToRow(draft);
  assert.ok(Math.abs(back.motion_upper_rad - 13 * R) < 1e-12);
  assert.ok(Math.abs(back.max_velocity_rad_s - 9 * R) < 1e-12);
  assert.equal('max_acceleration_rad_s2' in back, false);
  assert.equal(back.scale, 1, 'scale · offset 은 화면에 없어도 그대로');
  assert.equal(draftToRow({ ...draft, max_velocity_deg_s: 0 }).max_velocity_rad_s, undefined, '0 은 검사 안 함');
  assert.equal(draftToRow({ ...draft, reference_enabled: false }).reference_position_rad, 0);
});

test('막는 것 · 빈 이름(줄 번호) · 겹친 이름 · 같은 모터 · 모터 없음 · 범위 거꾸로 · 감속비 0', () => {
  const a = rowToDraft(serverRow);
  assert.deepEqual(draftProblems([a]), []);
  assert.match(draftProblems([a, { ...newRow(1, ''), enabled: true }])[0], /2번 줄 · 조인트 이름이 비어 있습니다 \(1번 모터\)/);
  assert.match(draftProblems([a, { ...a }]).join(), /중복됩니다/);
  assert.match(draftProblems([a, { ...a, motion_id: 'B' }]).join(), /같은 모터/);
  assert.match(draftProblems([{ ...a, motor_ref: '', motor_axis: null }]).join(), /모터가 지정되지 않았습니다/);
  assert.equal(draftProblems([{ ...a, motor_ref: '', motor_axis: null, enabled: false }]).length, 0, '안 쓰는 줄은 모터 없어도 됨');
  assert.match(draftProblems([{ ...a, motion_lower_deg: 20 }]).join(), /최소가 최대보다/);
  assert.match(draftProblems([{ ...a, gear_ratio: 0 }]).join(), /0보다 커야/);
  assert.deepEqual(draftProblems([]), ['조인트가 하나도 없습니다']);
});

test('식 · 모터 = 기준점 + (조인트 + offset) × scale × 방향 × 감속비', () => {
  const d = rowToDraft(serverRow);
  assert.equal(jointToMotor(d, 1), 30 + 150);
  assert.equal(jointToMotor({ ...d, invert: true }, 1), 30 - 150);
  const view = previewRow({ ...d, invert: true });
  assert.equal(view.perDegree, -150);
  assert.deepEqual([view.motorMin, view.motorMax], [30 - 13 * 150, 30 + 10 * 150]);
});

test('바뀐 것 · 칸 · 더함 · 뺌', () => {
  const a = { ...rowToDraft(serverRow), _key: 'k1' };
  const b = { ...rowToDraft({ ...serverRow, motion_id: 'Yaw', motor_axis: 1 }), _key: 'k2' };
  assert.deepEqual(changeSummary([a, b], [a, b]), []);
  assert.deepEqual(changeSummary([a, b], [{ ...a, gear_ratio: 120 }]), ['Neck_Pitch 감속·기어비 150 → 120', 'Yaw 삭제']);
  assert.deepEqual(changeSummary([a], [a, { ...newRow(2, 'New'), _key: 'k9' }]), ['New 추가']);
});

test('모터 고유 이름 · alias 우선 · 없으면 slave · DXL 포트 · ref 로 먼저 찾고 번호로', () => {
  assert.equal(motorRefFor({ motor_type: 'ac_servo', ethercat_master_index: 0, alias: 103, slave_position: 2 }), 'ac_servo:master:0:alias:103');
  assert.equal(motorRefFor({ motor_type: 'ac_servo', ethercat_master_index: 0, alias: 0, slave_position: 2 }), 'ac_servo:master:0:slave:2');
  assert.equal(motorRefFor({ motor_type: 'dynamixel', bus_id: 3, serial_port: '/dev/ttyUSB0' }), 'dynamixel:port:%2Fdev%2FttyUSB0:id:3');
  const motors = [{ axis: 0, ref: 'ac_servo:master:0:alias:101' }, { axis: 1, ref: 'ac_servo:master:0:alias:100' }];
  assert.equal(motorForRow({ motor_ref: 'AC_SERVO:master:0:alias:100', motor_axis: 0 }, motors).axis, 1, '번호가 바뀌어도 같은 드라이브');
  assert.equal(motorForRow({ motor_ref: '', motor_axis: 0 }, motors).axis, 0);
  assert.equal(motorForRow({ motor_ref: '', motor_axis: 7 }, motors), null);
});

test('충돌 문구', () => {
  assert.equal(isRevisionConflict('motion mapping command failed: 조인트 매핑이 화면을 불러온 뒤 변경됐습니다 · 다시'), true);
  assert.equal(isRevisionConflict('재생 중에는 바꿀 수 없습니다'), false);
});

test('범위 확인 · 칸이 있으면 그 값 · 옛 파일은 ±180 이면 미확인 · 숫자만 고쳐서는 안 바뀐다 (수정 목록 97 · 사용자 2026-10-13)', async () => {
  const { rangeConfirmed, unconfirmedRows } = await import('../static/v2/js/mapping_model.js');
  const mappingModel = await import('../static/v2/js/mapping_model.js');
  assert.equal(mappingModel.autoConfirmRange, undefined, '저절로 체크하는 함수는 없다');
  const old = rowToDraft({ ...serverRow, range_confirmed: undefined, motion_lower_rad: -Math.PI, motion_upper_rad: Math.PI });
  assert.equal(rangeConfirmed(old), false);
  assert.equal(old.range_confirmed, false, '불러올 때 칸으로 굳힌다');
  assert.equal(rangeConfirmed(rowToDraft(serverRow)), true, '옛 파일이라도 범위를 넣었으면 확인으로');
  assert.equal(rangeConfirmed({ ...old, range_confirmed: true }), true);
  assert.equal(rangeConfirmed(rowToDraft({ ...serverRow, range_confirmed: false })), false);
  // 옛 파일 ±180 줄에 숫자만 넣어도 미확인 그대로 · 짐작은 불러올 때 한 번만
  old.motion_lower_deg = -10;
  old.motion_upper_deg = 13;
  assert.equal(rangeConfirmed(old), false);
  assert.equal(draftToRow({ ...old }).range_confirmed, false, '저장에도 미확인으로 실린다');
  const fresh = newRow(0, 'X');
  assert.equal(fresh.range_confirmed, false, '자동 생성 새 줄은 미확인');
  fresh.motion_lower_deg = -10;
  fresh.motion_upper_deg = 10;
  assert.equal(rangeConfirmed(fresh), false, '최소·최대를 둘 다 고쳐도 그대로');
  fresh.range_confirmed = true;   // 사람이 체크
  assert.deepEqual(unconfirmedRows([old, { ...old, enabled: false }, { ...old, motion_id: '' }]).length, 1, '안 쓰는 줄 · 이름 없는 줄은 빼고');
  assert.equal(draftToRow({ ...fresh }).range_confirmed, true, '저장에 실린다');
  const noField = { ...rowToDraft(serverRow) };
  delete noField.range_confirmed;
  assert.equal(draftToRow(noField).range_confirmed, true, '칸이 없어도 늘 적어 보낸다');
});

test('「범위 확인」 칸 옆 주의 · 최소·최대 입력에 저절로 체크 없음 · 수동 하한·상한 지정도 (사용자 2026-10-13)', async () => {
  const { readFile } = await import('node:fs/promises');
  const page = await readFile(new URL('../static/v2/js/pages/mapping.js', import.meta.url), 'utf8');
  const manual = await readFile(new URL('../static/v2/js/pages/manual.js', import.meta.url), 'utf8');
  assert.match(page, /RANGE_NOTE = '범위 확인 유의';/);
  assert.match(page, /RANGE_HINT = '[^']*직접 체크/, '자세한 안내는 마우스를 올리면');
  assert.doesNotMatch(page, /autoConfirmRange|range_confirmed = true/);
  assert.doesNotMatch(manual, /autoConfirmRange|range_confirmed/);
  assert.doesNotMatch(page, /입력하거나 「범위 확인」/, '숫자 입력만으로 풀린다는 안내 없음');
});
