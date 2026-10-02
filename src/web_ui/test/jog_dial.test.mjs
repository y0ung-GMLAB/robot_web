/** 조그 다이얼 · 돌린 만큼 상대 이동 · 단위는 모터 deg (감속비 미적용) · 2026-10-02
 *
 * supervisor 는 앞 조그가 끝나기 전 새 조그를 거절한다 · 그래서 다이얼은
 * 돌린 양을 쌓아 두고 앞 요청이 끝나면 한 번에 보낸다 · 빨리 돌려도 칸을
 * 잃지 않는다 · 페이더(절대 위치)는 그대로 둔다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const html = indexHtml;
const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const dial = readFileSync(new URL('../static/js/jog_dial.js', import.meta.url), 'utf8');

test('the dial sits in the jog panel and is bound through dom.js', () => {
  for (const id of ['jogDial', 'jogDialNeedle', 'jogDialStep', 'jogDialPosition', 'jogDialPending', 'jogDialMessage']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} missing`);
    assert.match(dom, new RegExp(`${id}: document\\.getElementById\\(["']${id}["']\\)`));
  }
  const at = html.indexOf('id="jogDial"');
  assert.ok(html.lastIndexOf('data-motion-test-panel="jog"', at) > 0, '조그 패널 안에 있어야 한다');
  // 페이더는 그대로 있다
  assert.match(html, /id="manualFaderList"/);
});

test('step choices are motor deg and match the module list', () => {
  const options = [...html.matchAll(/<option value="([\d.]+)"[^>]*>[\d.]+°<\/option>/g)]
    .map((match) => Number(match[1]));
  const declared = JSON.parse(dial.match(/JOG_DIAL_STEPS = Object\.freeze\((\[[^\]]+\])\)/)[1]);
  for (const step of declared) assert.ok(options.includes(step), `${step}° 선택지가 없다`);
  assert.match(html, /모터 deg · 감속비 미적용/);
});

test('it sends raw motor deg through the existing jog path, never the gear ratio', () => {
  assert.match(dial, /relative_deg: delta/);
  assert.match(dial, /requestAcServoJog/);
  assert.match(dial, /requestDynamixelJog/);
  assert.doesNotMatch(dial, /gear_ratio|gearRatio|jointRowForAxis/);
});

test('ticks accumulate while a jog is running and retry on "previous jog"', () => {
  assert.match(dial, /if \(inFlight \|\| retryTimer/);
  assert.match(dial, /message\.includes\('이전 조그'\)/);
  assert.match(dial, /pendingDeg \+= delta;\s*\n\s*scheduleRetry\(\);/);
  // 다른 거절은 쌓인 양을 버린다
  assert.match(dial, /pendingDeg = 0;\s*\n\s*lastMessage = message;/);
});

test('switching motor or project drops the pending amount', () => {
  assert.match(main, /el\.motionTestAxisSelect\?\.addEventListener\('change', \(\) => jogDial\.reset\(\)\)/);
  assert.match(main, /jogDial\.reset\(\);/);
  assert.match(main, /jogDial\.renderRuntimeState\(\);/);
});
