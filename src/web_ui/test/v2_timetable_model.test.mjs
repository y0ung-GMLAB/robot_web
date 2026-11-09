/** UI v2 · 시간표 재생 · 재생 방식 · 다음 회차 · PC 별 시계 차이 (수정 목록 186 · 2026-11-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { clockOffsetText, groupRows, timetableView } from '../static/v2/js/play_model.js';

const snap = (timetable, extra = {}) => ({
  coordination: {
    config: { is_master: true, enabled: true },
    runtime: {
      joined: true, execution: {}, timetable,
      local: { pc_id: 'f1', display_name: 'floating1' },
      peers: [{ pc_id: 'f2', display_name: 'floating2', state: 'online' }],
      ...extra,
    },
  },
});

test('옛 서버 · 시간표 칸 없음 · 신호 재생으로 보인다', () => {
  const view = timetableView({ coordination: { runtime: {} } });
  assert.equal(view.known, false);
  assert.equal(view.clock, false);
  assert.equal(view.nextText, '');
});

test('시간표 재생 · 다음 회차 · 자동 간격 글자', () => {
  const view = timetableView(snap({ mode: 'clock', auto_period_sec: 930, next_cycle: 4, next_start_unix: 1_700_000_000 }));
  assert.equal(view.clock, true);
  assert.equal(view.autoText, '자동 930 s');
  assert.match(view.nextText, /^다음 4회차 · \d\d:\d\d:\d\d$/);
  const waiting = timetableView(snap({ mode: 'clock', reason: '운영시간 아님' }));
  assert.equal(waiting.reason, '운영시간 아님', '다음 회차가 없으면 이유');
  assert.equal(timetableView(snap({ mode: 'clock' })).autoText, '자동 · 애니메이션 길이 확인 중');
});

test('시계 차이 글자 · 부호 · 모르면 빈 글자', () => {
  assert.equal(clockOffsetText(12.4), '시계 +12 ms');
  assert.equal(clockOffsetText(-130), '시계 -130 ms');
  assert.equal(clockOffsetText(null), '');
  assert.equal(clockOffsetText(undefined), '');
});

test('PC 줄 · 시간표 재생이면 시계 차이 칸 · 100 ms 넘으면 노랑 · 쉬는 이유를 상태로', () => {
  const rows = groupRows(snap({
    mode: 'clock',
    peers: { f2: { clock_offset_ms: -140, clock_warning: true, run: { note: '3회차 쉼 · 다른 재생 중' } } },
    local: { note: '' },
  }));
  const f2 = rows.find((row) => row.id === 'f2');
  assert.equal(f2.clock, '시계 -140 ms');
  assert.equal(f2.clockWarn, true);
  assert.equal(f2.tone, 'warn');
  assert.equal(f2.note, '3회차 쉼 · 다른 재생 중');
  const signal = groupRows(snap({ mode: 'lockstep', peers: { f2: { clock_offset_ms: -140 } } }));
  assert.equal(signal.find((row) => row.id === 'f2').clock, '', '신호 재생에서는 빈 칸(자리는 그대로)');
});

test('시간대가 마스터와 다르면 PC 줄 노랑 · 확인할 일 · 시계 차이 100 ms 초과도 (수정 목록 186)', async () => {
  const { timetableNotices } = await import('../static/v2/js/model.js');
  const state = snap({
    mode: 'clock', master_timezone: 'America/New_York', local_timezone: 'America/New_York', local_timezone_mismatch: false,
    peers: { f2: { timezone: 'Asia/Seoul', timezone_mismatch: true, clock_offset_ms: 4 } },
    timezone_mismatches: ['f2'], clock_warnings: ['f2'], clock_warn_ms: 100,
  });
  const f2 = groupRows(state).find((row) => row.id === 'f2');
  assert.equal(f2.clock, '시간대 다름');
  assert.equal(f2.clockWarn, true);
  const notices = timetableNotices(state);
  assert.equal(notices.length, 2);
  assert.match(notices[0].title, /floating2 시계 차이 100 ms 초과/);
  assert.match(notices[1].title, /floating2 시간대가 마스터와 다름/);
  assert.match(notices[1].detail, /America\/New_York/);
  assert.deepEqual(timetableNotices(snap({ mode: 'lockstep', clock_warnings: ['f2'] })), [], '신호 재생이면 없음');
  const own = timetableNotices(snap({ mode: 'clock', local_timezone_mismatch: true, master_timezone: 'America/New_York' }));
  assert.match(own[0].title, /floating1 시간대가 마스터와 다름/, '이 PC 도');
});

test('시간표 방식이어도 직접 누른 그룹 재생(신호 재생)이 돌면 시간표 쉬는 이유를 PC 줄에 안 씀 (2026-11-09)', () => {
  const tt = { mode: 'clock', reason: '마스터 스케줄 꺼짐', peers: { f2: { run: { note: '마스터 스케줄 꺼짐' } } }, local: { note: '' } };
  const signal = snap(tt, { execution: { execution_id: 'exec-1', excluded: {}, joining: {} } });
  assert.equal(timetableView(signal).signalRun, true);
  assert.equal(groupRows(signal).find((row) => row.id === 'f2').note, '그룹 대기');
  const held = snap(tt, { execution: { execution_id: 'tt-s1700000000' } });
  assert.equal(timetableView(held).signalRun, false, '시간표 실행은 신호 재생이 아님');
  assert.equal(groupRows(held).find((row) => row.id === 'f2').note, '마스터 스케줄 꺼짐');
});
