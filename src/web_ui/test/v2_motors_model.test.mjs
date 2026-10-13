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
  assert.deepEqual(absoluteSummary(rows), { total: 2, ok: 1, allOk: false, needsSetup: 1, waiting: 0 });
});

test('앱솔루트 · 읽기만 실패(unknown)면 「앱솔루트 설정」 을 권하지 않는다 · 다시 읽는 중 (수정 목록 110)', () => {
  const snap = { motion_state: {
    motors: [{ controller_index: 0, state: 'detected' }, { controller_index: 1, state: 'detected' }],
    minas_absolute: { drives: [{ axis: 0, status: 'unknown', problem: '확인 불가 · 드라이브 응답을 기다리며 다시 읽는 중' }, { axis: 1, status: 'ok' }] },
  } };
  const rows = motorRows({ motors: [motor(0, 'A'), motor(1, 'B')] }, snap);
  assert.equal(rows[0].absolute, '다시 읽는 중');
  assert.deepEqual(absoluteSummary(rows), { total: 2, ok: 1, allOk: false, needsSetup: 0, waiting: 1 });
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
  assert.deepEqual(motorChanges(saved, draft), ['0번 이름 A → B', '0번 운영 시간이 끝나면 서보 끄기 - → true']);
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

test('EtherCAT 주소 겹침 · 서버 저장 검사와 같은 규칙 · 저장 전에 보이게 (2026-10-12)', () => {
  const ac = (axis, alias, slave) => ({ axis, name: `M${axis}`, motor_type: 'ac_servo', identity: { ethercat_master_index: 0, ethercat_alias: alias, slave_position: slave }, config: {} });
  assert.deepEqual(motorProblems([ac(0, 0, 0), ac(1, 0, 1), ac(2, 0, 2)]), [], 'Alias 0 이어도 Slave 번호가 다르면 된다');
  assert.match(motorProblems([ac(0, 101, 0), ac(1, 101, 1)])[0], /^1번 · EtherCAT Alias 101가 0번과 같습니다/);
  assert.match(motorProblems([ac(0, 0, 0), ac(1, 0, 0)])[0], /Alias 0 · Slave 0이 0번과 같습니다 · |「전체 검색」/);
  assert.deepEqual(motorProblems([ac(0, 101, 0), ac(1, 0, 0)]), [], 'Alias 를 쓰는 드라이브와 Slave 번호로 찾는 드라이브는 겹치지 않는다');
});

test('게인 칸 · 드라이브에 저장된 값 그대로 · 자동조정 꺼짐 · 강성 다름 알림 (수정 목록 108)', async () => {
  const { gainText, gainWarnings } = await import('../static/v2/js/motors_model.js');
  const on = { auto_tuning: 1, stiffness: 13, inertia_ratio: 137, estimation_speed: 1, error: '' };
  const off = { auto_tuning: 0, stiffness: 12, inertia_ratio: 137, estimation_speed: 1, error: '' };
  assert.equal(gainText(on).text, '자동조정 1 · 강성 13 · 관성비 137 %');
  assert.equal(gainText(off).tone, 'warn');
  assert.match(gainText(on).hint, /Pr0\.04/);
  assert.equal(gainText(null).text, '-');
  const rows = [{ axis: 0, ac: true, gains: on }, { axis: 2, ac: true, gains: off }, { axis: 5, ac: false, gains: null }];
  const warnings = gainWarnings(rows);
  assert.equal(warnings.length, 2);
  assert.match(warnings[0], /자동조정 꺼짐 · 2번/);
  assert.match(warnings[1], /0번 13 · 2번 12/);
  assert.deepEqual(gainWarnings([{ axis: 0, ac: true, gains: on }]), []);
});

test('게인 쓰기 · 바뀐 칸만 · 범위 · 뜻은 마우스로 (수정 목록 108 다)', async () => {
  const { gainChanges, gainHint, GAIN_FIELDS } = await import('../static/v2/js/pages/drive_gains.js');
  const gains = { auto_tuning: 1, stiffness: 13, estimation_speed: 1 };
  assert.deepEqual(gainChanges(gains, {}), { values: {}, problems: [] });
  assert.deepEqual(gainChanges(gains, { stiffness: '13' }).values, {});            // 같은 값은 안 보냄
  assert.deepEqual(gainChanges(gains, { stiffness: '12', auto_tuning: '3' }).values, { stiffness: 12, auto_tuning: 3 });
  assert.equal(gainChanges(gains, { stiffness: '32' }).problems.length, 1);
  assert.equal(gainChanges(gains, { auto_tuning: '5' }).problems.length, 1);
  assert.ok(!GAIN_FIELDS.some((f) => f.key === 'inertia_ratio'));                  // 관성비는 자동조정이 정함
  assert.match(gainHint(GAIN_FIELDS[0], 3), /3 = 수직축/);
});

test('파라미터 (고급) · 다름 표시 · 마우스 글 (수정 목록 109 · 114)', async () => {
  const { rowFlags, rowHint } = await import('../static/v2/js/pages/drive_params.js');
  const row = { number: 'Pr5.12', index: 0x3512, subindex: 0, type: 'int16', memo: '', factory: 0, drive: 50, boot: 0,
    differs_factory: true, differs_boot: true, error: '' };
  assert.deepEqual(rowFlags(row).map((f) => f.text), ['부팅 시 적용값과 다름', '팩토리값과 다름']);
  assert.match(rowHint(row), /0x3512:0 · int16/);
  assert.match(rowHint({ ...row, memo: 'C' }), /전원 재투입/);
  assert.deepEqual(rowFlags({ ...row, differs_factory: false, differs_boot: false }), []);
});
