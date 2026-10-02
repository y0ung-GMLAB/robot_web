/** 재생 라이브 오버라이드 · 실행 축 표의 사용 토글 + 라이브 리밋 · P7
 *
 * 재생 중 이상한 조인트 이름을 **그 자리에서** 빼거나(모터는 서보 켠 채 정지)
 * 범위를 산 채로 좁힌다 · 매핑 파일은 안 바뀐다 · 다음 20ms 틱부터 듣는다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const html = indexHtml;
const controller = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
const api = readFileSync(new URL('../static/js/api.js', import.meta.url), 'utf8');

test('the run-joints table carries the toggle and live-limit columns', () => {
  const head = html.slice(html.indexOf('애니메이션 재생 축'), html.indexOf('motionRunAxisRows'));
  assert.match(head, /<th>사용<\/th>/);
  assert.match(head, /<th>라이브 리밋 \(모션 deg\)<\/th>/);
  assert.match(html, /colspan="12" class="empty">실행 준비 검사를 누르면 표시됩니다/);
});

test('rows render the mute checkbox and clamp inputs from live_overrides', () => {
  assert.match(controller, /data-live-mute="\$\{escapeHtml\(axis\.motion_id\)\}"/);
  assert.match(controller, /data-live-clamp-side="lo"/);
  assert.match(controller, /data-live-clamp-side="hi"/);
  assert.match(controller, /function liveOverrideOf\(motionId\)/);
});

test('edits go through the one gateway and update local state', () => {
  assert.match(api, /setMotionRunLiveOverride = \(payload\) =>\n\s*request\('POST', '\/api\/motion-run\/live-override'/);
  assert.match(controller, /await setMotionRunLiveOverride\(payload\)/);
  assert.match(controller, /motionRunStatus\.live_overrides = result\?\.live_overrides \|\| \{\};/);
});

test('an inverted clamp is refused before it reaches the server', () => {
  assert.match(controller, /low > high/);
  assert.match(controller, /라이브 리밋은 최소 ≤ 최대 인 숫자여야 합니다/);
  // 두 칸을 다 비우면 해제다
  assert.match(controller, /payload\.clamp = null;/);
});

test('live status updates do not clobber a cell being edited', () => {
  const start = controller.indexOf('function renderMotionRunAxes()');
  const body = controller.slice(start, start + 400);
  assert.match(body, /contains\(document\.activeElement\)\) return;/);
});
