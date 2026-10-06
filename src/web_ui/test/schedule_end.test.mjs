// 운영 시간이 끝나면 · 기준점 주차 → 서보 OFF · 수정 목록 36 (2026-10-06)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { scheduleEndText } from '../static/js/schedule_scope.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('the last schedule-end result is shown as one line', () => {
  assert.equal(scheduleEndText({ state: 'idle', message: '' }), '');
  assert.equal(scheduleEndText({}), '');
  assert.equal(
    scheduleEndText({ state: 'failed', message: '스케줄 끝 · 서보를 끄지 않고 그대로 둠 · Servo 알람 2등급' }),
    '스케줄 끝 · 서보를 끄지 않고 그대로 둠 · Servo 알람 2등급',
  );
});

test('the schedule window saves the end action as a project setting', () => {
  const html = read('../static/panels/11-modals.html');
  const manager = read('../static/js/schedule_manager.js');
  assert.match(html, /id="scheduleEndAction"/);
  assert.match(html, /value="park_servo_off"/);
  assert.match(html, /value="hold"/);
  assert.match(manager, /configureMotionAutomation\(\{ schedule_end_action: action \}\)/);
});

test('each motor can stay powered at schedule end', () => {
  const motorConfig = read('../static/js/motor_config.js');
  assert.match(motorConfig, /const SCHEDULE_END_FIELD = 'schedule_end_servo_off'/);
  // 켬이 기본 · 끌 때만 false 를 적는다
  assert.match(motorConfig, /if \(value === false\) config\[field\] = false;\s*else delete config\[field\];/);
  assert.match(motorConfig, /setAxisEditValue\(row, field, Boolean\(input\.checked\)\)/);
});
