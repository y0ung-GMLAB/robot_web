/** UI v2 · 기록 화면이 보는 값 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 기록) */

export const RESULT_TEXT = {
  completed: ['끝까지', 'ok'],
  stopped: ['도중 정지', 'warn'],
  error: ['오류', 'bad'],
};

export const CATEGORY_LABELS = {
  all: '전체',
  error: '모터 오류',
  motion: '재생 시작',
  initial_position: '초기 위치',
  coordination: '그룹',
  system: '시스템',
};

/** 회차 줄 · 최대 오차는 축들 중 가장 큰 것 */
export function runRows(runs) {
  return (Array.isArray(runs) ? runs : []).map((run) => {
    const errors = (run.axes || []).map((axis) => Number(axis.max_abs_error_deg)).filter(Number.isFinite);
    const worst = errors.length ? Math.max(...errors) : null;
    const [label, tone] = RESULT_TEXT[run.result] || [String(run.result || '-'), 'idle'];
    return {
      file: String(run.file || ''),
      time: String(run.started_text || '').slice(11, 19),
      cycle: Number(run.cycle) || 0,
      motion: String(run.motion_file_id || '').replace(/\.json$/i, ''),
      result: label,
      tone,
      message: String(run.message || ''),
      group: run.group_execution === true,
      worst: worst === null ? '-' : `${worst.toFixed(2)}°`,
      worstValue: worst,
    };
  }).sort((a, b) => (a.time < b.time ? 1 : -1));
}

/** 목표·실제 두 줄 · 같은 세로 눈금 · null(빠진 표본)은 선을 끊는다 */
export function traceGeometry(time, target, actual, { width = 600, height = 120 } = {}) {
  const t = (time || []).map(Number);
  if (t.length < 2) return null;
  const values = [...(target || []), ...(actual || [])].map((v) => (v === null || v === '' ? NaN : Number(v))).filter(Number.isFinite);
  if (!values.length) return null;
  let vmin = Math.min(...values);
  let vmax = Math.max(...values);
  if (vmax - vmin < 1e-6) { vmin -= 1; vmax += 1; }
  const pad = (vmax - vmin) * 0.08;
  vmin -= pad;
  vmax += pad;
  const t0 = t[0];
  const span = Math.max(t[t.length - 1] - t0, 1e-6);
  const path = (series) => {
    let out = '';
    let pen = false;
    (series || []).forEach((raw, i) => {
      const v = raw === null || raw === '' ? NaN : Number(raw);
      if (!Number.isFinite(v) || !Number.isFinite(t[i])) { pen = false; return; }
      const x = ((t[i] - t0) / span) * width;
      const y = height - ((v - vmin) / (vmax - vmin)) * height;
      out += `${pen ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
      pen = true;
    });
    return out;
  };
  return { target: path(target), actual: path(actual), min: vmin + pad, max: vmax - pad, duration: span };
}

export function eventTime(event) {
  return String(event?.timestamp_text || '').slice(11, 19);
}
