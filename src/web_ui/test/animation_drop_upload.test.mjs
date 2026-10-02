/** 애니메이션 드래그&드롭 업로드 · 길은 기존 import 창구 하나다 · P5
 *
 * 새 라우트를 만들지 않는다 · `POST /api/projects/{id}/files` 가 JSONL
 * 검증과 「조인트 매핑 먼저」 문지기를 이미 들고 있다 · 화면은 파일을
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
  const start = controller.indexOf('async function importAnimationFiles');
  const body = controller.slice(start, controller.indexOf('function bindAnimationDropZone', start));
  assert.match(body, /break;/);
  assert.match(body, /업로드 실패/);
  // 실패는 창으로도 띄운다 · 작은 글씨만으론 놓친다 (2026-10-02)
  assert.match(controller, /showAlert\(message, \{ title: '애니메이션 불러오기', tone: 'warning' \}\);/);
});

// 불러오기 버튼 · 폴더 드롭 · 화면 전체 받는 칸 · 문서 전체 가드 · 2026-10-02
test('a 불러오기 button opens a multi-file picker through the same path', () => {
  assert.match(html, /<button id="motionFileImportButton"[^>]*>불러오기<\/button>/);
  assert.match(html, /<input id="motionFileImportInput" type="file"[^>]*accept="\.json,application\/json" multiple>/);
  assert.match(controller, /el\.motionFileImportButton\?\.addEventListener\('click', \(\) => el\.motionFileImportInput\?\.click\(\)\)/);
  assert.match(controller, /importAnimationFiles\(chosen\);/);
});

test('the whole animation screen takes drops, folders included, and stray drops cannot navigate away', () => {
  assert.match(controller, /closest\('\.motion-data-panel'\)/);
  assert.match(controller, /const entries = droppedEntries\(event\.dataTransfer\);/);
  assert.match(controller, /importAnimationFiles\(nested\.flat\(\)\.map\(\(item\) => item\.file\), \{ fromFolder: true \}\);/);
  const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
  assert.match(main, /guardDocumentDrops\(\);/);
});

test('MuJoCo precompute after upload picks from the reloaded list, not the dropped File objects', () => {
  const start = controller.indexOf('async function importAnimationFiles');
  const body = controller.slice(start, controller.indexOf('function bindAnimationDropZone', start));
  assert.match(body, /let picked = /);
  assert.doesNotMatch(body, /const files = /);
  assert.match(body, /const toCompute = files\.filter\(/);
});

test('the server refuses without a joint mapping, in joint terms', () => {
  assert.match(service, /조인트 매핑이 없는 프로젝트에는 애니메이션을 넣을 수 없습니다/);
  assert.match(service, /애니메이션\(\.json\)뿐입니다/);
});
