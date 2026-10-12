/** UI v2 · 문서 읽기 · 블록 나누기 · 표 · 목록 나무 · 차례 · 찾기 · 링크 안전 (설계안 2026-10-09 · 사용법) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { outline, parseMarkdown, safeHref, searchSections, slug } from '../static/v2/js/markdown.js';

const DOC = [
  '# 사용법', '', '## 1. 시작하기', '첫 줄', '둘째 줄', '',
  '| 모드 | 스케줄 |', '|---|:---:|', '| 수동 | 멈춤 |', '| `a|b` | x ' + String.fromCharCode(92) + '| y |', '',
  '- 하나', '  - 안쪽', '- 둘', '', '1. 첫째', '2. 둘째', '',
  '```bash', 'bash scripts/install.sh', '# 주석은 제목 아님', '```', '',
  '> 인용 **굵게**', '', '---', '### 기준점 캡처', '기준점 은 한 번', '',
].join('\n');

test('블록 · 제목 · 문단 이어 붙이기 · 표 · 목록 · 코드 · 인용 · 선', () => {
  const blocks = parseMarkdown(DOC);
  assert.deepEqual(blocks.map((b) => b.type), ['heading', 'heading', 'paragraph', 'table', 'list', 'list', 'code', 'quote', 'hr', 'heading', 'paragraph']);
  assert.equal(blocks[2].text, '첫 줄 둘째 줄');
  assert.deepEqual(blocks[3].head, ['모드', '스케줄']);
  assert.deepEqual(blocks[3].rows, [['수동', '멈춤'], ['`a|b`', 'x | y']], '코드 안 | 와 \| 는 칸을 안 나눈다');
  assert.equal(blocks[4].tree.length, 2);
  assert.equal(blocks[4].tree[0].children[0].text, '안쪽');
  assert.equal(blocks[5].tree[0].ordered, true);
  assert.equal(blocks[6].text, 'bash scripts/install.sh\n# 주석은 제목 아님');
});

test('차례 · ## 와 ### 만 · 찾기 · 절마다 몇 번', () => {
  assert.deepEqual(outline(DOC).map((o) => [o.level, o.text]), [[2, '1. 시작하기'], [3, '기준점 캡처']]);
  assert.deepEqual(searchSections(DOC, '기준점').map((s) => [s.text, s.count]), [['기준점 캡처', 2]]);
  assert.deepEqual(searchSections(DOC, ''), []);
});

test('링크 · http(s) 와 문서 안 # 만 · 나머지는 글로', () => {
  assert.deepEqual(safeHref('https://a.b/c'), { href: 'https://a.b/c', external: true });
  assert.equal(safeHref('#2-운전-모드').href, '#doc-2-운전-모드');
  assert.equal(safeHref('javascript:alert(1)'), null);
  assert.equal(safeHref('../etc/passwd'), null);
  assert.equal(slug('4-1. 찾기 (조인트)'), '4-1-찾기-조인트');
});
