/** 조그 다이얼 · 돌린 만큼 상대 이동 · 단위는 모터 deg (감속·기어비 미적용) · 2026-10-02
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
  for (const id of ['jogDial', 'jogDialRing', 'jogDialMinus', 'jogDialPlus', 'jogDialStep', 'jogDialPosition', 'jogDialPending', 'jogDialMessage', 'jogDialCancelPending']) {
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
  assert.match(html, /모터 deg · 감속·기어비 미적용/);
  // 범위 밖·숫자 아님은 보내지 않고 사유를 말한다
  assert.match(dial, /if \(step === null\)/);
  assert.match(dial, /const STEP_MIN_DEG = 0\.001;/);
  assert.match(dial, /const STEP_MAX_DEG = 360;/);
});

test('it streams raw motor deg like the fader, never the gear ratio · 56', () => {
  // 조그를 하나씩 보내지 않는다 · 페이더와 같은 실시간 스트림 · 단위는 모터 deg(감속비 없음)
  assert.match(dial, /\/ws\/manual-stream/);
  assert.match(dial, /type: 'target', axis: session\.axis, target_deg: next/);
  assert.match(dial, /send\(\{ type: 'release', axes: \[axis\] \}\)/);
  assert.doesNotMatch(dial, /requestAcServoJog|requestDynamixelJog|relative_deg/);
  assert.doesNotMatch(dial, /gear_ratio|gearRatio|jointRowForAxis/);
});

test('the streamed target moves at most the speed cap per tick and only after it was sent · 56', () => {
  assert.match(dial, /const MAX_SPEED_DEG_S = 1125;/);
  assert.match(dial, /const maxStep = MAX_SPEED_DEG_S \* \(SEND_PERIOD_MS \/ 1000\);/);
  // 보낸 것만 앞으로 간다 · 연결 전 혼자 앞서 나가면 연결 직후 튄다
  assert.match(dial, /if \(!send\(\{ type: 'target'[^]*?\}\)\) \{\s*\n\s*render\(\);\s*\n\s*return;\s*\n\s*\}\s*\n\s*session\.commanded = next;/);
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
  // 리밋 원본은 조인트 매핑 하나 · 모터 운전 한계는 매핑 저장 때 서버가 환산 (2026-10-02)
  assert.match(mainSource, /return motionData\.saveCapturedPoint\(axis, kind, motorDeg\);/);
  assert.doesNotMatch(mainSource, /saveMotorLimit/);
  // 매핑 저장이 모터 설정 파일을 바꾸면 모터 관리 화면이 다시 읽는다
  assert.match(mainSource, /onMotorLimitsChange: \(changed\) => motorConfig\.reloadIfClean\(changed\)/);
  // 이동 중·쌓인 양이 있을 때는 찍지 않는다
  assert.match(dial, /이동이 끝난 뒤에 지정하세요/);
  // 버튼 이름 · 「~으로」 대신 「지정 / limit」
  assert.match(html, />기준점 지정<\/button>/);
  assert.match(html, />\+ limit<\/button>/);
  assert.match(html, />− limit<\/button>/);
});

// 목표 위치 입력 후 이동 · 둘 다 모터 deg · 2026-10-02
// ON/OFF 토글 삭제 · 다이얼과 목표 칸을 늘 같이 · 숨김 규칙 없음 · 2026-10-06
test('dial and typed target are always shown together in the same jog block', () => {
  for (const id of ['jogDialBlock', 'jogTargetInput', 'jogTargetMoveButton']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} missing`);
    assert.match(dom, new RegExp(`${id}: document\\.getElementById\\(["']${id}["']\\)`));
  }
  const block = html.indexOf('id="jogDialBlock"');
  assert.ok(html.indexOf('id="jogTargetInput"') > block, '목표 칸은 다이얼 블록 안');
  assert.match(html, /목표 위치 \(모터 deg · 감속·기어비 미적용\)/);
  // 41 · 칸을 숨겨 옆 칸이 밀리던 옛 토글은 없다 · 52 · 스위치는 다이얼만 잠근다(숨기지 않음)
  assert.doesNotMatch(html, /jog-dial-toggle|jog-dial-only|jog-target-only|썸휠/);
  assert.doesNotMatch(dial, /dial-off|style\.display|classList\.toggle\('hidden'/);
  const css = readFileSync(new URL('../static/css/14-redesign.css', import.meta.url), 'utf8');
  assert.doesNotMatch(css, /dial-off|jog-dial-only|jog-target-only/);
  assert.match(html, /id="jogDialEnabledSwitch"[^>]*role="switch"/);
  assert.match(dom, /jogDialEnabledSwitch: document\.getElementById\('jogDialEnabledSwitch'\)/);
  assert.match(css, /\.jog-dial\.locked \{/);
  const column = html.indexOf('class="jog-wheel-column"');
  assert.ok(html.indexOf('id="jogDialPlus"') > column && html.indexOf('id="jogDial" class="jog-dial jog-wheel"') > column);
  assert.match(html, /오른쪽 = \+/);
});

test('the typed target goes through the existing absolute move path in motor deg', () => {
  assert.match(dial, /requestAcServoAction/);
  assert.match(dial, /requestDynamixelAction/);
  assert.match(dial, /target_deg: target,/);
  // 시간은 안 보낸다 · supervisor 가 속도·가속 한계로 정한다
  assert.doesNotMatch(dial, /duration_sec:/);
  // 같은 잠금 · 앞 요청이 돌거나 다이얼 양이 남았으면 안 보낸다 · 한계 밖이면 안 보낸다
  assert.match(dial, /if \(reason \|\| inFlight \|\| hasPending\(\)\) \{/);
  assert.match(dial, /const limitReason = targetLimitReason\(motor, target\);/);
  // 모터를 바꾸면 목표 칸을 새 모터 위치로 다시 채운다
  assert.match(dial, /targetTouched = false;\s*\n\s*endSession\(true\);/);
});

test('the old action tab with a hand-typed gear ratio is gone', () => {
  assert.doesNotMatch(html, /data-motion-test-mode="action"/);
  assert.doesNotMatch(html, /id="motionTestGearRatio"/);
  assert.doesNotMatch(html, /id="motionTestRunButton"/);
  // 범위 복귀는 남는다
  assert.match(html, /data-motion-test-mode="recovery"/);
  assert.match(html, /id="motionTestRecoveryButton"/);
});

test('motion range conversion respects invert and rounds inward', () => {
  const data = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
  const limits = readFileSync(new URL('../static/js/motor_config.js', import.meta.url), 'utf8');
  assert.match(data, /const setsMotionUpper = motorUpper === \(factor > 0\);/);
  assert.match(data, /Math\.floor\(motion \* 10000\) \/ 10000/);
  assert.match(data, /Math\.ceil\(motion \* 10000\) \/ 10000/);
  // 저장 안 한 편집이 있으면 거절 (같이 저장되면 안 된다)
  assert.match(data, /if \(mappingDirty\) \{/);
  // 모터 관리에 저장 안 한 편집이 있으면 다시 읽지 않고 알린다
  assert.match(limits, /if \(hasMotorConfigDataChanges\(\) \|\| hasAxisChanges\(\)\) \{/);
  assert.match(data, /if \(payload\.motor_limits\?\.changed\?\.length\) await onMotorLimitsChange\?\.\(payload\.motor_limits\.changed\);/);
});
