/** Blender 뷰 · 애니메이션 json 값으로 노드 돌리기 · 수정 목록 98 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { blenderUsesJoints, blenderViewAllowed, jointNodeRotation, sampleJointValues } from '../static/js/sim3d_math.js';

const close = (a, b) => a.every((v, i) => Math.abs(v - b[i]) < 1e-9);

test('조인트 방식이면 어떤 애니메이션이든 · 아니면 옛 방식(60) 그대로', () => {
  const joints = { available: true, joints: { f1_neck_yaw: { node: 'f1_neck_yaw', axis: [0, 1, 0] } } };
  assert.equal(blenderUsesJoints(joints), true);
  assert.equal(blenderViewAllowed(joints, { id: 'floating1_dir_test.json' }), true);
  assert.equal(blenderViewAllowed(joints, null), false, '애니메이션을 안 골랐으면 아님');
  const old = { available: true, animations: ['floating_narration_all'] };
  assert.equal(blenderUsesJoints(old), false);
  assert.equal(blenderViewAllowed(old, { id: 'floating_narration_all.json' }), true);
  assert.equal(blenderViewAllowed(old, { id: 'floating1_dir_test.json' }), false);
  assert.equal(blenderViewAllowed({ available: false, joints: joints.joints }, { id: 'x' }), false);
});

test('그 시각 값 · 두 점 사이 선형 · 끝 밖은 끝 값', () => {
  const payload = { fps: 10, sample_count: 3, joints: { a: [0, 1, 3], b: [5, 5, 5] } };
  assert.deepEqual(sampleJointValues(payload, 0.05), { a: 0.5, b: 5 });
  assert.deepEqual(sampleJointValues(payload, 0.15), { a: 2, b: 5 });
  assert.deepEqual(sampleJointValues(payload, 99), { a: 3, b: 5 });
  assert.deepEqual(sampleJointValues(payload, -1), { a: 0, b: 5 });
  assert.deepEqual(sampleJointValues({}, 1), {});
});

test('노드 회전 = 기본 자세 × 축 회전 · json 에 없으면 기본 자세', () => {
  const identity = [0, 0, 0, 1];
  // Y 축 90° · [0, sin45, 0, cos45]
  assert.ok(close(jointNodeRotation(identity, [0, 1, 0], { yaw: Math.PI / 2 }, 'yaw'), [0, Math.SQRT1_2, 0, Math.SQRT1_2]));
  assert.ok(close(jointNodeRotation(identity, [0, 2, 0], { yaw: Math.PI / 2 }, 'yaw'), [0, Math.SQRT1_2, 0, Math.SQRT1_2]), '축 길이는 맞춘다');
  const base = [0, 0, Math.SQRT1_2, Math.SQRT1_2];
  assert.ok(close(jointNodeRotation(base, [1, 0, 0], {}, 'missing'), base), '값 없으면 기본 자세');
  // 기본 자세가 Z 90° 이면 로컬 X 축 회전 · 순서가 base × axis 인지
  const q = jointNodeRotation(base, [1, 0, 0], { p: Math.PI }, 'p');
  assert.ok(close(q, [Math.SQRT1_2, Math.SQRT1_2, 0, 0].map((v) => v * 1) ) || close(q, [-Math.SQRT1_2, -Math.SQRT1_2, 0, 0]));
});
