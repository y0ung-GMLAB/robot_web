/** 다이나믹셀 감속·기어비 입력 허용 · ±180 한 바퀴 한계 폐지 · 2026-10-04
 *
 * 런타임(`motion_run_rules._motor_target`)은 원래 모든 줄의 감속·기어비를 썼다 ·
 * 화면과 한계 환산(`mapping_motor_limits`)만 다이나믹셀을 1 로 고정해 세 곳이
 * 어긋났다 · 외부 기어를 쓰는 사례가 있어 규칙을 없앴다 (사용자 결정) ·
 * 다이나믹셀은 Extended Position(멀티턴)이라 ±180 입력 제한도 함께 없앴다.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (name) => readFileSync(new URL(`../static/${name}`, import.meta.url), 'utf8');
const mapping = read('js/motion_data.js');
const manual = read('js/motion_test.js');
const panel = read('panels/05-panel-registration.html');

test('mapping screen no longer pins dynamixel gear ratio to 1', () => {
  for (const gone of ['normalizeDynamixelGearRatios', 'mappingGearRatioValue', 'dynamixelGearFixed', '감속비를 사용하지 않으며']) {
    assert.ok(!mapping.includes(gone), `${gone} 가 남아 있다`);
  }
  const gearCell = mapping.match(/<td class="mapping-number-cell"><input[^>]*data-motion-mapping-field="gear_ratio"[^>]*><\/td>/);
  assert.ok(gearCell, 'gear_ratio 입력 칸');
  assert.doesNotMatch(gearCell[0], /disabled/);
});

test('mapping header names the column 감속·기어비 and explains external gears', () => {
  assert.match(panel, /<span class="mapping-head-label">감속·기어비<\/span>/);
  assert.match(panel, /감속기·외부 기어/);
  assert.doesNotMatch(panel, /감속비/);
});

test('manual screen uses the entered gear ratio for dynamixel too', () => {
  for (const gone of ['actionGearRatio', '다이나믹셀 고정', 'isDynamixelMotor(motor) ? 1 :', 'DYNAMIXEL_ACTION_MIN_DEG', 'DYNAMIXEL_ACTION_MAX_DEG', '-180~180도로 제한']) {
    assert.ok(!manual.includes(gone), `${gone} 가 남아 있다`);
  }
  assert.match(manual, /if \(mode === 'action'\) return gearRatioValue\(el\);/);
});
