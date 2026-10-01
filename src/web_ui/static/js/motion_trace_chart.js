/** 회차별 모션 기록 그래프 계산 · DOM 없이 도는 순수 함수만 둔다
 *
 * 그리기는 motion_trace.js 가 한다 · 여기서는 범위와 선 좌표만 만든다 · 시험이
 * 브라우저 없이 확인할 수 있어야 한다.
 */

export const TRACE_RESULT_LABELS = Object.freeze({
  completed: '완료',
  stopped: '도중 정지',
  error: '오류',
});

/** 여러 계열의 값 범위 · 비어 있는 칸은 건너뛴다 · 위아래로 조금 띄운다 */
export function traceValueRange(seriesList, padRatio = 0.08) {
  let low = Infinity;
  let high = -Infinity;
  for (const series of seriesList) {
    for (const value of series || []) {
      if (value === null || value === undefined || !Number.isFinite(value)) continue;
      if (value < low) low = value;
      if (value > high) high = value;
    }
  }
  if (!Number.isFinite(low)) return [-1, 1];
  if (high - low < 1e-6) {
    return [low - 1, high + 1];
  }
  const pad = (high - low) * padRatio;
  return [low - pad, high + pad];
}

/** SVG polyline 점 목록 · 값이 빈 곳에서 선을 끊는다 (실제 위치가 끊긴 구간) */
export function tracePolylines(times, values, { width, height, timeRange, valueRange }) {
  const [t0, t1] = timeRange;
  const [v0, v1] = valueRange;
  const tSpan = Math.max(t1 - t0, 1e-9);
  const vSpan = Math.max(v1 - v0, 1e-9);
  const lines = [];
  let current = [];
  for (let i = 0; i < times.length; i += 1) {
    const value = values?.[i];
    if (value === null || value === undefined || !Number.isFinite(value)) {
      if (current.length > 1) lines.push(current.join(' '));
      current = [];
      continue;
    }
    const x = ((times[i] - t0) / tSpan) * width;
    const y = height - ((value - v0) / vSpan) * height;
    current.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  if (current.length > 1) lines.push(current.join(' '));
  return lines;
}

export function traceResultLabel(result) {
  return TRACE_RESULT_LABELS[String(result || '')] || String(result || '-');
}

/** 회차 요약의 모터별 최대 오차 중 가장 큰 것 · 없으면 null */
export function traceWorstError(record) {
  let worst = null;
  for (const axis of record?.axes || []) {
    const value = Number(axis?.max_abs_error_deg);
    if (axis?.max_abs_error_deg === null || axis?.max_abs_error_deg === undefined) continue;
    if (!Number.isFinite(value)) continue;
    if (worst === null || value > worst.value) worst = { motionId: String(axis.motion_id), value };
  }
  return worst;
}

export function formatTraceBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
