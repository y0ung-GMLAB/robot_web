/** 기준점을 새로 잡으면 페이더가 새 기준점으로 계산한다 · 2026-10-02
 *
 * 사용자 보고 · 기준점 지정 → 설정에서 재시작 → 돌아와도 페이더가 왼쪽 끝 ·
 * 원인 · 페이더는 화면이 보일 때 한 번만 매핑을 읽었다 · 같은 화면에서 찍은
 * 기준점은 몰랐고, 재시작 직후 읽기가 실패하면 옛 매핑을 들고 다시 안 읽었다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const fader = readFileSync(new URL('../static/js/manual_fader.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const data = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');

test('a saved mapping (reference capture included) makes the fader re-read', () => {
  assert.match(data, /await onProjectFilesChange\?\.\(\);\s*\n\s*onMappingSaved\?\.\(\);/);
  assert.match(main, /onMappingSaved: \(\) => manualFader\.refresh\(\),/);
});

test('a failed read is retried while the panel is visible', () => {
  assert.match(fader, /retryAt = Date\.now\(\) \+ RETRY_MS;/);
  assert.match(fader, /else if \(visible && retryAt && Date\.now\(\) >= retryAt && !refreshing\) refresh\(\);/);
});

test('a save during a read triggers one more read', () => {
  assert.match(fader, /refreshAgain = true;\s*\n\s*return;/);
  assert.match(fader, /if \(refreshAgain\) refresh\(\);/);
});

test('a restarted bridge makes the fader re-read too', () => {
  assert.match(main, /Promise\.resolve\(\)\.then\(\(\) => manualFader\.refresh\(\)\)\.catch\(\(\) => \{\}\);/);
});

test('the reference itself is part of what the fader redraws on', () => {
  assert.match(fader, /row\.lower, row\.upper, row\.reference, row\.gear, row\.sign/);
});
