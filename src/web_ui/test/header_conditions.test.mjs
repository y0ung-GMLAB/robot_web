import assert from 'node:assert/strict';
import test from 'node:test';
import { motionHeaderConditionCells } from '../static/js/header_conditions.js';

/**
 * 상단의 두 칸 · §6-286 §6-288
 *
 * 변수는 둘이다 · 그룹 참여냐 미참여냐 · 운영시간이냐 아니냐 · 그 조합이
 * 넷이다 · 배지를 셋으로 늘렸더니 상단이 두 줄로 밀리고 정작 다른 단추가
 * 안 보였다.
 */

const texts = (part) => motionHeaderConditionCells(part).map((cell) => cell.text);

test('네 조합이 전부 두 칸으로 나온다', () => {
  assert.deepEqual(
    texts({ enabled: true, joined: true, inWindow: true }), ['그룹 참여', '운영시간'],
  );
  assert.deepEqual(
    texts({ enabled: true, joined: true, inWindow: false }), ['그룹 참여', '운영시간 외'],
  );
  assert.deepEqual(
    texts({ enabled: true, joined: false, inWindow: true }), ['그룹 미참여', '운영시간'],
  );
  assert.deepEqual(
    texts({ enabled: false, joined: false, inWindow: false }), ['그룹 미참여', '운영시간 외'],
  );
});

test('둘 다 맞으면 둘 다 켜진다', () => {
  const cells = motionHeaderConditionCells({ enabled: true, joined: true, inWindow: true });

  assert.ok(cells.every((cell) => cell.on));
});

test('연동을 켜 두고 나가 있으면 그룹 미참여라고 말한다', () => {
  const [scope] = motionHeaderConditionCells({ enabled: true, joined: false, inWindow: false });

  assert.equal(scope.text, '그룹 미참여');
  assert.match(scope.title, /그룹에서 나가/);
});

test('아직 모르면 물음표로 둔다', () => {
  // 모르는 것을 「그룹 미참여」로 단정하면 없는 문제를 만든다
  assert.deepEqual(texts({ enabled: null, joined: null, inWindow: null }), ['그룹?', '운영시간?']);
});
