/** UI v2 · 모터·드라이브 · 표 줄 · 앱솔루트 · 막는 것 · 바뀐 것 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { absoluteJobText, absoluteSummary, motorChanges, motorProblems, motorRows, setField } from '../static/v2/js/motors_model.js';

const motor = (axis, name, extra = {}) => ({ id: `m${axis}`, axis, name, motor_type: 'ac_servo', profile: { driver_model: 'MINAS A6B' },
  config: { controller_index: axis, profile_velocity: 18000, max_speed_rpm: 3000, acceleration: 180000, profile_acceleration: 180000 }, ...extra });

test('표 줄 · 설정과 지금 상태를 번호로 · 서보 · 위치 · 과부하율 · 앱솔루트', () => {
  const snap = { motion_state: {
    motors: [{ controller_index: 0, state: 'detected', servo_on: true, position_rad: Math.PI, overload_ratio_pct: 104 },
      { controller_index: 1, state: 'detected', fault: true, error_text: 'Err16.0' }],
    minas_absolute: { drives: [{ axis: 0, status: 'ok' }, { axis: 1, status: 'not_absolute', problem: 'Pr0.15=1' }] },
  } };
  const rows = motorRows({ motors: [motor(1, 'B'), motor(0, 'A'), motor(2, 'C', { deleted: true })] }, snap);
  assert.deepEqual(rows.map((r) => [r.axis, r.servo, r.position, r.load, r.absolute, r.error]), [
    [0, '켜짐', 180, 104, '정상', ''], [1, '알람', null, null, '앱솔루트 아님', 'Err16.0'],
  ]);
  assert.deepEqual(absoluteSummary(rows), { total: 2, ok: 1, allOk: false });
});

test('막는 것 · 빈 이름 · 겹친 이름 · 범위 · 프로파일 > 최대(수정 목록 37)', () => {
  assert.deepEqual(motorProblems([motor(0, 'A'), motor(1, 'B')]), []);
  assert.match(motorProblems([motor(0, '')]).join(), /이름이 비어 있습니다/);
  assert.match(motorProblems([motor(0, 'A'), motor(1, 'A')]).join(), /중복됩니다/);
  const fast = motor(0, 'A');
  setField(fast, 'profile_velocity', 20000);
  assert.match(motorProblems([fast]).join(), /최대 속도 3000 rpm \(18000 deg\/s\)/);
  const rpm = motor(0, 'A');
  setField(rpm, 'max_speed_rpm', 7000);
  assert.match(motorProblems([rpm]).join(), /1~6500/);
  const dxl = { ...motor(0, 'A'), motor_type: 'dynamixel' };
  setField(dxl, 'max_speed_rpm', 99999);
  assert.deepEqual(motorProblems([dxl]).filter((p) => p.includes('rpm')), [], 'DXL 은 rpm 칸 없음');
});

test('바뀐 것 · 이름 · 설정 칸 · 체크', () => {
  const saved = [motor(0, 'A')];
  const draft = [{ ...motor(0, 'B'), config: { ...motor(0, 'B').config, schedule_end_servo_off: true } }];
  assert.deepEqual(motorChanges(saved, draft), ['0번 이름 A → B', '0번 운영 종료 시 서보 끄기 - → true']);
  assert.deepEqual(motorChanges(saved, [motor(0, 'A')]), []);
  // 검색 제안 · 뺌 · 더함 · 번호 (수정 목록 100)
  const two = [motor(0, 'A'), motor(1, 'B')];
  const proposal = [motor(0, 'A'), { ...motor(2, 'C'), id: 'm2', axis: 1 }];
  assert.deepEqual(motorChanges(two, proposal), ['1번 B 삭제', '1번 C 추가']);
  assert.deepEqual(motorChanges(two, [{ ...motor(1, 'B'), axis: 0 }]), ['0번 A 삭제', 'B 번호 1 → 0']);
});

test('앱솔루트 설정 일 한 줄', () => {
  assert.equal(absoluteJobText({ state: 'idle' }), '');
  assert.equal(absoluteJobText({ state: 'running', step_index: 3, step_count: 7, step_label: '전원 껐다 켜기 1' }), '앱솔루트 설정 중 · 3/7 · 전원 껐다 켜기 1');
});
