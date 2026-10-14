import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

import { mappingRangeConfirmed } from '../static/js/joint_mapping.js';
import { motionHeaderConditionCells } from '../static/js/header_conditions.js';
import { buildGeneratedMotionAxisRows } from '../static/js/motion_data.js';

/**
 * 조인트 범위 확인 · 수정 목록 97
 *
 * 자동 생성 줄의 −180 ~ 180° 는 기계 범위가 아니다 · 사람이 범위를 넣거나
 * 「범위 확인」 을 체크하기 전에는 재생·초기 이동을 막는다(판정은 서버) ·
 * 화면은 칸·빨간 테두리·상단 칸으로 알린다.
 */

test('화면 판정이 서버(`joint_mapping.range_confirmed`)와 같다', () => {
  assert.equal(mappingRangeConfirmed({ range_confirmed: true }), true);
  assert.equal(mappingRangeConfirmed({ range_confirmed: false, motion_lower_deg: -10, motion_upper_deg: 13 }), false);
  // 칸이 없는 옛 파일 · 기본값 그대로면 미확인 · 다른 값이면 확인
  assert.equal(mappingRangeConfirmed({ motion_lower_deg: -180, motion_upper_deg: 180 }), false);
  assert.equal(mappingRangeConfirmed({}), false);
  assert.equal(mappingRangeConfirmed({ motion_lower_deg: -10, motion_upper_deg: 13 }), true);
  assert.equal(mappingRangeConfirmed({ motion_lower_rad: -Math.PI, motion_upper_rad: Math.PI }), false);
});

test('자동 생성 새 줄은 범위 미확인으로 시작한다', () => {
  const motors = [{ controller_index: 0, motor_type: 'ac_servo', ethercat_master_index: 0, alias: 0, slave_position: 0 }];

  const [row] = buildGeneratedMotionAxisRows(motors, []);

  assert.equal(row.range_confirmed, false);
  assert.equal(mappingRangeConfirmed(row), false);
});

test('자동 생성이 지켜 둔 줄은 확인 표시도 그대로', () => {
  const motors = [{ controller_index: 0, motor_type: 'ac_servo', ethercat_master_index: 0, alias: 0, slave_position: 0 }];
  const previous = [{
    motion_id: 'Neck_Yaw', enabled: true, motor_ref: '', motor_axis: 0,
    motion_lower_deg: -15, motion_upper_deg: 15, range_confirmed: true,
  }];

  const [row] = buildGeneratedMotionAxisRows(motors, previous);

  assert.equal(row.range_confirmed, true);
});

test('범위 미확인이면 상단에 빨간 칸 · 누르면 모터 관리(조인트 매핑)', () => {
  const cells = motionHeaderConditionCells({
    enabled: true, joined: true, inWindow: true,
    rangeProblem: '조인트 범위 미확인 · Neck_Pitch · ...',
  });
  const range = cells.find((cell) => cell.key === 'range');

  assert.equal(range.text, '범위 미확인');
  assert.equal(range.bad, true);
  assert.equal(range.action, 'config');
  assert.match(range.title, /Neck_Pitch/);
  // 상태를 아직 몰라도 붙는다
  assert.ok(
    motionHeaderConditionCells({ enabled: null, joined: null, inWindow: null, rangeProblem: 'x' })
      .some((cell) => cell.key === 'range'),
  );
  assert.ok(!motionHeaderConditionCells({ enabled: true, joined: true, inWindow: true }).some((cell) => cell.key === 'range'));
});

test('표에 「범위 확인」 칸이 있고 상단 칸은 서버 값을 그대로 받는다', () => {
  const panel = readFileSync(new URL('../static/panels/05-panel-registration.html', import.meta.url), 'utf8');
  const source = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
  const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');

  assert.match(panel, /mapping-head-label">범위 확인</);
  assert.match(source, /data-motion-mapping-field="range_confirmed"/);
  assert.match(main, /rangeProblem: String\(payload\?\.mapping_range_blocker \|\| ''\)/);
});
