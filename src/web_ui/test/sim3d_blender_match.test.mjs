// 수정 목록 98 · 159 · Blender 뷰는 json 값 방식(joints · derived) 팩에서만 · glb 에 구운 클립(옛 60)은 지움
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { blenderUsesJoints, blenderViewAllowed } from '../static/js/sim3d_math.js';

const file = { id: 'wave.json' };

test('joints 또는 derived 가 있으면 어떤 애니메이션이든 켜짐', () => {
  assert.equal(blenderViewAllowed({ available: true, joints: { a: { node: 'a', axis: [1, 0, 0] } } }, file), true);
  assert.equal(blenderViewAllowed({ available: true, joints: {}, derived: true }, file), true);
  assert.equal(blenderUsesJoints({ available: true, derived: true }), true);
});

test('옛 animations 만 있는 팩 · 장면 없음 · 파일 없음은 꺼짐', () => {
  assert.equal(blenderViewAllowed({ available: true, animations: ['wave'] }, file), false);
  assert.equal(blenderViewAllowed({ available: true, joints: {}, derived: false }, file), false);
  assert.equal(blenderViewAllowed({ available: false, derived: true }, file), false);
  assert.equal(blenderViewAllowed({ available: true, derived: true }, null), false);
});

test('화면 · 체크는 맞을 때만 켜고 · 안 맞으면 MuJoCo 로 돌아간다 · 클립 재생 코드 없음', () => {
  const source = readFileSync(new URL('../static/js/sim3d.js', import.meta.url), 'utf8');
  assert.match(source, /view = next === 'blender' && blenderAllowed\(\) \? 'blender' : 'mujoco';/);
  assert.match(source, /el\.sim3dBlenderToggle\.disabled = blenderLoading \|\| !allowed;/);
  assert.match(source, /if \(view === 'blender' && !blenderAllowed\(\)\) \{\s*setView\('mujoco'\);/);
  for (const name of ['../static/js/sim3d.js', '../static/v2/js/viewer3d.js']) {
    const text = readFileSync(new URL(name, import.meta.url), 'utf8');
    assert.doesNotMatch(text, /AnimationMixer|clipAction/, name);
  }
});
