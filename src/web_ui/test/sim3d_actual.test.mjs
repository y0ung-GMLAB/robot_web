/** 웹 3D 실물 위치 겹쳐 보기 · 수정 목록 7-c */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { actualQpos } from '../static/js/sim3d_math.js';

const scene = {
  joints: [
    { id: 0, name: 'base_free', body: 1, type: 'free', qposadr: 0 },
    { id: 1, name: 'neck_yaw', body: 2, type: 'hinge', qposadr: 7 },
    { id: 2, name: 'neck_pitch', body: 3, type: 'hinge', qposadr: 8 },
  ],
  axes: [
    { joint: 'neck_yaw', motion_id: 'Neck_Yaw' },
    { joint: 'neck_pitch', motion_id: 'Neck_Pitch' },
  ],
};

test('actual joint angles from the motors go into their hinge slots in radians', () => {
  const { qpos, matched, missing } = actualQpos(scene, [
    { controller_index: 1, motion_id: 'Neck_Yaw', motion_actual_deg: 90 },
    { controller_index: 0, motion_id: 'Neck_Pitch', motion_actual_deg: -10 },
  ]);
  assert.equal(qpos.length, 9);
  assert.deepEqual(qpos.slice(0, 7), [0, 0, 0, 1, 0, 0, 0]);   // 자유 관절은 기본 자세
  assert.ok(Math.abs(qpos[7] - Math.PI / 2) < 1e-12);
  assert.ok(Math.abs(qpos[8] + Math.PI / 18) < 1e-12);
  assert.equal(matched, 2);
  assert.deepEqual(missing, []);
});

test('axes without a reading keep the planned pose instead of snapping to zero', () => {
  const base = [0.1, 0.2, 0.3, 1, 0, 0, 0, 0.5, 0.25];
  const { qpos, matched, missing } = actualQpos(scene, [
    { motion_id: 'Neck_Yaw', motion_actual_deg: null },
    { motion_id: 'Neck_Pitch', motion_actual_deg: 30 },
  ], base);
  assert.deepEqual(qpos.slice(0, 8), base.slice(0, 8));
  assert.ok(Math.abs(qpos[8] - Math.PI / 6) < 1e-12);
  assert.equal(matched, 1);
  assert.deepEqual(missing, ['Neck_Yaw']);
});

test('the actual-position toggle sits in the 3D toolbar and only the MuJoCo view uses it', () => {
  assert.match(indexHtml, /<input id="sim3dActualToggle" type="checkbox" disabled><span>실물 위치<\/span>/);
  const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');
  assert.ok(dom.includes("sim3dActualToggle: document.getElementById('sim3dActualToggle')"));
  const viewer = readFileSync(new URL('../static/js/sim3d.js', import.meta.url), 'utf8');
  assert.match(viewer, /el\.sim3dActualToggle\.disabled = view === 'blender' \|\| !ready;/);
  assert.match(viewer, /const \{ qpos, matched, missing \} = actualQpos\(sceneJson, motors, shownQpos\);/);
});
