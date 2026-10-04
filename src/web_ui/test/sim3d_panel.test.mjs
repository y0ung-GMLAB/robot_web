/** 웹 3D 표시 화면 조각 · 수정 목록 7-a */
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

test('the 3D section is a collapsed details block with every control', () => {
  assert.match(indexHtml, /<details id="sim3dSection"[^>]*>/);
  assert.doesNotMatch(indexHtml, /<details id="sim3dSection"[^>]*\bopen\b/);
  for (const id of ['sim3dStatus', 'sim3dPrepareButton', 'sim3dLoadButton', 'sim3dPlayButton',
    'sim3dSlider', 'sim3dTime', 'sim3dSpeed', 'sim3dResetViewButton', 'sim3dCanvasWrap']) {
    assert.match(indexHtml, new RegExp(`id="${id}"`), id);
  }
  assert.match(indexHtml, /href="\/static\/css\/13b-sim3d\.css"/);
});

test('three.js is a vendored copy loaded lazily, never from a CDN', () => {
  const vendor = new URL('../static/vendor/three/', import.meta.url);
  for (const name of ['three.module.js', 'OrbitControls.js', 'LICENSE']) {
    assert.ok(existsSync(new URL(name, vendor)), name);
  }
  const controls = readFileSync(new URL('OrbitControls.js', vendor), 'utf8');
  assert.match(controls, /from '\.\/three\.module\.js'/);
  assert.doesNotMatch(controls, /from 'three'/);
  const viewer = read('../static/js/sim3d.js');
  assert.match(viewer, /import\(THREE_URL\)/);
  assert.doesNotMatch(viewer, /https?:\/\/(cdn|unpkg|jsdelivr)/);
});

test('the viewer follows the selected animation and the companion toggle drives it', () => {
  const data = read('../static/js/motion_data.js');
  assert.match(data, /const sim3d = createSim3dViewer\(\{ el, getLatestState \}\);/);
  assert.match(data, /sim3d\.update\(\{ file: selectedFile, registeredFile: mujocoRegisteredFile \}\);/);
  // 「MuJoCo 같이 보기」 체크 = 웹 3D 따라가기 · 서버 뷰어 창 없음
  assert.match(data, /sim3d\.setFollow\(Boolean\(el\.motionRunMujocoToggle\?\.checked\), registered\)/);
  assert.doesNotMatch(data, /previewMotionFile\(|stopPreviewMotionFile|motionRunMujocoFps|with_mujoco/);
  assert.doesNotMatch(indexHtml, /motionRunMujocoFps|stopPreviewMotionFileButton|sim3dFollowToggle/);
  const api = read('../static/js/api.js');
  for (const route of ["'/api/preview/scene'", "'/api/preview/scene/export'", "'/api/preview/scene/data'", 'preview-frames']) {
    assert.ok(api.includes(route), route);
  }
});

test('follow mode starts on running and stops on terminal states', () => {
  const viewer = read('../static/js/sim3d.js');
  assert.match(viewer, /FOLLOW_START_STATES = new Set\(\['running'\]\)/);
  assert.match(viewer, /FOLLOW_STOP_STATES = new Set\(\['stopped', 'error', 'completed', 'idle', 'ready'\]\)/);
});
