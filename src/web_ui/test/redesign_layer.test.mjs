/** 리디자인 레이어 계약 · 2026-10-02
 *
 * 01~13 조각 위에 14-redesign 이 **마지막으로** 실려 전체 모양을 정한다 ·
 * 순서가 앞으로 밀리면 옛 조각의 밝은 하드코딩이 다시 이겨 화면 곳곳에
 * 흰 상자 + 밝은 글자(안 보이는 글자)가 돌아온다 · 실제로 그랬다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const index = readFileSync(new URL('../static/index.html', import.meta.url), 'utf8');
const layer = readFileSync(new URL('../static/css/14-redesign.css', import.meta.url), 'utf8');
const motionData = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');

test('the redesign layer is linked last', () => {
  const links = [...index.matchAll(/href="\/static\/css\/([0-9a-z-]+\.css)"/g)].map((m) => m[1]);
  assert.equal(links.at(-1), '14-redesign.css');
});

test('core tokens are redefined dark in one place', () => {
  for (const token of ['--bg', '--panel', '--panel-2', '--ink', '--muted', '--line', '--blue', '--green', '--yellow', '--red']) {
    assert.match(layer, new RegExp(`${token}:\\s*#`), `${token} 가 없다`);
  }
  assert.match(layer, /color-scheme: dark/);
});

test('charts read their colors from the theme, not hard-coded white', () => {
  assert.match(motionData, /function chartTheme\(\)/);
  assert.doesNotMatch(motionData, /fillStyle = '#ffffff'/);
  assert.match(motionData, /CHART_SERIES_COLORS/);
});

test('!important is reserved for surfaces, not layout', () => {
  // 표면(background·border-color·입력 색)만 · 배치(display/position/width)에 쓰면 구조가 깨진다
  const offenders = [...layer.matchAll(/(display|position|width|height|grid-template[\w-]*|flex[\w-]*)\s*:[^;]*!important/g)];
  assert.deepEqual(offenders.map((m) => m[0]), []);
});
