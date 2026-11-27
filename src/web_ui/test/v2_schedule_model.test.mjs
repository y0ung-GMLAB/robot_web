/** UI v2 · 스케줄 화면 값 · 이번 주 · 자정 넘김 · 편집 검사 · 저장 모양 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  dateText, datedNote, dayWindows, draftFrom, draftPayload, draftProblem, masterLink, repeatText, scheduleGroups,
  timeText, timezoneDrift, weekRows,
} from '../static/v2/js/schedule_model.js';
import { scheduleDay, todayWindows } from '../static/v2/js/model.js';

const night = { schedule_id: 'n', schedule_name: '밤', start_time: '22:00:00', stop_time: '02:00:00', repeat_type: 'weekly', repeat_days: ['WED'] };
const day = { schedule_id: 'd', schedule_name: '낮', start_time: '10:00:00', stop_time: '18:00:00', repeat_type: 'daily' };

test('그날 구간 · 자정 넘김은 다음 날 아침 몫까지 · 꺼진 것은 없음', () => {
  const wed = new Date(2026, 9, 14);
  const thu = new Date(2026, 9, 15);
  assert.deepEqual(dayWindows([night, day], wed).map((w) => [w.id, w.start, w.end]), [['d', 600, 1080], ['n', 1320, 1440]]);
  assert.deepEqual(dayWindows([night], thu).map((w) => [w.start, w.end, w.carried]), [[0, 120, true]]);
  assert.deepEqual(dayWindows([{ ...day, enabled: false }], wed), []);
  assert.deepEqual(dayWindows([{ ...day, stop_time: '10:00:00' }], wed), [], '시작 = 끝은 구간 없음');
});

test('이번 주 · 월요일부터 · 오늘 표시', () => {
  const rows = weekRows([day], new Date(2026, 9, 18, 9));
  assert.deepEqual(rows.map((r) => r.label), ['월', '화', '수', '목', '금', '토', '일']);
  assert.equal(rows.findIndex((r) => r.today), 6, '2026-10-18 은 일요일');
  assert.equal(rows[0].date.getDate(), 12);
});

test('반복 · 시각 글', () => {
  assert.equal(repeatText(day), '매일');
  assert.equal(repeatText({ repeat_type: 'weekly', repeat_days: ['SAT', 'FRI'] }), '금 · 토');
  assert.equal(repeatText({ repeat_type: 'once', run_date: '2026-10-20' }), '특정일 · 2026-10-20 (화)');
  assert.equal(repeatText({ repeat_type: 'holiday', run_date: '2026-11-26' }), '휴무일 · 2026-11-26 (목)');
  assert.equal(timeText({ repeat_type: 'holiday', run_date: '2026-11-26' }), '', '휴무일은 시각 없음');
  assert.equal(timeText(night), '22:00 – 02:00 (다음 날)');
  assert.equal(timeText(day), '10:00 – 18:00');
});

test('편집 · 검사 · 저장 모양은 기존 화면과 같은 칸', () => {
  const draft = draftFrom(null, new Date(2026, 9, 12));
  assert.deepEqual([draft.kind, draft.start, draft.stop, draft.repeat, draft.date], ['regular', '10:00', '18:00', 'daily', '2026-10-12']);
  assert.equal(draftProblem({ ...draft, stop: '10:00' }), '시작 시각과 종료 시각이 같습니다');
  assert.equal(draftProblem({ ...draft, repeat: 'weekly', days: [] }), '요일을 하나 이상 선택하세요');
  assert.equal(draftProblem(draft), '');
  const payload = draftPayload({ ...draftFrom(night), name: '  밤 ', days: ['THU', 'WED'] });
  assert.deepEqual(payload, {
    schedule_name: '밤', start_time: '22:00:00', stop_mode: 'time', stop_time: '02:00:00', duration_sec: null,
    repeat_type: 'weekly', repeat_days: ['WED', 'THU'], run_date: null, enabled: true, schedule_id: 'n',
  });
  assert.equal(draftPayload(draft).repeat_days.length, 7);
  assert.equal(draftPayload(draft).schedule_id, undefined, '새것은 id 없이');
});

test('시간대 어긋남 · 슬레이브의 마스터 주소', () => {
  assert.equal(timezoneDrift([{ saved_timezone: 'Asia/Seoul' }], 'Asia/Seoul'), '');
  assert.match(timezoneDrift([{ saved_timezone: 'Asia/Seoul' }], 'Europe/Paris'), /Asia\/Seoul 시간대에서 만든/);
  const snap = { coordination: { runtime: { network_pcs: [{ pc_id: 'f4', is_master: true, web_url: 'http://192.168.0.14:8000' }] } } };
  assert.deepEqual(masterLink(snap), { name: 'f4', url: 'http://192.168.0.14:8000/v2#/schedule' });
  assert.equal(masterLink({ coordination: { runtime: { network_pcs: [{ is_master: true, web_url: 'javascript:x' }] } } }).url, '');
});

/* ---------- 수정 목록 218 · 특정일(특정일 운영 · 휴무일)이 그날 정기 운영보다 우선 · 2026-11-18 은 수요일 ---------- */

const wed = { schedule_id: 'wed', schedule_name: '정기', start_time: '10:00:00', stop_time: '20:00:00', repeat_type: 'weekly', repeat_days: ['WED'] };
const special = { schedule_id: 'sp', schedule_name: '특정일', start_time: '09:00:00', stop_time: '18:00:00', repeat_type: 'once', run_date: '2026-11-18' };
const closed = { schedule_id: 'h', schedule_name: '추수감사절', start_time: null, stop_time: null, repeat_type: 'holiday', run_date: '2026-11-26' };

