/** 애니메이션이 없을 때 「초기 위치 이동」 · 실패가 보여야 한다 · 2026-10-02
 *
 * 사용자 보고 · 애니메이션이 없으면 초기 위치 이동이 자주 에러 ·
 * 화면은 그 오류를 「애니메이션 없음 · …0°로 이동할 수 있습니다」로 덮었고,
 * 막힌 사유 자리에 「…사용자 제어 가능」이 떴다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const data = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');

test('an error status is never replaced by the no-animation hint', () => {
  const at = data.indexOf("status.state === 'error' && status.message");
  const hint = data.indexOf("'애니메이션 없음 · 첫 프레임 모터는 모션값 0°로 초기 위치 이동할 수 있습니다'");
  assert.ok(at > 0 && hint > at, '오류를 먼저 본다');
});

test('the block reason says the animation is missing, not that control is possible', () => {
  assert.match(data, /'재생 등록된 애니메이션이 없습니다 · 「재생 등록」 후 재생 · 초기 위치 이동은 지금도 됩니다'/);
  assert.match(data, /localReason,\n\s*\}\);/);
});

test('the initialize button explains what it will do without an animation', () => {
  assert.match(data, /'애니메이션이 없어 「첫 프레임」 줄은 모션 0°\(기준점\)로 · 「직접 지정」 줄은 그 값으로 이동합니다'/);
});

// 「초기 방식: 첫 프레임 / 수동」 → 「초기 위치: 첫 프레임 / 직접 지정 / 기준점」 (2026-10-02 사용자 결정)
test('initial position offers 첫 프레임 · 직접 지정 · 기준점', () => {
  const html = readFileSync(new URL('../static/panels/05-panel-registration.html', import.meta.url), 'utf8');
  assert.match(html, /mapping-head-label">초기 위치</);
  assert.match(html, /mapping-head-label">지정 값</);
  assert.doesNotMatch(html, /mapping-head-label">초기 방식</);
  assert.match(data, /<option value="manual"[^>]*>직접 지정<\/option>/);
  assert.match(data, /<option value="reference"[^>]*>기준점<\/option>/);
  assert.match(data, />첫 프레임<\/option>/);
  // 값은 「직접 지정」일 때만 입력
  assert.match(data, /const initialPositionDisabled = initialMode !== 'manual';/);
  assert.match(data, /row\.initial_mode = \['manual', 'reference'\]\.includes\(value\) \? value : 'first_frame';/);
});

test('the runtime and the validator know the 기준점 mode', () => {
  const rules = readFileSync(new URL('../../motion_runtime/motion_runtime/motion_run_rules.py', import.meta.url), 'utf8');
  const mapping = readFileSync(new URL('../../motion_runtime/motion_runtime/motion_mapping_manager.py', import.meta.url), 'utf8');
  assert.match(rules, /if mode == 'reference':\n[\s\S]*?return 0\.0/);
  assert.match(mapping, /INITIAL_MODES = \('first_frame', 'manual', 'reference'\)/);
});

test('a later failure while moving is shown in a dialog once', () => {
  assert.match(data, /function watchInitializeOutcome\(status\)/);
  assert.match(data, /watchInitializeOutcome\(status\);/);
  assert.match(data, /if \(state === 'error' && initializeWatchStarted\) \{/);
});

test('runtime refuses a broken initialize right away and names the action', () => {
  const manager = readFileSync(new URL('../../motion_runtime/motion_runtime/motion_run_manager.py', import.meta.url), 'utf8');
  const player = readFileSync(new URL('../../motion_runtime/motion_runtime/motion_player.py', import.meta.url), 'utf8');
  assert.match(manager, /'message': f'초기 위치 이동 불가: \{exc\}',/);
  assert.match(player, /f'초기 위치 이동 준비 실패: \{exc\}'/);
});
