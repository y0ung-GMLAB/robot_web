// 각도 단위 변환 · 화면 deg ↔ 서버 rad · 수정 목록 6
import assert from 'node:assert/strict';
import test from 'node:test';

import { degToRad, radToDeg } from '../static/js/format.js';

test('degrees and radians convert both ways', () => {
  assert.equal(radToDeg(Math.PI), 180);
  assert.equal(degToRad(180), Math.PI);
  assert.ok(Math.abs(radToDeg(degToRad(12.345)) - 12.345) < 1e-12);
  assert.equal(radToDeg(null), 0);   // Number(null) = 0
  assert.equal(radToDeg('x'), null);
  assert.equal(degToRad(undefined), null);
});

// 조인트 매핑 식 · 화면 원본 하나 · 수정 목록 6
import { jointToMotor, mappingAngle, motorToJoint } from '../static/js/joint_mapping.js';

test('one mapping formula in the browser · same as the server formula', () => {
  const row = {
    reference_position_deg: 1234.5, offset_deg: 2, scale: 1, gear_ratio: 150, invert: true,
    motion_lower_deg: -10, motion_upper_deg: 13,
  };
  // 모터 = 1234.5 + (10 + 2) × 1 × (−1) × 150 = −565.5
  assert.equal(jointToMotor(row, 10), -565.5);
  assert.equal(motorToJoint(row, -565.5), 10);
  // rad 로 물어도 같은 자세
  const inRad = jointToMotor(row, (10 * Math.PI) / 180, 'rad');
  assert.ok(Math.abs((inRad * 180) / Math.PI - -565.5) < 1e-9);
  // _rad 칸이 있으면 그것이 먼저 · 없으면 기본값(±180°)
  assert.equal(mappingAngle({ offset_rad: 0.5, offset_deg: 99 }, 'offset', 'rad'), 0.5);
  assert.equal(mappingAngle({}, 'motion_upper', 'deg'), 180);
  assert.equal(motorToJoint({ gear_ratio: 0 }, 1), null);
});
