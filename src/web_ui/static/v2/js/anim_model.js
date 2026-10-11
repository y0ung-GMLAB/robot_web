/** UI v2 · 애니메이션 화면이 보는 값 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 애니메이션)
 *
 * 파일 값은 rad(서버 내부 단위) · 화면은 deg · 범위는 이 PC 조인트 매핑(rad)과 비교.
 */
import { fileInfo, formatDuration } from './play_model.js';

const DEG = 180 / Math.PI;
/** 범위 넘음 판정 여유 · 내보낼 때 반올림 정도는 넘음으로 치지 않는다 */
const RANGE_EPS_RAD = 1e-5;

const MUJOCO = {
  ready: ['준비됨', 'ok'],
  direct: ['바로 보기', 'ok'],
  computing: ['계산 중', 'info'],
  stale: ['다시 계산 필요', 'warn'],
  failed: ['계산 실패', 'bad'],
  missing: ['계산 전', 'idle'],
  unavailable: ['-', 'idle'],
};

export function mujocoState(file) {
  const preview = file?.preview;
  if (!preview || !preview.state) return { state: '', text: '-', tone: 'idle' };
  const [text, tone] = MUJOCO[preview.state] || [String(preview.state), 'idle'];
  return { state: String(preview.state), text, tone, message: String(preview.message || '') };
}

/** 범위 넘는 조인트 · 이 PC 매핑에 있는 것만 · [{id, min, max, lower, upper, over(deg)}] */
export function rangeIssues(analysis, mapping) {
  const rows = new Map((mapping?.mappings || []).filter((row) => row.enabled !== false).map((row) => [String(row.motion_id), row]));
  const out = [];
  for (const stat of analysis?.motion_ids || []) {
    const row = rows.get(String(stat.motion_id));
    if (!row) continue;
    const lower = Number(row.motion_lower_rad);
    const upper = Number(row.motion_upper_rad);
    const min = Number(stat.min_value);
    const max = Number(stat.max_value);
    if (![lower, upper, min, max].every(Number.isFinite)) continue;
    const over = Math.max(lower - min, max - upper);
    if (over > RANGE_EPS_RAD) {
      out.push({ id: String(stat.motion_id), min: min * DEG, max: max * DEG, lower: lower * DEG, upper: upper * DEG, over: over * DEG });
    }
  }
  return out.sort((a, b) => b.over - a.over);
}

/** 이 PC 매핑에 있는 조인트 수 · 파일 조인트 수 */
export function mappedCount(analysis, mapping) {
  const ids = new Set((mapping?.mappings || []).filter((row) => row.enabled !== false).map((row) => String(row.motion_id)));
  const fileIds = (analysis?.motion_ids || []).map((stat) => String(stat.motion_id));
  return { total: fileIds.length, mapped: fileIds.filter((id) => ids.has(id)).length };
}

/** 검사 칸 · 오류(형식) > 범위 넘음 > 경고 > 정상 */
export function checkState(file, mapping) {
  const analysis = file?.analysis || {};
  const info = fileInfo(file);
  if (info.check === 'bad') {
    const reason = (analysis.errors || [])[0] || analysis.message || file?.message || '형식';
    return { text: `오류 · ${reason}`, tone: 'bad' };
  }
  if (info.check === 'unknown') return { text: '검사 전', tone: 'idle' };
  const issues = rangeIssues(analysis, mapping);
  if (issues.length) return { text: `경고 · 범위 넘음 ${issues.length}`, tone: 'warn' };
  const { total, mapped } = mappedCount(analysis, mapping);
  if (mapping && total && !mapped) return { text: '경고 · 이 PC 조인트 없음', tone: 'warn' };
  if ((analysis.warnings || []).length) return { text: `경고 · ${analysis.warnings[0]}`, tone: 'warn' };
  return { text: '정상', tone: 'ok' };
}

/** 재생 목록 몇 번 · 같은 파일이 두 번이면 「1·3번」 */
export function playlistSlots(id, playlist) {
  const slots = (playlist || []).map((item, index) => (item === id ? index + 1 : 0)).filter(Boolean);
  return slots.length ? `${slots.join('·')}번` : '–';
}

function shortDate(epochSec) {
  const value = Number(epochSec);
  if (!Number.isFinite(value) || value <= 0) return '-';
  const date = new Date(value * 1000);
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function fileRows(files, { playlist = [], mapping = null } = {}) {
  return (files || []).map((file) => {
    const info = fileInfo(file);
    return {
      id: info.id,
      name: info.name,
      duration: formatDuration(info.duration),
      check: checkState(file, mapping),
      mujoco: mujocoState(file),
      slots: playlistSlots(info.id, playlist),
      date: shortDate(file.updated_at),
      sizeMb: Number(file.size_bytes || 0) / 1e6,
    };
  }).sort((a, b) => a.name.localeCompare(b.name));
}

/** 상세 머리 한 줄 · 「길이 9:16 · 50 fps · 27 802 프레임」 */
export function factLine(analysis) {
  const duration = Number(analysis?.time?.duration_sec);
  const period = Number(analysis?.interpolation?.period_sec || 0.02);
  const samples = Number(analysis?.interpolation?.sample_count);
  const parts = [`길이 ${formatDuration(Number.isFinite(duration) ? duration : null)}`];
  if (period > 0) parts.push(`${Math.round(1 / period)} fps`);
  if (Number.isFinite(samples) && samples > 0) parts.push(`${samples.toLocaleString('ko-KR')} 프레임`);
  return parts.join(' · ');
}

/**
 * 조인트 하나 그래프 · SVG path · 값은 deg · 범위 선이 보이도록 세로 폭에 범위도 넣는다
 * points [{time_sec, value(rad)}] → { line, lowerY, upperY, min, max }
 */
export function seriesGeometry(points, { width = 300, height = 80, lower = null, upper = null } = {}) {
  const list = (points || []).filter((p) => Number.isFinite(Number(p.time_sec)) && Number.isFinite(Number(p.value)));
  if (!list.length) return null;
  const values = list.map((p) => Number(p.value) * DEG);
  const times = list.map((p) => Number(p.time_sec));
  const bounds = [...values, ...[lower, upper].filter((v) => Number.isFinite(v))];
  let vmin = Math.min(...bounds);
  let vmax = Math.max(...bounds);
  if (vmax - vmin < 1e-6) { vmin -= 1; vmax += 1; }
  const pad = (vmax - vmin) * 0.08;
  vmin -= pad;
  vmax += pad;
  const t0 = times[0];
  const span = Math.max(times[times.length - 1] - t0, 1e-6);
  const x = (t) => ((t - t0) / span) * width;
  const y = (v) => height - ((v - vmin) / (vmax - vmin)) * height;
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(times[i]).toFixed(1)},${y(v).toFixed(1)}`).join('');
  return {
    line,
    lowerY: Number.isFinite(lower) ? y(lower) : null,
    upperY: Number.isFinite(upper) ? y(upper) : null,
    min: Math.min(...values),
    max: Math.max(...values),
  };
}
