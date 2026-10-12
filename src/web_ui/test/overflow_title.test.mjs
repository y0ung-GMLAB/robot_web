/** 잘린 글에 전체 글 툴팁 · 수정 목록 99 · 판정과 글 고르기 (DOM 없이 가짜 칸으로) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { isClipped, overflowText } from '../static/js/overflow_title.js';

const box = (scrollWidth, clientWidth) => ({ scrollWidth, clientWidth });

test('「…」 이고 글이 칸보다 넓을 때만 잘린 것', () => {
  assert.equal(isClipped(box(300, 120), { textOverflow: 'ellipsis' }), true);
  assert.equal(isClipped(box(120, 120), { textOverflow: 'ellipsis' }), false, '딱 맞음');
  assert.equal(isClipped(box(900, 300), { textOverflow: 'clip' }), false, '스크롤 칸(표 감싸개)은 아님');
  assert.equal(isClipped(box(300, 0), { textOverflow: 'ellipsis' }), false, '안 그려진 칸');
});

test('글 · 공백 하나로 · 선택 칸은 고른 것 · 입력 칸은 값', () => {
  assert.equal(overflowText({ tagName: 'SPAN', textContent: '  floating_narration_all\n  .json ' }), 'floating_narration_all .json');
  assert.equal(overflowText({ tagName: 'SELECT', selectedOptions: [{ textContent: ' motion_axis.yaml ' }] }), 'motion_axis.yaml');
  assert.equal(overflowText({ tagName: 'INPUT', value: 'abc' }), 'abc');
});

test('기존 화면 시작에서 한 번 깐다', () => {
  const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
  assert.match(main, /installOverflowTitles\(\);/);
});
