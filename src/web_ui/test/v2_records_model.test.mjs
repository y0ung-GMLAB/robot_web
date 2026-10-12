/** UI v2 · 기록 · 회차 줄 · 목표·실제 그래프 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { runRows, traceGeometry } from '../static/v2/js/records_model.js';

test('회차 줄 · 결과 글 · 최대 오차는 축 중 가장 큰 것 · 최근 것이 위', () => {
  const rows = runRows([
    { file: 'a', started_text: '2026-10-12T10:00:00+09:00', cycle: 1, motion_file_id: 'x.json', result: 'error', message: '도달 실패',
      axes: [{ max_abs_error_deg: 0.1 }, { max_abs_error_deg: 0.4 }, { max_abs_error_deg: null }] },
    { file: 'b', started_text: '2026-10-12T14:27:01+09:00', cycle: 3, motion_file_id: 'y.json', result: 'completed', group_execution: true, axes: [] },
  ]);
  assert.deepEqual(rows.map((r) => [r.file, r.time, r.result, r.worst, r.group]), [
    ['b', '14:27:01', '끝까지', '-', true], ['a', '10:00:00', '오류', '0.40°', false],
  ]);
});

test('그래프 · 같은 눈금 · 빠진 표본은 선을 끊는다', () => {
  const geo = traceGeometry([0, 1, 2, 3], [0, 1, 2, 3], [0, null, 2, 3], { width: 30, height: 10 });
  assert.equal((geo.target.match(/M/g) || []).length, 1);
  assert.equal((geo.actual.match(/M/g) || []).length, 2, 'null 뒤에서 새로 시작');
  assert.equal(traceGeometry([0], [1], [1]), null);
  assert.equal(traceGeometry([0, 1], [null, null], [null, null]), null);
});