test('특정일이 있는 날은 정기 운영 대신 · 휴무일은 없음 · 서버와 같은 규칙', () => {
  const nov18 = new Date(2026, 10, 18);
  assert.deepEqual(dayWindows([wed, special], nov18).map((w) => [w.id, w.start, w.end]), [['sp', 540, 1080]]);
  assert.deepEqual(dayWindows([wed, special], new Date(2026, 10, 25)).map((w) => w.id), ['wed'], '다음 주 수요일은 정기 운영');
  assert.equal(scheduleDay([wed, special], nov18).kind, 'date');
  assert.deepEqual(scheduleDay([day, closed], new Date(2026, 10, 26)), { kind: 'holiday', items: [] });
  assert.deepEqual(todayWindows([day, closed], new Date(2026, 10, 26, 9)), []);
  assert.equal(scheduleDay([{ ...special, run_date: '2026-11-26' }, closed], new Date(2026, 10, 26)).kind, 'holiday', '같은 날짜면 휴무일 우선');
  assert.equal(scheduleDay([{ ...closed, enabled: false }, day], new Date(2026, 10, 26)).kind, 'regular', '꺼 둔 휴무일은 없는 것');
});

test('자정 넘김은 시작한 날짜 기준 · 다음 날이 휴무일이어도 전날 밤 몫은 그대로', () => {
  const tueNight = { ...night, schedule_id: 'tn', repeat_days: ['TUE', 'WED'] };
  const holiday18 = { ...closed, run_date: '2026-11-18' };
  const rows = dayWindows([tueNight, holiday18], new Date(2026, 10, 18));
  assert.deepEqual(rows.map((w) => [w.id, w.start, w.end, Boolean(w.carried)]), [['tn', 0, 120, true]], '수요일 밤 구간은 빠짐');
});

test('이번 주 표시 · 특정일 · 휴무일 날짜에 표시', () => {
  const rows = weekRows([wed, special, closed], new Date(2026, 10, 18, 9));
  assert.deepEqual(rows.map((r) => r.tag), ['', '', '특정일', '', '', '', '']);
  const next = weekRows([wed, special, closed], new Date(2026, 10, 24, 9));
  assert.equal(next[3].tag, '휴무일');
  assert.deepEqual(next[3].windows, []);
});

test('목록 두 묶음 · 다가올 날짜 순 · 지난 날짜는 아래 · 상태 글', () => {
  const old = { ...special, schedule_id: 'old', run_date: '2026-11-01' };
  const groups = scheduleGroups([wed, closed, old, special, day], new Date(2026, 10, 17, 12));
  assert.deepEqual(groups.dated.map((i) => i.schedule_id), ['sp', 'h', 'old']);
  assert.deepEqual(groups.regular.map((i) => i.schedule_id), ['wed', 'd']);
  assert.equal(datedNote(old, [old], new Date(2026, 10, 17)), '지난 날짜');
  const clash = { ...special, run_date: '2026-11-26' };
  assert.equal(datedNote(clash, [clash, closed], new Date(2026, 10, 17)), '같은 날짜의 휴무일 우선 적용');
  assert.equal(datedNote(closed, [closed], new Date(2026, 10, 26, 10)), '오늘 적용');
  assert.equal(datedNote(wed, [wed], new Date(2026, 10, 17)), '');
  assert.equal(dateText('2026-11-18'), '2026-11-18 (수)');
});

test('편집 · 휴무일은 시각 없이 저장 · 같은 날짜 겹침 막음', () => {
  const draft = { ...draftFrom(null, new Date(2026, 10, 17)), kind: 'holiday', date: '2026-11-26', start: '', stop: '' };
  assert.equal(draftProblem(draft), '', '휴무일은 시각 검사 없음');
  assert.deepEqual(draftPayload(draft), {
    schedule_name: '휴무일', start_time: null, stop_mode: 'time', stop_time: null, duration_sec: null,
    repeat_type: 'holiday', repeat_days: ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'], run_date: '2026-11-26', enabled: true,
  });
  assert.equal(draftProblem(draft, [closed]), '해당 날짜는 이미 휴무일입니다');
  assert.equal(draftProblem(draft, [{ ...special, run_date: '2026-11-26' }]), '해당 날짜에 특정일 운영이 있습니다');
  assert.equal(draftProblem({ ...draftFrom(closed), name: '추수감사절' }, [closed]), '', '자기 자신은 겹침 아님');
  const date = { ...draftFrom(special), kind: 'date', date: '2026-11-26' };
  assert.equal(draftProblem(date, [closed]), '해당 날짜는 이미 휴무일입니다');
  assert.equal(draftPayload({ ...draftFrom(special), name: '' }).repeat_type, 'once');
  assert.equal(draftPayload({ ...draftFrom(special), name: '' }).schedule_name, '특정일 운영');
  assert.equal(draftPayload({ ...draftFrom(special) }).run_date, '2026-11-18');
  assert.deepEqual([draftFrom(closed).kind, draftFrom(special).kind, draftFrom(wed).kind], ['holiday', 'date', 'regular']);
  assert.equal(draftProblem({ ...draftFrom(special), date: '' }), '날짜를 선택하세요');
});
