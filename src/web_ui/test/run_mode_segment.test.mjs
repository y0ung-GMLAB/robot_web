/** 상단 운전 모드 세그먼트 · 스케줄 | 수동 | 오프 · P5
 *
 * 모드 전환이 모달 속 select 에만 있어서 3클릭이었다 · 상단에서 1클릭으로
 * 바꾸되, **위험한 방향은 한 번 묻는다** · 스케줄(시간 창 안이면 즉시 재생
 * 가능) · 오프(움직임 명령 전부 차단) · 수동은 자동만 멈추므로 바로 간다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const html = indexHtml;
const manager = readFileSync(new URL('../static/js/schedule_manager.js', import.meta.url), 'utf8');

test('three modes sit in the topbar segment', () => {
  const segment = html.match(/id="runModeSegment"[\s\S]*?<\/div>/)?.[0] || '';
  for (const mode of ['schedule', 'manual', 'off']) {
    assert.match(segment, new RegExp(`data-run-mode="${mode}"`), `${mode} 단추가 없다`);
  }
});

test('risky directions ask once, manual goes straight through', () => {
  const start = manager.indexOf('async requestRunMode(mode)');
  const body = manager.slice(start, manager.indexOf('async saveRunMode(mode)', start));
  assert.ok(start >= 0, 'requestRunMode 가 있어야 한다');
  assert.match(body, /schedule:/);
  assert.match(body, /off:/);
  assert.doesNotMatch(body, /manual:/);
  assert.match(body, /showConfirm\(/);
  // 같은 모드를 또 눌러도 아무 일 없다
  assert.match(body, /if \(mode === current\) return;/);
  // 저장은 기존 한 길 · 모달 select 와 같은 경로
  assert.match(body, /await this\.saveRunMode\(mode\);/);
});

test('the segment mirrors saved state and locks when editing is blocked', () => {
  assert.match(manager, /button\.classList\.toggle\('active', button\.dataset\.runMode === mode\);/);
  assert.match(manager, /button\.disabled = !state\.canEdit;/);
});
