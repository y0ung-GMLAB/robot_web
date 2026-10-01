// 회차별 모션 기록 그래프 계산 · 범위 · 선 끊기 · 요약
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  TRACE_RESULT_LABELS,
  formatTraceBytes,
  tracePolylines,
  traceResultLabel,
  traceValueRange,
  traceWorstError,
} from '../static/js/motion_trace_chart.js';

test('범위는 두 계열을 함께 보고 빈 칸은 건너뛴다', () => {
  const [low, high] = traceValueRange([[0, null, 10], [-2, 5]], 0);
  assert.equal(low, -2);
  assert.equal(high, 10);
});

test('값이 하나뿐이거나 없어도 그릴 수 있는 범위를 준다', () => {
  assert.deepEqual(traceValueRange([[3, 3]]), [2, 4]);
  assert.deepEqual(traceValueRange([[null], []]), [-1, 1]);
});

test('실제 위치가 끊긴 곳에서 선을 끊는다', () => {
  const lines = tracePolylines(
    [0, 1, 2, 3, 4],
    [0, 1, null, 3, 4],
    { width: 100, height: 10, timeRange: [0, 4], valueRange: [0, 4] },
  );
  assert.deepEqual(lines, ['0.0,10.0 25.0,7.5', '75.0,2.5 100.0,0.0']);
});

test('점 하나짜리 조각은 선이 아니다', () => {
  const lines = tracePolylines([0, 1, 2], [null, 1, null], {
    width: 10, height: 10, timeRange: [0, 2], valueRange: [0, 2],
  });
  assert.deepEqual(lines, []);
});

test('회차 요약에서 가장 큰 오차를 고른다', () => {
  const worst = traceWorstError({
    axes: [
      { motion_id: '1-1', max_abs_error_deg: 0.2 },
      { motion_id: '1-2', max_abs_error_deg: null },
      { motion_id: '1-3', max_abs_error_deg: 0.7 },
    ],
  });
  assert.deepEqual(worst, { motionId: '1-3', value: 0.7 });
  assert.equal(traceWorstError({ axes: [{ motion_id: '1-1', max_abs_error_deg: null }] }), null);
});

test('결과 이름과 크기 표기', () => {
  assert.equal(traceResultLabel('completed'), TRACE_RESULT_LABELS.completed);
  assert.equal(traceResultLabel('weird'), 'weird');
  assert.equal(formatTraceBytes(2048), '2.0 KB');
});
