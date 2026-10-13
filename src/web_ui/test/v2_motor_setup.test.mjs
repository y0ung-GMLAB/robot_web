/** UI v2 · 모터 설정 · ① 모터·드라이브 · ② 조인트 매핑 을 한 페이지 두 구획으로 (사용자 결정 2026-10-12) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { pendingText, setupStatus } from '../static/v2/js/pages/motor_setup.js';
import { motorWhere } from '../static/v2/js/mapping_model.js';
import { absoluteJobText } from '../static/v2/js/motors_model.js';
import { NAV, routeLabel } from '../static/v2/js/shell.js';

test('메뉴엔 「모터 설정」 하나 · 조인트 매핑 주소도 그 메뉴로 열린다', () => {
  const ids = NAV.flatMap((group) => group.items.map(([id]) => id));
  assert.ok(ids.includes('maintain-motors'));
  assert.ok(!ids.includes('mapping'));
  assert.equal(routeLabel('maintain-motors'), '모터 설정');
  assert.equal(routeLabel('mapping'), '모터 설정');
});

test('구획 상태 · 모터 연결 수 · 범위 미확인 · 장비 적용', () => {
  const snap = {
    motion_state: { motors: [{ state: 'detected' }, { state: 'missing' }] },
    mapping_range_blocker: 'Neck_Pitch',
    project_scope: { runtime_matches_selected: true, motor_config_applied: true },
  };
  const status = setupStatus(snap);
  assert.deepEqual(status.motors, { done: false, note: '1/2대 연결' });
  assert.deepEqual(status.mapping, { done: false, note: '범위 미확인' });
  assert.deepEqual(status.apply, ['장비에 적용됨', 'ok']);
  assert.equal(setupStatus(snap, { dirty: true }).apply[1], 'warn');
  assert.deepEqual(setupStatus({}).apply, ['장비에 적용 필요', 'warn']);
});

test('저장 칸 한 줄 · 두 구획 변경을 같이 센다', () => {
  assert.equal(pendingText([], []), '저장됨');
  assert.equal(pendingText(['0번 이름 A → B'], []), '저장하지 않은 변경 · 모터 1개 · 0번 이름 A → B');
  assert.equal(pendingText(['a', 'b'], ['c', 'd']), '저장하지 않은 변경 · 모터 2개 · 조인트 매핑 2개 · a · b · c 외 1개');
});

test('모터 고르기 목록 · 어느 드라이브인지 · 슬레이브 번호 · alias · 다이나믹셀 포트·ID', () => {
  assert.equal(motorWhere({ motor_type: 'ac_servo', ethercat_master_index: 0, slave_position: 3, alias: 103 }), 'AC · 슬레이브 3 · alias 103');
  assert.equal(motorWhere({ motor_type: 'ac_servo', slave_position: 0, alias: 0 }), 'AC · 슬레이브 0');
  assert.equal(motorWhere({ motor_type: 'ac_servo', ethercat_master_index: 1, slave_position: 2 }), 'AC · 마스터 1 · 슬레이브 2');
  assert.equal(motorWhere({ motor_type: 'dynamixel', serial_port: '/dev/ttyUSB0', bus_id: 5 }), 'DXL · /dev/ttyUSB0 · ID 5');
});

test('앱솔루트 작업 글 · 머리말과 같은 말은 한 번만(「완료 · 완료」 없음)', () => {
  assert.equal(absoluteJobText({ state: 'done', message: '완료 · 위치 숫자가 바뀌어 기준점을 다시 캡처해야 합니다' }),
    '앱솔루트 설정 완료 · 위치 숫자가 바뀌어 기준점을 다시 캡처해야 합니다');
  assert.equal(absoluteJobText({ state: 'done', message: '앱솔루트 설정 완료 · 위치 숫자가 바뀌어 기준점을 다시 캡처해야 합니다' }),
    '앱솔루트 설정 완료 · 위치 숫자가 바뀌어 기준점을 다시 캡처해야 합니다');
  assert.equal(absoluteJobText({ state: 'running', step_count: 4, step_index: 2, step_label: '드라이브 재시작' }), '앱솔루트 설정 중 · 2/4 · 드라이브 재시작');
});

test('모터·드라이브 · 모든 서보 켜기·끄기 (사용자 2026-10-12) · AC 는 서버 scope all 한 번 · 끄기는 확인 창', async () => {
  const { readFileSync } = await import('node:fs');
  const page = readFileSync(new URL('../static/v2/js/pages/motors.js', import.meta.url), 'utf8');
  const actions = readFileSync(new URL('../static/v2/js/actions.js', import.meta.url), 'utf8');
  assert.match(page, /'모든 서보 켜기'/);
  assert.match(page, /'모든 서보 끄기'/);
  assert.match(page, /servoAllBar\(rows, state, changed\)/);
  const body = actions.slice(actions.indexOf('export async function servoAll'), actions.indexOf('export function motionStop'));
  assert.match(body, /scope: 'all'/);
  assert.match(body, /confirmBox\(/);
  assert.match(body, /dynamixel\/control/);
});

test('드라이브 공통 값 · 바뀐 칸 · 범위 검사 (수정 목록 114)', async () => {
  const { minasBaseChanges, minasBaseProblems } = await import('../static/v2/js/pages/minas_base.js');
  const rows = [
    { key: '0x3437:0', label: 'Pr4.37', unit: 'ms', min: 0, max: 10000, default: 150, local: null, value: 150 },
    { key: '0x3512:0', label: 'Pr5.12', unit: '%', min: 0, max: 115, default: 0, local: 50, value: 50 },
  ];
  assert.deepEqual(minasBaseChanges(rows, {}), {});
  assert.deepEqual(minasBaseChanges(rows, { '0x3437:0': '200', '0x3512:0': '50' }), { '0x3437:0': '200' });
  assert.deepEqual(minasBaseChanges(rows, { '0x3512:0': '' }), { '0x3512:0': '' });   // 비우면 기본값으로
  assert.deepEqual(minasBaseProblems(rows, { '0x3512:0': '116' }).length, 1);
  assert.deepEqual(minasBaseProblems(rows, { '0x3437:0': '1.5' }).length, 1);
  assert.deepEqual(minasBaseProblems(rows, { '0x3437:0': '' }), []);
});

test('드라이브 공통 값 · 잠금 해제 확인 뒤에만 고침 · 모터 설정 ① 에 붙음', async () => {
  const { readFileSync } = await import('node:fs');
  const card = readFileSync(new URL('../static/v2/js/pages/minas_base.js', import.meta.url), 'utf8');
  const page = readFileSync(new URL('../static/v2/js/pages/motors.js', import.meta.url), 'utf8');
  assert.match(card, /'잠금 해제'/);
  assert.match(card, /confirmBox\(/);
  assert.match(card, /ui\.unlocked\s*\n?\s*\? h\('input'/);
  assert.match(page, /minasBaseCard\(changed/);
});
