/** UI v2 · 스케줄 화면 값 · 이번 주 · 자정 넘김 · 편집 검사 · 저장 모양 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  dayWindows, draftFrom, draftPayload, draftProblem, masterLink, repeatText, timeText, timezoneDrift, weekRows,
} from '../static/v2/js/schedule_model.js';

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
  assert.equal(repeatText({ repeat_type: 'once', run_date: '2026-10-20' }), '한 번 · 2026-10-20');
  assert.equal(timeText(night), '22:00 – 02:00 (다음 날)');
  assert.equal(timeText(day), '10:00 – 18:00');
});

test('편집 · 검사 · 저장 모양은 기존 화면과 같은 칸', () => {
  const draft = draftFrom(null, new Date(2026, 9, 12));
  assert.deepEqual([draft.start, draft.stop, draft.repeat, draft.date], ['10:00', '18:00', 'daily', '2026-10-12']);
  assert.equal(draftProblem({ ...draft, stop: '10:00' }), '시작과 끝이 같습니다');
  assert.equal(draftProblem({ ...draft, repeat: 'weekly', days: [] }), '요일을 하나 이상 고르세요');
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
  assert.match(timezoneDrift([{ saved_timezone: 'Asia/Seoul' }], 'Europe/Paris'), /Asia\/Seoul 에서 만든/);
  const snap = { coordination: { runtime: { network_pcs: [{ pc_id: 'f4', is_master: true, web_url: 'http://192.168.0.14:8000' }] } } };
  assert.deepEqual(masterLink(snap), { name: 'f4', url: 'http://192.168.0.14:8000/v2#/schedule' });
  assert.equal(masterLink({ coordination: { runtime: { network_pcs: [{ is_master: true, web_url: 'javascript:x' }] } } }).url, '');
});
