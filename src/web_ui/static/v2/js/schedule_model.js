/** UI v2 · 스케줄 화면이 보는 값 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 스케줄)
 *
 * 시각은 이 PC 시각 · 끝이 시작보다 이르면 다음 날 그 시각까지(22:00 – 02:00) · 서버 엔진과 같은 규칙.
 */
import { DAY_CODES, toMinutes } from './model.js';

/** 월요일부터 · 화면 순서 */
export const WEEK = [
  ['MON', '월'], ['TUE', '화'], ['WED', '수'], ['THU', '목'], ['FRI', '금'], ['SAT', '토'], ['SUN', '일'],
];
const DAY_LABEL = Object.fromEntries(WEEK);

function ymd(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function runsOn(item, date) {
  if (!item || item.enabled === false) return false;
  const type = String(item.repeat_type || 'daily');
  if (type === 'weekly') return (item.repeat_days || []).includes(DAY_CODES[date.getDay()]);
  if (type === 'once') return item.run_date === ymd(date);
  return true;
}

function span(item) {
  const start = toMinutes(item.start_time);
  let end = toMinutes(item.stop_time);
  if (start === null) return null;
  if (end === null && Number(item.duration_sec) > 0) end = start + Math.round(Number(item.duration_sec) / 60);
  if (end === null || end === start) return null;
  return { start, end };
}

/** 그날 도는 구간 · 전날 밤에 시작해 넘어온 몫도 넣는다 · [{id, name, start, end(분)}] */
export function dayWindows(items, date) {
  const prev = new Date(date.getFullYear(), date.getMonth(), date.getDate() - 1);
  const out = [];
  for (const item of Array.isArray(items) ? items : []) {
    const s = item ? span(item) : null;
    if (!s) continue;
    const base = { id: String(item.schedule_id || ''), name: String(item.schedule_name || '스케줄') };
    if (runsOn(item, date)) out.push({ ...base, start: s.start, end: s.end > s.start ? s.end : 1440 });
    if (s.end < s.start && runsOn(item, prev)) out.push({ ...base, start: 0, end: s.end, carried: true });
  }
  return out.sort((a, b) => a.start - b.start);
}

/** 이번 주 · 월요일부터 7일 · [{code, label, date, today, windows}] */
export function weekRows(items, now = new Date()) {
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7));
  return WEEK.map(([code, label], index) => {
    const date = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + index);
    return { code, label, date, today: ymd(date) === ymd(now), windows: dayWindows(items, date) };
  });
}

/** 「매일」 · 「금 · 토」 · 「한 번 · 2026-10-08」 */
export function repeatText(item) {
  const type = String(item?.repeat_type || 'daily');
  if (type === 'once') return `한 번 · ${item.run_date || '날짜 없음'}`;
  if (type === 'weekly') {
    const days = WEEK.map(([code]) => code).filter((code) => (item.repeat_days || []).includes(code));
    if (days.length === 7) return '매일';
    return days.length ? days.map((code) => DAY_LABEL[code]).join(' · ') : '요일 없음';
  }
  return '매일';
}

export function timeText(item) {
  const start = String(item?.start_time || '').slice(0, 5);
  const stop = String(item?.stop_time || '').slice(0, 5);
  const s = item ? span(item) : null;
  return `${start} – ${stop}${s && s.end < s.start ? ' (다음 날)' : ''}`;
}

/** 편집 칸 · 새것은 10:00 – 18:00 매일 */
export function draftFrom(item, today = new Date()) {
  return {
    id: String(item?.schedule_id || ''),
    name: String(item?.schedule_name || ''),
    start: String(item?.start_time || '10:00:00').slice(0, 5),
    stop: String(item?.stop_time || '18:00:00').slice(0, 5),
    repeat: ['daily', 'weekly', 'once'].includes(item?.repeat_type) ? item.repeat_type : 'daily',
    days: Array.isArray(item?.repeat_days) && item.repeat_type === 'weekly' ? [...item.repeat_days] : [],
    date: String(item?.run_date || ymd(today)),
    enabled: item ? item.enabled !== false : true,
  };
}

/** 저장 전 검사 · 글 하나 · 비면 저장해도 된다 */
export function draftProblem(draft) {
  if (toMinutes(draft.start) === null) return '시작 시각을 입력하세요';
  if (toMinutes(draft.stop) === null) return '종료 시각을 입력하세요';
  if (toMinutes(draft.start) === toMinutes(draft.stop)) return '시작 시각과 종료 시각이 같습니다';
  if (draft.repeat === 'weekly' && !draft.days.length) return '요일을 하나 이상 선택하세요';
  if (draft.repeat === 'once' && !/^\d{4}-\d{2}-\d{2}$/.test(draft.date)) return '날짜를 선택하세요';
  return '';
}

/** 서버 저장 모양 · 기존 화면과 같은 칸 (정지는 지정 시각 하나 · §6-137) */
export function draftPayload(draft) {
  const payload = {
    schedule_name: draft.name.trim() || '새 스케줄',
    start_time: `${draft.start.slice(0, 5)}:00`,
    stop_mode: 'time',
    stop_time: `${draft.stop.slice(0, 5)}:00`,
    duration_sec: null,
    repeat_type: draft.repeat,
    repeat_days: draft.repeat === 'weekly' ? WEEK.map(([code]) => code).filter((code) => draft.days.includes(code)) : WEEK.map(([code]) => code),
    run_date: draft.repeat === 'once' ? draft.date : null,
    enabled: draft.enabled !== false,
  };
  if (draft.id) payload.schedule_id = draft.id;
  return payload;
}

/** 스케줄을 만든 곳의 시간대가 지금 이 PC 와 다르면 · 들고 나간 PC (§6-150) */
export function timezoneDrift(items, timezone) {
  const now = String(timezone || '').trim();
  if (!now) return '';
  const stamps = new Set((Array.isArray(items) ? items : [])
    .filter((item) => item?.enabled !== false)
    .map((item) => String(item?.saved_timezone || '').trim())
    .filter(Boolean));
  stamps.delete(now);
  if (!stamps.size) return '';
  return `${[...stamps].sort().join(', ')} 시간대에서 만든 스케줄인데, 지금 PC 시간대는 ${now}입니다. 시각을 다시 확인하세요.`;
}

/** 슬레이브면 마스터 화면 주소 · 같은 망 표에서 */
export function masterLink(snap) {
  const pcs = snap?.coordination?.runtime?.network_pcs;
  const master = (Array.isArray(pcs) ? pcs : []).find((pc) => pc.is_master && !pc.is_local);
  if (!master) return null;
  const url = String(master.web_url || '');
  return { name: String(master.display_name || master.pc_id || '마스터'), url: /^https?:\/\/[^\s"'<>]+$/.test(url) ? `${url}/v2#/schedule` : '' };
}
