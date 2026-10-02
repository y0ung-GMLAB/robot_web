/** 조그 단위 토글 · 기본은 조인트 deg(감속비·방향 적용), 끄면 모터 deg · P4
 *
 * 전에는 조그가 **항상 모터 deg** 였다 · 목(1:150)에서 1도를 치면 모터축
 * 1도 = 관절이 0.0067도만 움직여서, 사람은 "조그가 안 된다" 고 읽었다
 * (2026-09-30 미니PC에서 실제로 그랬다).
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const html = indexHtml;
const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const controller = readFileSync(new URL('../static/js/motion_test.js', import.meta.url), 'utf8');
const motionData = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');

test('the toggle lives in the jog panel and is bound through dom.js', () => {
  assert.match(html, /id=["']motionTestJogJointMode["']/);
  assert.match(dom, /motionTestJogJointMode: document\.getElementById\(["']motionTestJogJointMode["']\)/);
  // 조그 패널에서만 보인다
  const toggleAt = html.indexOf('motionTestJogJointMode');
  const panelAt = html.lastIndexOf('data-motion-test-panel="jog"', toggleAt);
  assert.ok(panelAt > 0, '토글이 조그 패널 안에 있어야 한다');
});

test('every gear-ratio site asks one function, with the toggle folded in', () => {
  // 세 곳이 따로 삼항식을 들고 있던 것을 하나로 모았다
  assert.doesNotMatch(controller, /mode === 'action' \? actionGearRatio\(el, motor\) : 1/);
  assert.match(controller, /function commandGearRatio\(mode, motor\)/);
  assert.ok(controller.match(/commandGearRatio\(/g).length >= 4);
  // 방향(invert)까지 비율에 접힌다 · 출력 = 모터 / signedRatio
  assert.match(controller, /\(row\.invert \? -1 : 1\)/);
});

test('the joint row comes from the saved mapping through main.js', () => {
  assert.match(motionData, /jointRowForAxis: \(axis\) =>/);
  assert.match(main, /getJointRow: \(axis\) => motionData\?\.jointRowForAxis\?\.\(axis\) \|\| null/);
});

test('joint mode is the default and the user override resets per motor', () => {
  assert.match(controller, /if \(!el\.motionTestJogJointMode\.dataset\.userSet\)/);
  assert.match(controller, /delete el\.motionTestJogJointMode\.dataset\.userSet/);
  // 연결된 조인트 이름이 없으면 꺼지고 그 이유를 말한다
  assert.match(controller, /이 모터에 연결된 조인트 이름이 없습니다/);
});

test('the jog cap shrinks with the ratio so the motor-side 360° holds', () => {
  assert.match(controller, /function jogInputMaxDeg\(motor\)/);
  assert.match(controller, /maxJogDeltaDeg\(getLatestState\(\)\) \/ ratio/);
  assert.doesNotMatch(controller, /Math\.abs\(command\) > maxJogDeltaDeg\(getLatestState\(\)\)/);
});
