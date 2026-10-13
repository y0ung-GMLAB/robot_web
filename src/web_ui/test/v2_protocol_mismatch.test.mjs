/** UI v2 · 연동 약속 번호가 다른 PC · 그룹에서 빠진다 · 커밋만 다르면 빠지지 않는다 (프로토콜 7 · 2026-10-13) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { collectIssues, pcRows } from '../static/v2/js/model.js';
import { protocolNote, storeRows } from '../static/v2/js/store_model.js';

const snap = { coordination: { runtime: { network_pcs: [
  { pc_id: 'floating4', is_local: true, is_master: true, online: true, joined: true, protocol_version: 7 },
  { pc_id: 'floating1', online: true, joined: true, protocol_version: 6, protocol_mismatch: true, version_differs: true },
  { pc_id: 'floating2', online: true, joined: true, protocol_version: 7, version_differs: true },
  { pc_id: 'speaker', role: 'speaker', online: true, protocol_version: 0, version_differs: true },
] } } };

test('PC 현황 · 연동 버전 다름은 빨강 · 번호를 같이 · 커밋만 다르면 노랑 · 그룹 재생은 된다', () => {
  const rows = storeRows(snap);
  assert.deepEqual(rows.map((r) => [r.id, r.status, r.tone]), [
    ['floating4', '그룹 대기', 'ok'], ['floating1', '연동 버전 다름', 'bad'], ['floating2', '버전 다름', 'warn'], ['speaker', '스피커', 'ok'],
  ]);
  assert.match(rows[1].note, /그룹 재생에서 빠집니다\(연동 약속 번호 6 · 이 PC 7\)/);
  assert.match(rows[2].note, /그룹 재생은 되지만/);
  assert.match(protocolNote(0, 7), /약속 번호 없음\(옛 프로그램\) · 이 PC 7/);
});

test('확인할 일 · 연동 버전 다름과 커밋 다름을 나눠 말한다 · 스피커 뺌', () => {
  const issues = collectIssues(snap, {}).filter((i) => i.action?.kind === 'update-all');
  assert.deepEqual(issues.map((i) => [i.title, i.detail]), [
    ['floating1 연동 버전이 다릅니다', '그룹 재생에서 빠집니다. 모든 PC를 같은 버전으로 업데이트하세요.'],
    ['floating2 버전이 다릅니다', '그룹 재생은 되지만 같은 버전으로 맞추세요'],
  ]);
});

test('홈 PC 줄 · 연동 버전 다름은 빨강', () => {
  assert.deepEqual(pcRows(snap).map((r) => [r.note, r.tone]).slice(1, 3), [['연동 버전 다름', 'bad'], ['버전 다름', 'warn']]);
});
