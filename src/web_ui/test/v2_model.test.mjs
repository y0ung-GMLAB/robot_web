/** UI v2 · 상태 한 문장 · 확인할 일 · 지금 카드 · 오늘 스케줄 (설계안 2026-10-09 · 뼈대 + 홈) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  collectIssues, headline, modePhrase, motorChips, pcRows, runSummary, todayWindows,
} from '../static/v2/js/model.js';

const pcs = (...extra) => ({ coordination: { runtime: { network_pcs: [
  { pc_id: 'floating4', is_local: true, is_master: true, online: true, joined: true },
  ...extra,
] } } });

test('정상이면 한 문장 · 모드와 운영 시간', () => {
  const sched = { run_mode: 'schedule', active_schedule_id: 'a' };
  assert.deepEqual(headline(pcs(), sched).text, '정상 · 자동 운영 중');
  assert.equal(headline(pcs(), { run_mode: 'schedule' }).text, '정상 · 운영 시간 외');
  assert.equal(headline(pcs(), { run_mode: 'manual' }).tone, 'info');
  assert.equal(modePhrase({ run_mode: 'off' }), '끔 · 명령 막힘');
});

test('나쁜 문제가 있으면 그 문제가 한 문장 · 주의만 있으면 개수', () => {
  const snap = { ...pcs({ pc_id: 'floating2', online: true, version_differs: true }),
    minas_absolute_blocker: '0번 모터 Pr0.15=1' };
  const line = headline(snap, { run_mode: 'schedule', active_schedule_id: 'a' });
  assert.equal(line.tone, 'bad');
  assert.match(line.text, /앱솔루트 미확인/);
  assert.equal(line.issues[0].action.kind, 'open');
  const warnOnly = headline(pcs({ pc_id: 'floating2', online: true, version_differs: true }), { run_mode: 'schedule', active_schedule_id: 'a' });
  assert.equal(warnOnly.tone, 'warn');
  assert.equal(warnOnly.text, '자동 운영 중 · 확인할 일 1개');
  assert.equal(warnOnly.issues[0].action.kind, 'update-all');
});

test('문제마다 해결 버튼 · 긴급 정지 · 알람 · 그룹 오류 · 스케줄 거부 · 연결 끊김', () => {
  const snap = {
    ...pcs({ pc_id: 'floating2', online: false }),
    safety_status: { emergency_latched: true },
    motion_state: { motors: [{ controller_index: 2, fault: true, error_code: 'Err16.0' }] },
  };
  snap.coordination.runtime.coordination_error = { active: true, message: '회차 실패' };
  const kinds = collectIssues(snap, { last_failure: { count: 3, message: '피어 없음' } }).map((i) => i.action?.kind || i.title);
  assert.deepEqual(kinds.slice(0, 3), ['restart-program', 'fault-reset', 'ack-group-error']);
  assert.ok(kinds.includes('스케줄 시작 거부 3회'));
  assert.ok(kinds.some((k) => /floating2 연결 안 됨/.test(k)));
  assert.equal(collectIssues(snap, {}, { connected: false }).length, 1, '연결이 끊기면 그것 하나만');
});

test('지금 카드 · 재생 중이면 파일 · 회차 · 진행 · 매장 전체', () => {
  const run = runSummary({ motion_run_status: { state: 'running', motion_file_id: 'narration.json', current_cycle: 3,
    run_mode: 'continuous', group_execution: true, progress: { elapsed_sec: 256, duration_sec: 556 } },
  coordination: { runtime: { execution: { participants: ['a', 'b', 'c', 'd'] } } } });
  assert.equal(run.title, 'narration 재생 중');
  assert.equal(run.subtitle, '매장 전체 4대 · 3회차 · 연속');
  assert.equal(run.timeText, '04:16 / 09:16');
  assert.ok(run.moving && Math.abs(run.ratio - 256 / 556) < 1e-9);
  assert.equal(runSummary({ motion_run_status: { state: 'idle' } }).title, '서 있음');
  assert.equal(runSummary({}).moving, false);
});

test('모터 · 조인트 값이 있으면 조인트 deg · 알람·서보 꺼짐', () => {
  const chips = motorChips({ motion_state: { motors: [
    { controller_index: 0, name: '눈 상하', motion_actual_rad: Math.PI / 180 * 2.31, servo_on: true, torque_percent: 18 },
    { controller_index: 1, name: '눈 좌우', position_rad: -Math.PI / 180 * 80.4, servo_on: false },
    { controller_index: 2, fault: true, error_code: 'Err16.0' },
  ] } });
  assert.deepEqual(chips.map((c) => [c.value, c.unit, c.tone, c.note]), [
    ['+2.31°', '조인트', 'ok', '부하 18%'], ['−80.40°', '모터', 'warn', '서보 꺼짐'], ['-', '모터', 'bad', '알람 Err16.0'],
  ]);
});

test('매장 PC 줄 · 연결 안 됨 · 버전 다름 · 그룹 참여 꺼짐', () => {
  const rows = pcRows(pcs({ pc_id: 'f1', online: false }, { pc_id: 'f2', version_differs: true }, { pc_id: 'f3', joined: false }, { pc_id: 'sp', role: 'speaker' }));
  assert.deepEqual(rows.map((r) => r.note), ['마스터', '연결 안 됨', '버전 다름', '그룹 참여 꺼짐', '스피커']);
  assert.equal(rows[0].local, true);
});

test('오늘 스케줄 · 매일 · 요일 · 한 번 · 자정 넘김 · 꺼진 것', () => {
  const thursday = new Date(2026, 9, 8, 14, 32);
  const items = [
    { schedule_name: '매장', start_time: '10:00:00', stop_time: '18:00:00', repeat_type: 'daily' },
    { schedule_name: '금토', start_time: '19:00:00', stop_time: '21:00:00', repeat_type: 'weekly', repeat_days: ['FRI', 'SAT'] },
    { schedule_name: '오늘만', start_time: '22:00:00', stop_time: '02:00:00', repeat_type: 'once', run_date: '2026-10-08' },
    { schedule_name: '꺼짐', start_time: '08:00:00', stop_time: '09:00:00', repeat_type: 'daily', enabled: false },
  ];
  assert.deepEqual(todayWindows(items, thursday).map((w) => [w.name, w.start, w.end]), [
    ['매장', 600, 1080], ['오늘만', 1320, 1440],
  ]);
});

test('새 UI 는 기존 화면 코드를 가져다 쓰지 않는다 · 따로 선다', () => {
  for (const file of ['main.js', 'shell.js', 'net.js', 'actions.js', 'play_model.js', 'pages/home.js', 'pages/play.js']) {
    const text = readFileSync(new URL(`../static/v2/js/${file}`, import.meta.url), 'utf8');
    assert.doesNotMatch(text, /from '\.\.\/(\.\.\/)?js\//, file);
    assert.doesNotMatch(text, /innerHTML/, `${file} · 글은 textContent 로`);
  }
});
