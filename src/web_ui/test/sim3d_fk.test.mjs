/** 브라우저 순방향 운동학 = MuJoCo · 수정 목록 7-a
 *
 * 기준값은 `fixtures/make_sim3d_fixture.py` 가 MuJoCo `mj_kinematics` 로 만든
 * `fixtures/sim3d_fk.json` · 자유·힌지·슬라이드·볼 관절 · 무작위 qpos 6벌.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  axisAngleQuat, bodyLocalPose, cameraPosition, forwardKinematics, frameIndexAt, quatMul, rotVec,
} from '../static/js/sim3d_math.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/sim3d_fk.json', import.meta.url), 'utf8'));
const { scene, cases } = fixture;

function quatClose(a, b, tol) {
  // q 와 -q 는 같은 자세
  const same = a.every((v, i) => Math.abs(v - b[i]) < tol);
  const flipped = a.every((v, i) => Math.abs(v + b[i]) < tol);
  return same || flipped;
}

test('fixture covers every joint type', () => {
  const types = new Set(scene.joints.map((j) => j.type));
  assert.deepEqual([...types].sort(), ['ball', 'free', 'hinge', 'slide']);
  assert.equal(scene.nq, 14);
  assert.ok(cases.length >= 5);
});

test('world poses match MuJoCo for every body in every case', () => {
  for (const [index, c] of cases.entries()) {
    const world = forwardKinematics(scene, c.qpos);
    for (const body of scene.bodies) {
      const got = world[body.id];
      const pos = c.xpos[body.id];
      const quat = c.xquat[body.id];
      for (let k = 0; k < 3; k += 1) {
        assert.ok(Math.abs(got.pos[k] - pos[k]) < 1e-6,
          `case ${index} · ${body.name} · pos[${k}] ${got.pos[k]} ≠ ${pos[k]}`);
      }
      assert.ok(quatClose(got.quat, quat, 1e-6), `case ${index} · ${body.name} · quat ${got.quat} ≠ ${quat}`);
    }
  }
});

test('rest pose with no qpos equals body pos/quat chain', () => {
  const world = forwardKinematics(scene, null);
  const base = scene.bodies.find((b) => b.name === 'base');
  assert.deepEqual(world[base.id].pos, base.pos);
});

test('quaternion helpers behave', () => {
  const q = axisAngleQuat([0, 0, 1], Math.PI / 2);
  const v = rotVec(q, [1, 0, 0]);
  assert.ok(Math.abs(v[0]) < 1e-12 && Math.abs(v[1] - 1) < 1e-12);
  const id = quatMul(q, [q[0], -q[1], -q[2], -q[3]]);
  assert.ok(Math.abs(id[0] - 1) < 1e-12);
  const local = bodyLocalPose({ pos: [0, 0, 0], quat: [1, 0, 0, 0] }, [], null);
  assert.deepEqual(local, { pos: [0, 0, 0], quat: [1, 0, 0, 0] });
});

test('camera sits above the lookat for a negative elevation and frames resolve by time', () => {
  const pos = cameraPosition({ lookat: [0, 0, 0.7], distance: 1.8, azimuth: 120, elevation: -15 });
  assert.ok(pos[2] > 0.7);
  assert.ok(Math.abs(Math.hypot(pos[0], pos[1], pos[2] - 0.7) - 1.8) < 1e-9);
  const times = [0, 0.02, 0.04, 0.06];
  assert.equal(frameIndexAt(times, -1), 0);
  assert.equal(frameIndexAt(times, 0.029), 1);
  assert.equal(frameIndexAt(times, 0.031), 2);
  assert.equal(frameIndexAt(times, 9), 3);
});
