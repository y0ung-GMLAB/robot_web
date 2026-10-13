// 수정 목록 132 (실물 2026-10-13) · 「장비에 적용」 이 성공했는데 응답 전에 브리지가 재시작으로 내려가 HTTP 500 ·
// 화면은 작업 기록(motor_operation)을 다시 읽어 실제 결과를 보인다
import test from 'node:test';
import assert from 'node:assert/strict';

import { applyOutcomeFromRecord } from '../static/v2/js/actions.js';

const noSleep = { sleep: async () => {}, waitMs: 0 };

function reader(snaps) {
  let i = 0;
  return async () => {
    const snap = snaps[Math.min(i, snaps.length - 1)];
    i += 1;
    if (snap instanceof Error) throw snap;
    return snap;
  };
}

test('다시 켜지는 동안 못 읽고 · 진행 중 · 그다음 성공이면 성공', async () => {
  const outcome = await applyOutcomeFromRecord(reader([
    new Error('연결 끊김'),
    { motor_operation: { type: 'motor_apply', status: 'running' } },
    { motor_operation: { type: 'motor_apply', status: 'success', message: '모터 설정 적용·재시작 완료' } },
  ]), noSleep);
  assert.deepEqual(outcome, { success: true, message: '모터 설정 적용·재시작 완료' });
});

test('작업 기록이 실패면 실패와 이유', async () => {
  const outcome = await applyOutcomeFromRecord(reader([
    { motor_operation: { type: 'motor_apply', status: 'failure', error: '준비 거절' } },
  ]), noSleep);
  assert.deepEqual(outcome, { success: false, message: '준비 거절' });
});

test('끝까지 모르면 null · 다른 작업 기록은 보지 않음', async () => {
  const outcome = await applyOutcomeFromRecord(reader([
    { motor_operation: { type: 'full_scan', status: 'success' } },
  ]), { ...noSleep, tries: 3 });
  assert.equal(outcome, null);
});

test('누르기 전의 성공 기록은 이번 결과로 치지 않음', async () => {
  const outcome = await applyOutcomeFromRecord(reader([
    { motor_operation: { type: 'motor_apply', status: 'success', operation_id: 'old' } },
  ]), { ...noSleep, tries: 3, previousId: 'old' });
  assert.equal(outcome, null);
});
