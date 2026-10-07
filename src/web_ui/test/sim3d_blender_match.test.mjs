// 수정 목록 60 · Blender 뷰는 glb 가 담은 애니메이션에서만 · 이름 없는 옛 팩은 안 보임
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { blenderHoldsAnimation } from '../static/js/sim3d_math.js';

const info = { available: true, animations: ['floating_narration_all'] };

test('파일 이름(확장자 뺌)이 목록에 있으면 켜짐 · 대소문자 무시', () => {
  assert.equal(blenderHoldsAnimation(info, { id: 'floating_narration_all.json' }), true);
  assert.equal(blenderHoldsAnimation(info, { id: 'x', filename: 'Floating_Narration_All.json' }), true);
});

test('다른 애니메이션 · 이름 없는 팩 · 장면 없음 · 파일 없음은 꺼짐', () => {
  assert.equal(blenderHoldsAnimation(info, { id: 'wave.json' }), false);
  assert.equal(blenderHoldsAnimation({ available: true }, { id: 'floating_narration_all.json' }), false);
  assert.equal(blenderHoldsAnimation({ available: false, animations: ['a'] }, { id: 'a.json' }), false);
  assert.equal(blenderHoldsAnimation(info, null), false);
});

test('화면 · 체크는 맞을 때만 켜고 · 안 맞으면 MuJoCo 로 돌아간다', () => {
  const source = readFileSync(new URL('../static/js/sim3d.js', import.meta.url), 'utf8');
  assert.match(source, /view = next === 'blender' && blenderAllowed\(\) \? 'blender' : 'mujoco';/);
  assert.match(source, /el\.sim3dBlenderToggle\.disabled = blenderLoading \|\| !allowed;/);
  assert.match(source, /if \(view === 'blender' && !blenderAllowed\(\)\) \{\s*setView\('mujoco'\);/);
});
