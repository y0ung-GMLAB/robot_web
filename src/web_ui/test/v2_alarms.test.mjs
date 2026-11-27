/** UI v2 · 알람 정책 · 바뀐 것 판정 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { isDirtyOverrides } from '../static/v2/js/pages/alarms.js';

test('초안과 저장값이 다르면 변경 · 기본(0·없음)은 같은 것', () => {
  assert.equal(isDirtyOverrides({}, {}), false);
  assert.equal(isDirtyOverrides({ 16: 1 }, {}), true);
  assert.equal(isDirtyOverrides({}, { 16: 1 }), true);
  assert.equal(isDirtyOverrides({ 16: 1 }, { 16: '1' }), false);
  assert.equal(isDirtyOverrides(null, undefined), false);
});
