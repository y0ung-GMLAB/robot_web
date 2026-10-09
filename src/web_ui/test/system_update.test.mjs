/** 모든 PC 업데이트 화면 · 2026-10-08 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { systemUpdateRows } from '../static/js/system_update.js';

const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const api = readFileSync(new URL('../static/js/api.js', import.meta.url), 'utf8');
const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');

test('the update section sits under the same-network PC table with one button', () => {
  const network = indexHtml.indexOf('aria-label="같은 망 PC"');
  const update = indexHtml.indexOf('aria-label="모든 PC 업데이트"');
  assert.ok(network > 0 && update > network);
  assert.match(indexHtml, /<button id="systemUpdateAllButton" class="primary" type="button">모든 PC 업데이트<\/button>/);
  for (const id of ['systemUpdateAllButton', 'systemUpdateRefreshButton', 'systemUpdateMessage', 'systemUpdateRows']) {
    assert.ok(dom.includes(`${id}: document.getElementById('${id}')`), id);
  }
  assert.match(main, /const systemUpdate = createSystemUpdateController\(\{ el \}\);/);
  assert.match(main, /systemUpdate\.bindEvents\(\);/);
  assert.match(api, /request\('POST', '\/api\/system\/update-all', \{ projectScoped: false/);
});

test('rows show state, version change and the last line', () => {
  const html = systemUpdateRows([
    { pc_id: 'floating1', state: 'done', before_hash: 'aaa', git_hash: 'bbb', tail: ['설치 완료'] },
    { pc_id: 'floating2', state: 'unreachable', git_hash: 'aaa', message: '응답 없음' },
    { pc_id: 'speaker', role: 'speaker', state: 'manual', message: '스피커 PC 는 그 PC 터미널에서' },
    { pc_id: 'floating4', state: 'failed', is_local: true, git_hash: 'aaa', tail: ['!! 새 시스템 패키지가 필요합니다'] },
  ]);
  assert.match(html, /완료/);
  assert.match(html, /aaa → bbb/);
  assert.match(html, /응답 없음 \(재시작 중일 수 있음\)/);
  assert.match(html, /터미널에서/);
  assert.match(html, /floating4<\/strong> <small>\(이 PC\)<\/small>/);
  assert.match(html, /새 시스템 패키지가 필요합니다/);
  assert.match(systemUpdateRows([]), /같은 망 PC 를 기다리는 중/);
});

test('a failed update shows only the current version, not before → after (82)', () => {
  const html = systemUpdateRows([
    { pc_id: 'floating3', state: 'failed', before_hash: 'aaa', git_hash: 'ccc', message: '멈춘 단계 · 8. 전체 빌드' },
  ]);
  assert.doesNotMatch(html, /→/);
  assert.match(html, />ccc</);
  assert.match(html, /멈춘 단계 · 8\. 전체 빌드/);
  const recovered = systemUpdateRows([
    { pc_id: 'floating3', state: 'done', before_hash: 'aaa', git_hash: 'ccc', after_hash: 'ddd', message: '그 뒤 설치로 복구됨' },
  ]);
  assert.match(recovered, /aaa → ddd/);
});
