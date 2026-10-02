/** 수동 조작은 「수동」 모드에서만 · 화면 쪽 · 2026-10-02 사용자 결정
 *
 * 서버(run_mode_gate.manual_control_block_reason)가 최종 문이고, 화면은 같은
 * 규칙으로 미리 막고 이유와 「수동 모드로 전환」 버튼을 보여 준다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { manualControlBlockReason, setRunMode } from '../static/js/run_mode_state.js';

const read = (name) => readFileSync(new URL(`../static/js/${name}`, import.meta.url), 'utf8');
const gate = readFileSync(
  new URL('../../web_bridge/motion_web_bridge/run_mode_gate.py', import.meta.url), 'utf8');

test('only manual mode opens the gate · unknown mode does not block', () => {
  setRunMode('');
  assert.equal(manualControlBlockReason(), '');
  setRunMode('manual');
  assert.equal(manualControlBlockReason(), '');
  setRunMode('schedule');
  assert.match(manualControlBlockReason(), /스케줄 모드 · 수동 조작은 「수동」 모드에서만/);
  setRunMode('off');
  assert.match(manualControlBlockReason(), /오프 모드/);
});

test('the screen sentence matches the server sentence', () => {
  setRunMode('schedule');
  const screen = manualControlBlockReason();
  assert.ok(gate.includes(screen.split(' (')[0]), '서버 문장과 다르다');
});

test('jog, action, dial and fader all ask the same gate', () => {
  assert.match(read('motion_test.js'), /return manualControlBlockReason\(\) \|\| servoAlarmBlockReason\(motor\) \|\| jogBlockReason\(motor\);/);
  assert.match(read('motion_test.js'), /return manualControlBlockReason\(\) \|\| servoAlarmBlockReason\(motor\) \|\| actionBlockReason\(motor\);/);
  assert.match(read('jog_dial.js'), /const modeReason = manualControlBlockReason\(\);/);
  assert.match(read('manual_fader.js'), /const modeReason = manualControlBlockReason\(\);/);
  assert.match(read('schedule_manager.js'), /setRunMode\(this\.status\?\.run_mode \|\| 'schedule'\);/);
});

test('the manual screen shows why and offers the one-click way out', () => {
  assert.match(indexHtml, /id="manualModeBanner"/);
  assert.match(indexHtml, /id="manualModeSwitchButton"[^>]*>수동 모드로 전환</);
  assert.match(read('main.js'), /window\.ScheduleManager\?\.requestRunMode\('manual'\)/);
  assert.match(read('main.js'), /onRunModeChange\(\(\) => \{/);
});
