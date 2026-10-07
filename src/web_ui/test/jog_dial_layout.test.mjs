/** 다이얼 「동작 취소」 자리 고정 · 수정 목록 53 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const css = readFileSync(new URL('../static/css/14-redesign.css', import.meta.url), 'utf8');

test('남은 이동 글자 칸은 폭이 고정되어 옆 버튼이 움직이지 않는다', () => {
  const rule = css.match(/\.jog-dial-pending \{([^}]*)\}/);
  assert.ok(rule, '.jog-dial-pending 규칙이 없다');
  // 글자에 따라 폭이 변하지 않는다(기준 19ch · 늘어나지 않음 · 좁으면 줄어듦) · 넘치면 말줄임
  assert.match(rule[1], /flex:\s*0 1 19ch/);
  assert.match(rule[1], /min-width:\s*0/);
  assert.match(rule[1], /white-space:\s*nowrap/);
  assert.match(rule[1], /text-overflow:\s*ellipsis/);
});

test('오른쪽 칸은 좁은 창에서 줄어든다 · 「이동」·「+ limit」 이 패널 밖으로 잘리지 않게', () => {
  const side = css.match(/\.jog-dial-side \{([^}]*)\}/);
  assert.match(side[1], /min-width:\s*0;/);
});
