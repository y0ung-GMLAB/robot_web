// 수정 목록 54 · 계산 실패가 「다시 계산 필요」 에 가려지지 않게 · 옛 결과가 있으면 보기는 허용
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (name) => readFileSync(new URL(`../static/js/${name}`, import.meta.url), 'utf8');

test('실패 배지에 서버 이유 · 같이 보기와 3D 보기는 failed + has_result 도 허용', () => {
  const motion = read('motion_data.js');
  assert.match(motion, /file\?\.preview\?\.message \|\| '마지막 계산이 실패했습니다'/);
  assert.match(motion, /registeredState === 'failed' && mujocoRegisteredFile\?\.preview\?\.has_result === true/);
  assert.match(read('sim3d.js'), /state === 'failed' && file\.preview\?\.has_result === true/);
});
