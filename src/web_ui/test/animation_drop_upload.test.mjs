/** 애니메이션 드래그&드롭 업로드 · 길은 기존 import 창구 하나다 · P5
 *
 * 새 라우트를 만들지 않는다 · `POST /api/projects/{id}/files` 가 JSONL
 * 검증과 「모션축 설정 먼저」 문지기를 이미 들고 있다 · 화면은 파일을
 * 글자로 읽어 싣고, 거절 사유를 그대로 보여 준다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const html = indexHtml;
const controller = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
const service = readFileSync(
  new URL('../../web_bridge/motion_web_bridge/project_service.py', import.meta.url),
  'utf8',
);

test('the file list is a drop zone and says so', () => {
  assert.match(html, /motion-file-drop-hint/);
  assert.match(controller, /function bindAnimationDropZone\(\)/);
  assert.match(controller, /bindAnimationDropZone\(\);/);
  assert.match(controller, /closest\('\.motion-file-column'\)/);
});

test('drops go through the one existing import gateway', () => {
  assert.match(controller, /importProjectFile\(projectId, \{\n\s*category: 'motions'/);
  // 새 업로드 경로를 만들지 않았다
  assert.doesNotMatch(controller, /FormData|multipart/);
});

test('json only, and one failure stops the batch so its reason stays visible', () => {
  assert.match(controller, /\.json\$\/i\.test\(file\.name/);
  const start = controller.indexOf('async function importDroppedAnimations');
  const body = controller.slice(start, controller.indexOf('function bindAnimationDropZone', start));
  assert.match(body, /break;/);
  assert.match(body, /업로드 실패/);
});

test('the server refuses without a joint mapping, in joint terms', () => {
  assert.match(service, /모션축 설정이 없는 프로젝트에는 애니메이션을 넣을 수 없습니다/);
  assert.match(service, /애니메이션\(\.json\)뿐입니다/);
});
