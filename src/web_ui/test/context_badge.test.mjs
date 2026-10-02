/** 상단 설정 상태 배지 · 저장 안 한 편집 → 모터 적용 필요 → 설정 적용됨 · 2026-10-02
 *
 * 전에는 「저장 = 실행」 하나라 화면에서 고쳐도 초록 그대로였다 (사용자 보고).
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const motorConfig = readFileSync(new URL('../static/js/motor_config.js', import.meta.url), 'utf8');
const motionData = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');

test('the old 「저장 = 실행」 label is gone', () => {
  assert.doesNotMatch(main, /'저장 = 실행'/);
});

test('unsaved screen edits are checked before the saved-vs-running state', () => {
  const start = main.indexOf('function contextBadge(context)');
  const body = main.slice(start, main.indexOf("el.headerContextState?.addEventListener('click'", start));
  const unsavedAt = body.indexOf("text: '저장 안 한 변경'");
  const readyAt = body.indexOf("text: '설정 적용됨'");
  assert.ok(unsavedAt > 0 && readyAt > unsavedAt, '저장 안 한 변경을 먼저 본다');
  assert.match(body, /motorConfig\.hasUnsavedChanges\(\)/);
  assert.match(body, /motionData\.hasUnsavedMappingChanges\(\)/);
  assert.match(body, /text: '모터 적용 필요'/);
  // 선언 전에 불려도 터지지 않는다
  assert.match(body, /try \{ return Boolean\(read\(\)\); \} catch \{ return false; \}/);
});

test('controllers expose their unsaved state', () => {
  assert.match(motorConfig, /hasUnsavedChanges: \(\) => hasMotorConfigDataChanges\(\) \|\| hasAxisChanges\(\),/);
  assert.match(motionData, /hasUnsavedMappingChanges: \(\) => Boolean\(mappingDirty\),/);
});

test('clicking a warning badge goes to the screen that fixes it', () => {
  assert.match(main, /document\.querySelector\(`\[data-workspace-tab="\$\{target\}"\]`\)\?\.click\(\);/);
  assert.match(main, /target: 'config',/);
});
