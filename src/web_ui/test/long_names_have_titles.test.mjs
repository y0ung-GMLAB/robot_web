// 수정 목록 55 · 「…」 로 잘리는 파일 이름 칸은 마우스를 올리면 전체 이름
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (name) => readFileSync(new URL(`../static/js/${name}`, import.meta.url), 'utf8');

test('애니메이션 파일 목록 · 현재 파일 문구 · 프로젝트 트리 이름에 title', () => {
  const motion = read('motion_data.js');
  assert.match(motion, /class="link-button" data-motion-file-id="\$\{displayText\(file\.id\)\}" title="\$\{displayText\(file\.filename\)\}"/);
  assert.match(motion, /el\.motionFileMessage\.title = /);
  const tree = read('project_explorer.js');
  assert.equal((tree.match(/class="project-tree-name" title=/g) || []).length, 2);
});
