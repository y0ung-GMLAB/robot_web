/** 수동 조작 · 모터를 안 골랐으면 아무 모터도 움직이지 않는다 · 2026-10-02
 *
 * 사용자 보고 · 「동작 명령에서 모터 선택을 안 해도 1번 모터가 기본으로 움직인다」
 * 원인 셋 · Number(null) === 0 (다이얼) · Number('') === 0 (「모터 선택」 빈 칸) ·
 * 모터 관리 표의 ON/OFF 가 수동 조작의 선택을 몰래 바꿈.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const motionTest = readFileSync(new URL('../static/js/motion_test.js', import.meta.url), 'utf8');
const dial = readFileSync(new URL('../static/js/jog_dial.js', import.meta.url), 'utf8');

test('the blank 「모터 선택」 option clears the selection instead of picking motor 0', () => {
  assert.match(motionTest, /const blank = axis === null \|\| axis === undefined \|\| String\(axis\)\.trim\(\) === '';/);
  assert.match(motionTest, /const nextAxis = blank \? null : numericValue\(axis, null\);/);
});

test('the dial treats no selection as no motor', () => {
  assert.match(dial, /if \(raw === null \|\| raw === undefined \|\| String\(raw\)\.trim\(\) === ''\) return null;/);
});

test('servo ON/OFF from 모터 관리 does not change the manual-control selection', () => {
  const start = motionTest.indexOf('controlAcServo: async (action, axis) => {');
  const body = motionTest.slice(start, motionTest.indexOf('},', start));
  assert.doesNotMatch(body, /selectAxis\(/);
  assert.match(body, /sendAcServoControl\(action, 'selected', numericValue\(axis, null\)\)/);
  assert.match(motionTest, /const axis = axisOverride \?\? selectedAxis;/);
});
