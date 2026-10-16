/** Blender 뷰 카메라 · 로봇들 정면 평균 쪽에서 (MuJoCo 뷰처럼 정면) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { rigQuatsFromJoints, sceneFrontDir } from '../static/js/sim3d_math.js';

// 실제 floating 팩 scene.glb 의 리그 회전 (glTF x, y, z, w) · 매장 배치로 로봇마다 Y 축으로 돌아 있다
const RIGS = {
  FH_Rig_1: [-0.019, -0.427, -0.021, 0.904],
  FH_Rig_2: [-0.027, -0.62, -0.036, 0.783],
  FH_Rig_3: [0.035, -0.819, 0.024, 0.572],
  FH_Rig_4: [0, -0.828, 0, 0.561],
};

function fakeScene() {
  const root = { name: 'Scene', parent: null, quaternion: { x: 0, y: 0, z: 0, w: 1 } };
  const nodes = {};
  for (const [name, [x, y, z, w]] of Object.entries(RIGS)) {
    const rig = { name, parent: root, quaternion: { x, y, z, w } };
    const k = name.slice(-1);
    const rootBone = { name: 'Root', parent: rig, quaternion: { x: 0, y: 0, z: -1, w: 0 } };
    const yaw = { name: `f${k}_neck_yaw`, parent: rootBone, quaternion: { x: 0.707, y: 0, z: 0, w: 0.707 } };
    const pitch = { name: `f${k}_neck_pitch`, parent: yaw, quaternion: { x: 0, y: 0, z: 0, w: 1 } };
    nodes[yaw.name] = yaw;
    nodes[pitch.name] = pitch;
  }
  return { root, find: (name) => nodes[name] || null };
}

test('로봇마다 맨 위 노드 하나 · 같은 로봇의 조인트 여러 개는 한 번만', () => {
  const { root, find } = fakeScene();
  const joints = {};
  for (const k of ['1', '2', '3', '4']) {
    joints[`f${k}_neck_yaw`] = { node: `f${k}_neck_yaw`, axis: [0, 0, 1] };
    joints[`f${k}_neck_pitch`] = { node: `f${k}_neck_pitch`, axis: [1, 0, 0] };
  }
  joints.missing = { node: 'not_there', axis: [0, 0, 1] };
  const quats = rigQuatsFromJoints(root, joints, find);
  assert.equal(quats.length, 4);
});

test('floating 매장 배치 · 정면 평균은 장면 −X 쪽(옛 카메라 +Z 는 얼굴을 옆에서 봄)', () => {
  const { root, find } = fakeScene();
  const joints = Object.fromEntries(['1', '2', '3', '4'].map((k) => [`f${k}_neck_yaw`, { node: `f${k}_neck_yaw` }]));
  const [x, y, z] = sceneFrontDir(rigQuatsFromJoints(root, joints, find));
  assert.equal(y, 0);
  assert.ok(Math.abs(Math.hypot(x, z) - 1) < 1e-9);
  assert.ok(x < -0.95, `정면이 −X 쪽이어야 · ${x}`);
  // 로봇마다 정면과 카메라 방향 차이 · 모두 70° 안 (옛 +Z 는 최대 ~112°)
  for (const [qx, qy, qz, qw] of Object.values(RIGS)) {
    const yaw = 2 * Math.atan2(qy, qw);
    const front = [Math.sin(yaw), Math.cos(yaw)];
    const deg = (Math.acos(front[0] * x + front[1] * z) * 180) / Math.PI;
    assert.ok(deg < 70, `${deg}`);
  }
});

test('리그를 못 찾거나 서로 지워지면 옛 방향 +Z', () => {
  assert.deepEqual(sceneFrontDir([]), [0, 0, 1]);
  assert.deepEqual(sceneFrontDir(null), [0, 0, 1]);
  const facing = [1, 0, 0, 0];                       // 정면 +Z
  const away = [0, 0, 1, 0];                         // Y 로 180° · 정면 −Z
  assert.deepEqual(sceneFrontDir([facing, away]), [0, 0, 1]);
  const [x, , z] = sceneFrontDir([facing]);
  assert.ok(Math.abs(x) < 1e-12 && Math.abs(z - 1) < 1e-12);
});
