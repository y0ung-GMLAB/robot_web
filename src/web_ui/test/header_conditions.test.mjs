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

test('그룹 참여를 꺼 두면 그룹 미참여 · 혼자 재생이라고 말한다 · 83', () => {
  const [scope] = motionHeaderConditionCells({ enabled: true, joined: false, inWindow: false });

  assert.equal(scope.text, '그룹 미참여');
  assert.match(scope.title, /그룹 참여」 꺼짐 · 이 PC 혼자 재생합니다/);
});

test('아직 모르면 물음표로 둔다', () => {
  // 모르는 것을 「그룹 미참여」로 단정하면 없는 문제를 만든다
  assert.deepEqual(texts({ enabled: null, joined: null, inWindow: null }), ['그룹?', '운영시간?']);
});

test('앱솔루트 미확인이면 빨간 칸이 붙고 누르면 모터 관리로 간다 · 수정 목록 62', () => {
  const cells = motionHeaderConditionCells({
    enabled: true, joined: false, inWindow: true,
    absoluteProblem: '앱솔루트 미확인 · 1번 모터 Pr0.15=1(인크리멘털)',
  });
  const absolute = cells.find((cell) => cell.key === 'absolute');

  assert.equal(absolute.text, '앱솔루트 미확인');
  assert.equal(absolute.bad, true);
  assert.equal(absolute.action, 'config');
  assert.match(absolute.title, /1번 모터 Pr0\.15=1/);
  // 상태를 아직 몰라도 붙는다 · 모든 화면에서 보여야 한다
  assert.ok(texts({ enabled: null, joined: null, inWindow: null, absoluteProblem: 'x' }).includes('앱솔루트 미확인'));
  assert.ok(!texts({ enabled: true, joined: true, inWindow: true }).includes('앱솔루트 미확인'));
});
