/** UI v2 · 스케줄 화면이 보는 값 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 스케줄)
 *
 * 시각은 이 PC 시각 · 끝이 시작보다 이르면 다음 날 그 시각까지(22:00 – 02:00) · 서버 엔진과 같은 규칙.
 * 두 단계 · 1단계 특정일(특정일 운영 `once` · 휴무일 `holiday`) · 2단계 정기 운영(매일 · 요일) ·
 * 특정일이 있는 날짜는 정기 운영 대신 특정일만 · 휴무일이 같은 날짜의 특정일 운영보다 우선 (수정 목록 218).
 */
import { DAY_CODES, isDated, scheduleDay, toMinutes, ymdOf } from './model.js';

/** 월요일부터 · 화면 순서 */
export const WEEK = [
  ['MON', '월'], ['TUE', '화'], ['WED', '수'], ['THU', '목'], ['FRI', '금'], ['SAT', '토'], ['SUN', '일'],
];
const DAY_LABEL = Object.fromEntries(WEEK);

/** 편집 「구분」 · 저장 값과 화면 이름 */
export const KINDS = [['regular', '정기 운영'], ['date', '특정일 운영'], ['holiday', '휴무일']];

const ymd = ymdOf;

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
  const base = (item) => ({ id: String(item.schedule_id || ''), name: String(item.schedule_name || '스케줄') });
  for (const item of scheduleDay(items, date).items) {
    const s = span(item);
    if (s) out.push({ ...base(item), start: s.start, end: s.end > s.start ? s.end : 1440 });
  }
  for (const item of scheduleDay(items, prev).items) {
    const s = span(item);
    if (s && s.end < s.start) out.push({ ...base(item), start: 0, end: s.end, carried: true });
  }
  return out.sort((a, b) => a.start - b.start);
}

/** 이번 주 · 월요일부터 7일 · [{code, label, date, today, windows, tag}] · tag = 특정일 · 휴무일 · '' */
export function weekRows(items, now = new Date()) {
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7));
  return WEEK.map(([code, label], index) => {
    const date = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + index);
    const kind = scheduleDay(items, date).kind;
    return {
      code, label, date, today: ymd(date) === ymd(now), windows: dayWindows(items, date),
      tag: kind === 'holiday' ? '휴무일' : kind === 'date' ? '특정일' : '',
    };
  });
}

