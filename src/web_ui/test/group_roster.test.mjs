// 매장 로봇 명단 · 1대가 빠져도 나머지로 · 수정 목록 30 (2026-10-06)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../static/js/coordination.js', import.meta.url), 'utf8');

test('excluded PCs show the reason in the table and the execution line', () => {
  assert.match(source, /`제외 · \$\{excludedReason\}`/);
  assert.match(source, /execution\.excluded/);
  assert.match(source, /` · 제외 \$\{/);
});

test('roster rows say missing and outside instead of waiting for boot autoplay', () => {
  assert.match(source, /🔴 미접속/);
  assert.match(source, /'명단 외'/);
  assert.doesNotMatch(source, /부팅 자동 재생/);
});

test('slave mode and web link come from the heartbeat', () => {
  assert.match(source, /OPERATION_MODE_TEXT\[peer\.operation_mode\]/);
  // 주소는 숫자 IP:포트만 · 하트비트 값을 그대로 링크로 쓰지 않는다
  assert.match(source, /\^http:\\\/\\\/\[0-9\.\]\+:\\d\+\$/);
});
