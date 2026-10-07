// 수정 목록 61 · MuJoCo 뷰 재생·슬라이더·길이 표시는 애니메이션 길이(정착 3초 꼬리 제외)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { followEndSec } from '../static/js/sim3d_math.js';

test('타임라인 끝 = 애니메이션 길이 · 옛 결과(motion_sec 없음)는 전체 길이', () => {
  const source = readFileSync(new URL('../static/js/sim3d.js', import.meta.url), 'utf8');
  assert.match(source, /return frames \? followEndSec\(frames\) : 0;/);
  assert.doesNotMatch(source, /frames\.duration_sec\.toFixed/);
  assert.equal(followEndSec({ duration_sec: 23, motion_sec: 20 }), 20);
  assert.equal(followEndSec({ duration_sec: 23 }), 23);
});
