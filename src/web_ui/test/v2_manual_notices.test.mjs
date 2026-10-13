/** UI v2 · 목표 근처 출렁임 알림 · 실물 R-11 (2026-10-13) · supervisor 가 조작을 끝내며 남긴 알림 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { collectIssues, manualNotices } from '../static/v2/js/model.js';

test('출렁임 알림 · 축마다 · 홈에도', () => {
  const snap = { safety_status: { manual_notices: [
    { axis: 2, kind: 'hunting', message: '2번 모터가 목표 근처에서 출렁입니다(…) · 게인(강성)을 확인하세요', stamp: 1 },
    { axis: 0, kind: 'short', message: '0번 모터가 목표에 못 미치고 섰습니다(…)', stamp: 1 },
  ] } };
  assert.deepEqual(manualNotices(snap, 2).map((n) => n.kind), ['hunting']);
  assert.equal(manualNotices(snap).length, 2);
  assert.deepEqual(manualNotices({}), []);
  const issue = collectIssues(snap).find((i) => i.title.startsWith('2번 모터가 목표 근처에서 출렁입니다'));
  assert.ok(issue);
  assert.equal(issue.tone, 'warn');
  assert.deepEqual(issue.action, { kind: 'open', target: 'maintain-motors', label: '모터 설정 열기' });
});
