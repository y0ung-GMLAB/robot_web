/** UI v2 · 구간 재생 · 재생 목록 1번을 m:ss 부터 (끝 시각까지) · 화면 없이 시험되는 함수만 (2026-10-16)
 *
 * 서버 낱말의 주인은 `motion_common/motion_segment.py` · 글 모양(1:20 · 1:20.5)과 거절 문구를 같게 쓴다.
 * 시각은 파일 시각 · 애니메이션 첫 줄이 0.
 */

/** `80` → `1:20` · `80.5` → `1:20.5` · 0.1 초 단위 */
export function segmentClock(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return '-';
  const tenths = Math.round(Math.max(value, 0) * 10);
  const minutes = Math.floor(tenths / 600);
  const rest = tenths % 600;
  const whole = Math.floor(rest / 10);
  const tenth = rest % 10;
  return `${minutes}:${String(whole).padStart(2, '0')}${tenth ? `.${tenth}` : ''}`;
}

/** `1:20` · `1:20.5` · `80` · `80.5` · `1:02:03` → 초 · 빈 칸 = null · 못 읽으면 NaN */
export function parseClock(text) {
  const raw = String(text ?? '').trim();
  if (!raw) return null;
  if (!/^\d+(?::\d{1,2}){0,2}(?:\.\d+)?$/.test(raw)) return NaN;
  const parts = raw.split(':');
  const last = Number(parts.pop());
  if (parts.length && last >= 60) return NaN;
  const minutes = parts.length ? Number(parts.pop()) : 0;
  if (parts.length && minutes >= 60) return NaN;
  const hours = parts.length ? Number(parts.pop()) : 0;
  return hours * 3600 + minutes * 60 + last;
}

/** `구간 1:20~1:45` · 끝 0 = `구간 1:20~끝` · 구간이 없으면 빈 글자 */
export function segmentLabel(start, end) {
  const s = Math.max(Number(start) || 0, 0);
  const e = Math.max(Number(end) || 0, 0);
  if (s <= 0 && e <= 0) return '';
  return `구간 ${segmentClock(s)}~${e > 0 ? segmentClock(e) : '끝'}`;
}

/**
 * 입력 칸 두 개 → 보낼 값과 막는 이유 · `length` = 재생 목록 1번 길이(초 · 모르면 null)
 * 돌려주는 것 · { active, start, end, payload: {start_sec, end_sec} | null, error, note }
 */
export function segmentCheck({ startText = '', endText = '', length = null } = {}) {
  const start = parseClock(startText);
  const end = parseClock(endText);
  const idle = { active: false, start: 0, end: 0, payload: null, error: '', note: '' };
  if (Number.isNaN(start)) return { ...idle, error: '구간 시작을 m:ss 모양으로 적으세요 (예 1:20)' };
  if (Number.isNaN(end)) return { ...idle, error: '구간 끝을 m:ss 모양으로 적으세요 (예 1:45) · 끝까지면 비우세요' };
  const s = start ?? 0;
  const e = end ?? 0;
  if (s <= 0 && e <= 0) return idle;
  const known = Number.isFinite(Number(length)) && Number(length) > 0 ? Number(length) : null;
  const base = { active: true, start: s, end: e, payload: { start_sec: s, end_sec: e }, error: '', note: '' };
  if (e > 0 && e <= s) return { ...base, payload: null, error: `구간 끝 ${segmentClock(e)} 이 구간 시작 ${segmentClock(s)} 보다 뒤여야 합니다` };
  if (known !== null && s >= known) return { ...base, payload: null, error: `구간 시작 ${segmentClock(s)} 이 애니메이션 길이 ${segmentClock(known)} 보다 깁니다` };
  if (known !== null && e > known) return { ...base, note: `끝 ${segmentClock(e)} 이 길이 ${segmentClock(known)} 보다 길어 끝까지 재생합니다` };
  return base;
}

/** 재생 중 진행 글 · `구간 1:20~1:45 · 지금 1:31` · 구간이 아니면 빈 글자 */
export function segmentProgressText(status, elapsed) {
  const start = Number(status?.segment_start_sec) || 0;
  const end = Number(status?.segment_end_sec) || 0;
  const label = segmentLabel(start, end);
  if (!label) return '';
  const now = start + Math.max(Number(elapsed) || 0, 0);
  return `${label} · 지금 ${segmentClock(end > 0 ? Math.min(now, end) : now)}`;
}
