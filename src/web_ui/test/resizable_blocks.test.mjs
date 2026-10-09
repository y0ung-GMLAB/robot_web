/** 애니메이션 화면 블록 · 끌어서 높이 조절 · 크기 기억 · 수정 목록 96 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { initResizableBlocks, savedHeight } from '../static/js/resizable_blocks.js';

test('saved heights are only sane pixel values', () => {
  assert.equal(savedHeight('320px'), '320px');
  assert.equal(savedHeight('320.6px'), '321px');
  assert.equal(savedHeight('10px'), '');
  assert.equal(savedHeight('50%'), '');
  assert.equal(savedHeight(''), '');
});

test('a block gets its remembered height back and works without storage', () => {
  const store = { 'robot_web.size.anim.playlist': '300px' };
  globalThis.window = { localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; }, removeItem: (k) => { delete store[k]; } } };
  const block = { dataset: { resizeKey: 'anim.playlist' }, style: { height: '' }, addEventListener: () => {} };
  const root = { querySelectorAll: () => [block] };
  assert.equal(initResizableBlocks(root), 1);
  assert.equal(block.style.height, '300px');
  globalThis.window = { get localStorage() { throw new Error('blocked'); } };
  const fresh = { dataset: { resizeKey: 'anim.files' }, style: { height: '' }, addEventListener: () => {} };
  assert.equal(initResizableBlocks({ querySelectorAll: () => [fresh] }), 1);
  assert.equal(fresh.style.height, '', '저장소가 막혀도 기본 크기로 돈다');
});

test('the animation screen blocks are drag-resizable and the playlist no longer gets squeezed', () => {
  for (const key of ['anim.files', 'anim.playlist', 'anim.axes', 'anim.graph', 'anim.3d']) {
    assert.match(indexHtml, new RegExp(`data-resize-key="${key.replace('.', '\.')}"`), key);
  }
  const css = readFileSync(new URL('../static/css/07-motion.css', import.meta.url), 'utf8');
  assert.match(css, /\.user-resizable \{ resize: vertical; overflow: auto; \}/);
  assert.match(css, /\.motion-file-column > \.motion-playlist\.user-resizable \{ flex: 0 0 auto;/);
  assert.match(css, /\.motion-file-column > \.motion-file-drop-hint \{ flex: 0 0 auto; \}/);
  const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
  assert.match(main, /initResizableBlocks\(document\);/);
  const sim3d = readFileSync(new URL('../static/js/sim3d.js', import.meta.url), 'utf8');
  assert.match(sim3d, /new ResizeObserver\(\(\) => resize\(\)\)\.observe\(el\.sim3dCanvasWrap\)/);
});
