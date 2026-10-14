/** UI v2 · 모터·드라이브 · 표 줄 · 앱솔루트 · 막는 것 · 바뀐 것 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { absoluteJobText, absoluteLine, absoluteSummary, motorChanges, motorProblems, motorRows, setField } from '../static/v2/js/motors_model.js';

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
  assert.deepEqual(absoluteSummary(rows), { total: 2, ok: 1, allOk: false, needsSetup: 1, waiting: 0, unread: 0 });
});

test('앱솔루트 · 읽기만 실패(unknown)면 「앱솔루트 설정」 을 권하지 않는다 · 다시 읽는 중 (수정 목록 110)', () => {
  const snap = { motion_state: {
    motors: [{ controller_index: 0, state: 'detected' }, { controller_index: 1, state: 'detected' }],
    minas_absolute: { drives: [{ axis: 0, status: 'unknown', problem: '확인 불가 · 드라이브 응답을 기다리며 다시 읽는 중' }, { axis: 1, status: 'ok' }] },
  } };
  const rows = motorRows({ motors: [motor(0, 'A'), motor(1, 'B')] }, snap);
  assert.equal(rows[0].absolute, '다시 읽는 중');
  assert.deepEqual(absoluteSummary(rows), { total: 2, ok: 1, allOk: false, needsSetup: 0, waiting: 1, unread: 0 });
  assert.match(absoluteLine(absoluteSummary(rows)), /1대 드라이브 응답을 기다리며 다시 읽는 중/);
});

test('앱솔루트 · 아직 못 읽은 드라이브(검색 직후 · 모터 프로그램 꺼짐)는 「필요 없음」 이라 하지 않는다 (수정 목록 120 (아))', () => {
  const rows = motorRows({ motors: [motor(0, 'A'), motor(1, 'B'), motor(2, 'C')] }, { motion_state: { motors: [] } });
  const abs = absoluteSummary(rows);
  assert.deepEqual(abs, { total: 3, ok: 0, allOk: false, needsSetup: 0, waiting: 0, unread: 3 });
  const line = absoluteLine(abs);
  assert.doesNotMatch(line, /필요 없음/);
  assert.match(line, /3대 아직 못 읽음/);
  assert.match(line, /인크리멘털이면 「앱솔루트 설정」/);
  // 인크리멘털(Pr0.15 = 1)로 읽히면 설정 필요
  const incremental = motorRows({ motors: [motor(0, 'A')] }, { motion_state: { motors: [{ controller_index: 0, state: 'detected' }],
    minas_absolute: { drives: [{ axis: 0, status: 'not_absolute', absolute_mode: 1 }] } } });
  assert.match(absoluteLine(absoluteSummary(incremental)), /1대 앱솔루트 설정 필요/);
  assert.equal(absoluteLine(absoluteSummary([])), 'AC 서보 없음');
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
  assert.deepEqual(motorChanges(saved, draft), ['0번 이름 A → B', '0번 스케줄 모드에서 운영 시간이 끝나면 서보 끄기 - → true']);
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
  assert.match(absoluteJobText({ state: 'running', resumed: true, step_index: 4, step_count: 7, step_label: '앱솔루트 방식 확인' }), /^앱솔루트 설정 이어서 하는 중 · 4\/7/);
});

test('앱솔루트 설정 이어서 하기 · 4/7 에서 실패하면 버튼 · 확인 창은 기준점 다시 캡처를 말한다 (수정 목록 134)', async () => {
  const { absoluteResumeConfirm, absoluteResumeView } = await import('../static/v2/js/motors_model.js');
  const resume = {
    from_step: 'check_mode', from_index: 4, step_count: 7, failed_step: 'check_mode', failed_index: 4, failed_label: '앱솔루트 방식 확인',
    error: '0번 모터 0x3015 읽기 실패 · Failed to upload SDO: Input/output error (11번 시도)',
    targets: [{ label: '0번 모터' }, { label: '1번 모터' }],
  };
  // 방금 실패한 그 작업 · 실패 줄에 버튼만
  const failed = absoluteResumeView({ state: 'failed', step: 'check_mode', resume });
  assert.equal(failed.label, '이어서 하기 (4/7 부터)');
  assert.equal(failed.inline, true);
  assert.match(failed.note, /0번 모터, 1번 모터 · 다회전 클리어를 아직 하지 않았습니다/);
  // 웹을 다시 켠 뒤(idle) · 따로 한 줄에 실패 이유
  const later = absoluteResumeView({ state: 'idle', resume });
  assert.equal(later.inline, false);
  assert.match(later.text, /^앱솔루트 설정 실패 · 4\/7 · 앱솔루트 방식 확인 · 0번 모터 0x3015 읽기 실패/);
  // 진행 중 · 기록 없음 → 없음
  assert.equal(absoluteResumeView({ state: 'running', resume }), null);
  assert.equal(absoluteResumeView({ state: 'failed', step: 'write_mode', resume: null }), null);
  assert.equal(absoluteResumeView({ state: 'idle', resume: { ...resume, from_step: 'power_cycle_2', from_index: 6 } }).label, '이어서 하기 (6/7 부터)');

  const box = absoluteResumeConfirm({
    from_index: 4, step_count: 7, failed_index: 4, failed_label: '앱솔루트 방식 확인', error: 'Input/output error', clear_done: false,
    steps: ['앱솔루트 방식 확인', '다회전 클리어', '드라이브 전원 껐다 켜기 2', '최종 확인'], targets: [{ label: '0번 모터' }],
  });
  assert.equal(box.title, '앱솔루트 설정 이어서 하기 (4/7 부터)');
  assert.equal(box.confirmLabel, '이어서 하기');
  assert.match(box.body, /4\. 앱솔루트 방식 확인\n5\. 다회전 클리어\n6\. 드라이브 전원 껐다 켜기 2\n7\. 최종 확인/);
  // 클리어는 4/7 에서 Err40 인 드라이브만 · 없으면 기준점 그대로 · 수정 목록 140
  assert.match(box.body, /Err40\(다회전 무효\)인 드라이브만/);
  assert.match(box.body, /Err40이 없으면 클리어하지 않고 기준점도 그대로/);
  assert.match(box.body, /전원을 한 번 더/);
  const after = absoluteResumeConfirm({ from_index: 7, step_count: 7, failed_index: 7, failed_label: '최종 확인', clear_done: true, cleared: [{ label: '0번 모터' }], steps: ['최종 확인'], targets: [] });
  assert.match(after.body, /다회전 클리어는 이미 했습니다\(0번 모터\).*기준점을 다시 지정해 저장/s);
  assert.doesNotMatch(after.body, /전원을/);
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

test('PREOP 에 멈춘 드라이브는 그 줄 통신 칸에 (수정 목록 125)', () => {
  const snap = { motion_state: { motors: [{ controller_index: 0, state: 'detected' }],
    ethercat: { stuck_slaves: [{ slave_position: 1, axis: 1, state: 'PREOP', message: '1번 드라이브가 PREOP 에 멈춤 · …' }] } } };
  const rows = motorRows({ motors: [motor(0, 'A'), motor(1, 'B')] }, snap);
  assert.equal(rows[0].comm, '연결됨');
  assert.equal(rows[1].comm, 'PREOP 에 멈춤 · 드라이브 제어 전원을 껐다 켜세요');
});

test('메일박스가 멈춘 드라이브는 그 줄 통신 칸에 (수정 목록 139 ③)', () => {
  const snap = { motion_state: { motors: [{ controller_index: 0, state: 'detected' }, { controller_index: 1, state: 'detected' }],
    minas_absolute: { state: 'ok', drives: [], stuck_mailboxes: [{ slave_position: 1, axis: 1, message: '1번 드라이브 메일박스 응답 없음 · …' }] } } };
  const rows = motorRows({ motors: [motor(0, 'A'), motor(1, 'B')] }, snap);
  assert.equal(rows[0].comm, '연결됨');
  assert.equal(rows[1].comm, '메일박스 응답 없음 · 드라이브 제어 전원을 껐다 켜세요');
});
