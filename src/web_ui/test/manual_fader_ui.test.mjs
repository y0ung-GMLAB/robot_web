/** 수동 페이더 · 잡는 동안만 흐르고, 놓으면 그 자리에 선다 · §6-310
 *
 * 변환(모션축 deg → 모터 deg)은 화면이 한다 · 그래서 소켓 인사에
 * `base_mapping_revision` 이 실려야 하고, 식은 서버
 * (`motion_mapping_manager._motion_to_motor_target`)와 같아야 한다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const html = indexHtml;
const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const fader = readFileSync(new URL('../static/js/manual_fader.js', import.meta.url), 'utf8');
const mappingManager = readFileSync(
  new URL('../../motion_runtime/motion_runtime/motion_mapping_manager.py', import.meta.url),
  'utf8',
);

test('fader card exists in the manual screen and is bound through dom.js', () => {
  for (const id of ['manualFaderList', 'manualFaderMessage']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} missing from HTML`);
    assert.match(dom, new RegExp(`${id}: document\\.getElementById\\(["']${id}["']\\)`));
  }
  assert.match(html, /페이더 · 실시간 드래그/);
});

test('main.js wires render, project reset, and event binding', () => {
  assert.match(main, /createManualFaderController\(/);
  assert.match(main, /manualFader\.renderRuntimeState\(\);/);
  assert.match(main, /manualFader\.bindEvents\(\);/);
  // 프로젝트가 바뀌면 옛 매핑으로 변환하지 않는다
  assert.match(main, /manualFader\.onProjectChange\(\);/);
});

test('the socket handshake carries the mapping revision', () => {
  assert.match(fader, /\/ws\/manual-stream/);
  assert.match(fader, /base_mapping_revision: mapping\?\.revision \|\| ''/);
});

test('input streams while held and change releases in place', () => {
  // input = 잡는 중 · 50ms(20Hz) 묶음 전송
  assert.match(fader, /const SEND_PERIOD_MS = 50;/);
  assert.match(fader, /addEventListener\('input'/);
  // change = 놓음 · release 가 나가 지금 자리에 선다
  assert.match(fader, /addEventListener\('change'/);
  assert.match(fader, /type: 'release'/);
});

test('the joint-to-motor formula matches the server', () => {
  // 서버: reference + ((value + offset) * scale * sign) * gear
  assert.match(
    mappingManager,
    /return \(motion_value \+ offset\) \* scale \* sign/,
  );
  assert.match(mappingManager, /return reference \+ \(output_value \* gear_ratio\)/);
  // 화면: 같은 식 · 한 줄로 합쳐 적었다
  assert.match(
    fader,
    /row\.reference \+ \(jointDeg \+ row\.offset\) \* row\.scale \* row\.sign \* row\.gear/,
  );
});

test('faders follow the real position only while not held', () => {
  assert.match(fader, /if \(!active\) slider\.value = /);
  // 범위는 매핑의 모션 최소·최대 · 그 밖은 잘린다
  assert.match(fader, /clamp\(Number\(value\), row\.lower, row\.upper\)/);
});
