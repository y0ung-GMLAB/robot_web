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

test('step size is a free numeric input in motor deg', () => {
  assert.match(html, /<input id="jogDialStep"[^>]*type="number"/);
  assert.doesNotMatch(html, /<select id="jogDialStep"/);
  assert.match(html, /모터 deg · 감속비 미적용/);
  // 범위 밖·숫자 아님은 보내지 않고 사유를 말한다
  assert.match(dial, /if \(step === null\)/);
  assert.match(dial, /const STEP_MIN_DEG = 0\.001;/);
  assert.match(dial, /const STEP_MAX_DEG = 360;/);
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

test('capture buttons save the current motor position, with a confirm first', () => {
  for (const id of ['jogDialSetReference', 'jogDialSetLower', 'jogDialSetUpper']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  const mainSource = main;
  assert.match(mainSource, /async function captureJogPoint\(kind, \{ axis, motorDeg \}\)/);
  assert.match(mainSource, /await showConfirm\(/);
  // 기준점은 모션축 설정만 · 끝은 모션축 범위 + 모터 운전 한계 둘 다
  assert.match(mainSource, /if \(kind === 'reference' \|\| !mapping\.success\) return mapping;/);
  assert.match(mainSource, /motorConfig\.saveMotorLimit\(axis, kind, motorDeg\)/);
  // 이동 중·쌓인 양이 있을 때는 찍지 않는다
  assert.match(dial, /이동이 끝난 뒤에 지정하세요/);
  // 버튼 이름 · 「~으로」 대신 「지정 / limit」
  assert.match(html, />기준점 지정<\/button>/);
  assert.match(html, />\+ limit<\/button>/);
  assert.match(html, />− limit<\/button>/);
});

test('motion range conversion respects invert and rounds inward', () => {
  const data = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
  const limits = readFileSync(new URL('../static/js/motor_config.js', import.meta.url), 'utf8');
  assert.match(data, /const setsMotionUpper = motorUpper === \(factor > 0\);/);
  assert.match(data, /Math\.floor\(motion \* 10000\) \/ 10000/);
  assert.match(data, /Math\.ceil\(motion \* 10000\) \/ 10000/);
  // 저장 안 한 편집이 있으면 거절 (같이 저장되면 안 된다)
  assert.match(data, /if \(mappingDirty\) \{/);
  assert.match(limits, /if \(hasMotorConfigDataChanges\(\) \|\| hasAxisChanges\(\)\) \{/);
});
