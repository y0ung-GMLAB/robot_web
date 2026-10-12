/** UI v2 · 수동 조작 · 다이얼 규칙 · 막는 순서 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { addDelta, markSent, nextTarget, pending, releaseDue, startSession, wheelPixels } from '../static/v2/js/dial_session.js';
import { manualBlocker } from '../static/v2/js/pages/manual.js';

test('다이얼 · 한계로 자름 · 한 번에 1125°/s × 0.05 s 까지 · 보낸 만큼만', () => {
  const s = startSession({ axis: 0, position: 0, lower: -100, upper: 100, now: 0 });
  addDelta(s, 300, 0);
  assert.equal(s.target, 100);
  assert.equal(s.hitLimit, '상한');
  const first = nextTarget(s);
  assert.equal(first, 56.25);
  assert.equal(s.commanded, 0, '안 보냈으면 그대로');
  markSent(s, first);
  assert.equal(pending(s), 43.75);
  addDelta(s, -500, 10);
  assert.equal(s.target, -100);
  assert.equal(s.hitLimit, '하한');
});

test('놓기 · 200 ms 멈추고 다 보냈고 · 도착(0.05°) 또는 1 s', () => {
  const s = startSession({ axis: 0, position: 0, now: 0 });
  addDelta(s, 10, 0);
  markSent(s, 10);
  assert.equal(releaseDue(s, 100, 10), false, '입력 직후');
  assert.equal(releaseDue(s, 300, 9), false, '아직 안 닿음');
  assert.equal(releaseDue(s, 300, 9.97), true, '도착');
  assert.equal(releaseDue(s, 1000, 5), true, '1 s 지남');
  const t = startSession({ axis: 0, position: 0, now: 0 });
  addDelta(t, 10, 0);
  assert.equal(releaseDue(t, 5000, 0), false, '덜 보냈으면 안 놓음');
});

test('휠 · 줄·쪽 단위를 픽셀로', () => {
  assert.equal(wheelPixels({ deltaY: 100, deltaMode: 0 }), 100);
  assert.equal(wheelPixels({ deltaY: 3, deltaMode: 1 }), 120);
  assert.equal(wheelPixels({ deltaY: 1, deltaMode: 2 }), 800);
});

test('막는 순서 · 긴급 정지 > 모드 > 범위 미확인 > 앱솔루트 > 모터 사정 > 매핑 줄 없음', () => {
  const item = { axis: 0, ac: true, detected: true, fault: false, servoOn: true, row: { motion_id: 'A' } };
  const manual = { run_mode: 'manual' };
  assert.equal(manualBlocker({ snap: {}, sched: manual }, item), null);
  assert.equal(manualBlocker({ snap: { safety_status: { emergency_latched: true } }, sched: { run_mode: 'off' } }, item).fix, 'restart');
  assert.equal(manualBlocker({ snap: {}, sched: { run_mode: 'schedule' } }, item).fix, 'mode-manual');
  assert.equal(manualBlocker({ snap: { mapping_range_blocker: 'x' }, sched: manual }, item).fix, 'open-mapping');
  assert.equal(manualBlocker({ snap: { minas_absolute_blocker: 'y' }, sched: manual }, item).fix, 'open-motors');
  assert.equal(manualBlocker({ snap: {}, sched: manual }, { ...item, fault: true }).fix, 'reset');
  assert.equal(manualBlocker({ snap: {}, sched: manual }, { ...item, servoOn: false }).fix, 'servo-on');
  assert.equal(manualBlocker({ snap: {}, sched: manual }, { ...item, ac: false, servoOn: false }), null, 'DXL 은 서보 검사 안 함');
  assert.match(manualBlocker({ snap: {}, sched: manual }, { ...item, row: null }).text, /「사용」이 꺼져 있습니다/);
  assert.match(manualBlocker({ snap: {}, sched: manual }, { ...item, detected: false }).text, /통신 없음/);
});

test('초기 위치에서 대기 중 · 재생 중이면 「정지」 뒤에만 · 서버와 같은 문구 (2026-10-12)', () => {
  const manual = { run_mode: 'manual' };
  const item = { axis: 0, detected: true, servoOn: true, ac: true, row: { motion_id: 'a' } };
  const initialized = manualBlocker({ snap: { motion_run_status: { state: 'initialized' } }, sched: manual }, item);
  assert.equal(initialized.text, '초기 위치에서 대기 중입니다. 「정지」를 누른 뒤 수동 조작을 하세요.');
  assert.equal(initialized.fix, 'stop');
  assert.match(manualBlocker({ snap: { motion_run_status: { state: 'running' } }, sched: manual }, item).text, /재생 중입니다/);
  assert.equal(manualBlocker({ snap: { motion_run_status: { state: 'stopped' } }, sched: manual }, item), null);
});
