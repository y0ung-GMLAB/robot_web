/** UI v2 · 저장 충돌 때 최신 파일에 이 화면에서 고친 칸만 얹기 (사용자 2026-10-12) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { threeWayMerge } from '../static/v2/js/merge_model.js';

const key = (m) => m.id;

test('다른 곳이 다른 칸을 바꿨으면 둘 다 남는다 · 충돌 없음', () => {
  const base = [{ id: 'a', name: 'A', config: { brake: 100, speed: 10 } }];
  const draft = [{ id: 'a', name: 'A2', config: { brake: 100, speed: 10 } }];
  const latest = [{ id: 'a', name: 'A', config: { brake: 120, speed: 10 }, lower: -5 }];
  const { records, conflicts } = threeWayMerge(base, draft, latest, key);
  assert.deepEqual(conflicts, []);
  assert.deepEqual(records, [{ id: 'a', name: 'A2', config: { brake: 120, speed: 10 }, lower: -5 }]);
});

test('같은 칸을 양쪽이 다르게 바꾸면 충돌 · 값은 이 화면 것', () => {
  const base = [{ id: 'a', config: { brake: 100 } }];
  const draft = [{ id: 'a', config: { brake: 90 } }];
  const latest = [{ id: 'a', config: { brake: 120 } }];
  const { records, conflicts } = threeWayMerge(base, draft, latest, key);
  assert.equal(records[0].config.brake, 90);
  assert.deepEqual(conflicts, [{ key: 'a', path: ['config', 'brake'], mine: 90, theirs: 120 }]);
});

test('같은 값으로 바꿨거나 안 고친 레코드는 최신 그대로 · 추가 · 삭제', () => {
  const base = [{ id: 'a', v: 1 }, { id: 'b', v: 1 }];
  const draft = [{ id: 'a', v: 2 }, { id: 'c', v: 3 }];
  const latest = [{ id: 'a', v: 2 }, { id: 'b', v: 1 }, { id: 'd', v: 4 }];
  const { records, conflicts } = threeWayMerge(base, draft, latest, key);
  assert.deepEqual(conflicts, []);
  assert.deepEqual(records.map((r) => r.id), ['a', 'd', 'c']);
});

test('지웠는데 다른 곳이 고쳤으면 충돌', () => {
  const { conflicts } = threeWayMerge([{ id: 'b', v: 1 }], [], [{ id: 'b', v: 2 }], key);
  assert.equal(conflicts[0].path[0], '(삭제)');
});