/** 「2026-11-18」 → 그날 0시(이 PC 시각) · 못 읽으면 null */
function dateOf(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

/** 「2026-11-18 (수)」 · 못 읽으면 그대로 */
export function dateText(value) {
  const date = dateOf(value);
  if (!date) return String(value || '날짜 없음');
  return `${value} (${DAY_LABEL[DAY_CODES[date.getDay()]]})`;
}

export function kindOf(item) {
  if (isDated(item)) return item.repeat_type === 'holiday' ? 'holiday' : 'date';
  return 'regular';
}

/** 「매일」 · 「금 · 토」 · 「특정일 · 2026-11-18 (수)」 · 「휴무일 · 2026-11-26 (목)」 */
export function repeatText(item) {
  const type = String(item?.repeat_type || 'daily');
  if (type === 'holiday') return `휴무일 · ${dateText(item.run_date)}`;
  if (type === 'once') return `특정일 · ${dateText(item.run_date)}`;
  if (type === 'weekly') {
    const days = WEEK.map(([code]) => code).filter((code) => (item.repeat_days || []).includes(code));
    if (days.length === 7) return '매일';
    return days.length ? days.map((code) => DAY_LABEL[code]).join(' · ') : '요일 없음';
  }
  return '매일';
}

export function timeText(item) {
  if (String(item?.repeat_type || '') === 'holiday') return '';
  const start = String(item?.start_time || '').slice(0, 5);
  const stop = String(item?.stop_time || '').slice(0, 5);
  const s = item ? span(item) : null;
  return `${start} – ${stop}${s && s.end < s.start ? ' (다음 날)' : ''}`;
}

/** 목록 두 묶음 · 특정일(오늘 · 다가올 날짜 순 → 지난 날짜 최근 순) · 정기 운영(저장 순) */
export function scheduleGroups(items, now = new Date()) {
  const list = (Array.isArray(items) ? items : []).filter(Boolean);
  const today = ymd(now);
  const dated = list.filter(isDated);
  const coming = dated.filter((item) => item.run_date >= today).sort((a, b) => a.run_date.localeCompare(b.run_date));
  const past = dated.filter((item) => item.run_date < today).sort((a, b) => b.run_date.localeCompare(a.run_date));
  return { dated: [...coming, ...past], regular: list.filter((item) => !isDated(item)) };
}

/** 특정일 줄 옆 짧은 상태 · 지난 날짜 · 휴무일 우선 · 오늘 적용 · 없으면 '' */
export function datedNote(item, items, now = new Date()) {
  if (!isDated(item)) return '';
  const today = ymd(now);
  if (item.run_date < today) return '지난 날짜';
  const date = dateOf(item.run_date);
  if (item.enabled === false || !date) return '';
  if (item.repeat_type === 'once' && scheduleDay(items, date).kind === 'holiday') return '같은 날짜의 휴무일 우선 적용';
  if (item.run_date === today && item.repeat_type === 'holiday') return '오늘 적용';
  return '';
}

/** 편집 칸 · 새것은 정기 운영 10:00 – 18:00 매일 */
export function draftFrom(item, today = new Date()) {
  const kind = item ? kindOf(item) : 'regular';
  return {
    id: String(item?.schedule_id || ''),
    name: String(item?.schedule_name || ''),
    kind,
    start: String(item?.start_time || '10:00:00').slice(0, 5),
    stop: String(item?.stop_time || '18:00:00').slice(0, 5),
    repeat: item?.repeat_type === 'weekly' ? 'weekly' : 'daily',
    days: Array.isArray(item?.repeat_days) && item.repeat_type === 'weekly' ? [...item.repeat_days] : [],
    date: String(item?.run_date || ymd(today)),
    enabled: item ? item.enabled !== false : true,
  };
}

/** 저장 전 검사 · 글 하나 · 비면 저장해도 된다 · items = 저장된 목록(같은 날짜 겹침 검사) */
export function draftProblem(draft, items = []) {
  const kind = draft.kind || 'regular';
  if (kind !== 'holiday') {
    if (toMinutes(draft.start) === null) return '시작 시각을 입력하세요';
    if (toMinutes(draft.stop) === null) return '종료 시각을 입력하세요';
    if (toMinutes(draft.start) === toMinutes(draft.stop)) return '시작 시각과 종료 시각이 같습니다';
  }
  if (kind === 'regular') return draft.repeat === 'weekly' && !draft.days.length ? '요일을 하나 이상 선택하세요' : '';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.date)) return '날짜를 선택하세요';
  const same = (Array.isArray(items) ? items : [])
    .filter((item) => item && isDated(item) && item.run_date === draft.date && String(item.schedule_id || '') !== draft.id);
  if (same.some((item) => item.repeat_type === 'holiday')) return '해당 날짜는 이미 휴무일입니다';
  if (kind === 'holiday' && same.length) return '해당 날짜에 특정일 운영이 있습니다';
  return '';
}

/** 서버 저장 모양 · 기존 화면과 같은 칸 (정지는 지정 시각 하나 · §6-137) · 휴무일은 시각 없음 */
export function draftPayload(draft) {
  const kind = draft.kind || 'regular';
  const repeat = kind === 'holiday' ? 'holiday' : kind === 'date' ? 'once' : draft.repeat;
  const fallback = kind === 'holiday' ? '휴무일' : kind === 'date' ? '특정일 운영' : '새 스케줄';
  const payload = {
    schedule_name: draft.name.trim() || fallback,
    start_time: kind === 'holiday' ? null : `${draft.start.slice(0, 5)}:00`,
    stop_mode: 'time',
    stop_time: kind === 'holiday' ? null : `${draft.stop.slice(0, 5)}:00`,
    duration_sec: null,
    repeat_type: repeat,
    repeat_days: repeat === 'weekly' ? WEEK.map(([code]) => code).filter((code) => draft.days.includes(code)) : WEEK.map(([code]) => code),
    run_date: kind === 'regular' ? null : draft.date,
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
  return `${[...stamps].sort().join(', ')} 시간대에서 만든 스케줄입니다. 현재 시간대(${now}) 기준으로 시각을 확인하세요.`;
}

/** 슬레이브면 마스터 화면 주소 · 같은 망 표에서 */
export function masterLink(snap) {
  const pcs = snap?.coordination?.runtime?.network_pcs;
  const master = (Array.isArray(pcs) ? pcs : []).find((pc) => pc.is_master && !pc.is_local);
  if (!master) return null;
  const url = String(master.web_url || '');
  return { name: String(master.display_name || master.pc_id || '마스터'), url: /^https?:\/\/[^\s"'<>]+$/.test(url) ? `${url}/v2#/schedule` : '' };
}
