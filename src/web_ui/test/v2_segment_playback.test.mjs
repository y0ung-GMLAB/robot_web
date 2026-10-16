/** UI v2 · 구간 재생 · 입력 검사 · 진행 글 · 3D 파일 시각 · 기록 줄 (2026-10-16) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  parseClock, segmentCheck, segmentClock, segmentLabel, segmentProgressText,
} from '../static/v2/js/segment_model.js';
import { runSummary } from '../static/v2/js/model.js';
import { playHeadline } from '../static/v2/js/play_model.js';
import { runRows } from '../static/v2/js/records_model.js';
import { followPlayheadSec, followRestSec } from '../static/js/sim3d_math.js';

test('시각 글 · 서버(motion_segment.format_time)와 같은 모양 · 0.1 초', () => {
  assert.equal(segmentClock(80), '1:20');
  assert.equal(segmentClock(80.5), '1:20.5');
  assert.equal(segmentClock(0), '0:00');
  assert.equal(segmentClock(160), '2:40');
  assert.equal(segmentClock(59.96), '1:00');
});

test('입력 읽기 · m:ss · m:ss.s · 초만 · 빈 칸 = null · 틀린 모양 = NaN', () => {
  assert.equal(parseClock('1:20'), 80);
  assert.equal(parseClock(' 1:20.5 '), 80.5);
  assert.equal(parseClock('95'), 95);
  assert.equal(parseClock('7.5'), 7.5);
  assert.equal(parseClock('1:02:03'), 3723);
  assert.equal(parseClock(''), null);
  assert.equal(parseClock(undefined), null);
  for (const bad of ['1:75', 'abc', '-3', '1::2', '1:2:3:4', '1,5']) assert.ok(Number.isNaN(parseClock(bad)), bad);
});

test('검사 · 비우면 통째로 · 끝만 적으면 처음부터 · 틀리면 이유', () => {
  assert.deepEqual(segmentCheck({}), { active: false, start: 0, end: 0, payload: null, error: '', note: '' });
  const ok = segmentCheck({ startText: '1:20', endText: '1:45', length: 160 });
  assert.deepEqual(ok.payload, { start_sec: 80, end_sec: 105 });
  assert.equal(ok.error, '');
  assert.deepEqual(segmentCheck({ endText: '0:30', length: 160 }).payload, { start_sec: 0, end_sec: 30 });
  assert.deepEqual(segmentCheck({ startText: '1:20', length: 160 }).payload, { start_sec: 80, end_sec: 0 });

  const late = segmentCheck({ startText: '3:12', length: 160 });
  assert.equal(late.payload, null);
  assert.equal(late.error, '구간 시작 3:12 이 애니메이션 길이 2:40 보다 깁니다');
  assert.equal(segmentCheck({ startText: '2:40', length: 160 }).payload, null, '길이와 같아도 재생할 것이 없다');

  const backwards = segmentCheck({ startText: '1:20', endText: '1:10' });
  assert.equal(backwards.error, '구간 끝 1:10 이 구간 시작 1:20 보다 뒤여야 합니다');
  assert.match(segmentCheck({ startText: 'x' }).error, /m:ss/);
  assert.match(segmentCheck({ endText: '1:99' }).error, /끝까지면 비우세요/);

  const long = segmentCheck({ startText: '1:00', endText: '9:00', length: 160 });
  assert.deepEqual(long.payload, { start_sec: 60, end_sec: 540 }, '끝이 길면 막지 않는다 · 서버가 끝까지');
  assert.match(long.note, /끝까지/);
  assert.equal(segmentCheck({ startText: '3:12', length: null }).error, '', '길이를 모르면(그룹) 모양만 본다');
});

test('구간 글 · 진행 글은 파일 시각 · 끝을 넘지 않는다', () => {
  assert.equal(segmentLabel(80, 105), '구간 1:20~1:45');
  assert.equal(segmentLabel(80, 0), '구간 1:20~끝');
  assert.equal(segmentLabel(0, 0), '');
  assert.equal(segmentLabel(0, 30), '구간 0:00~0:30');
  assert.equal(segmentProgressText({ segment_start_sec: 80, segment_end_sec: 105 }, 11), '구간 1:20~1:45 · 지금 1:31');
  assert.equal(segmentProgressText({ segment_start_sec: 80, segment_end_sec: 105 }, 40), '구간 1:20~1:45 · 지금 1:45');
  assert.equal(segmentProgressText({}, 11), '');
});

test('지금 칸 · 진행 시각 옆에 구간과 파일 시각 · 머리에 구간', () => {
  const status = {
    state: 'running', motion_file_id: 'narration.json', current_cycle: 1, run_mode: 'once',
    segment_start_sec: 80, segment_end_sec: 105, progress: { elapsed_sec: 11, duration_sec: 25 },
  };
  assert.equal(runSummary({ motion_run_status: status }).timeText, '00:11 / 00:25 · 구간 1:20~1:45 · 지금 1:31');
  assert.equal(runSummary({ motion_run_status: { ...status, segment_start_sec: 0, segment_end_sec: 0 } }).timeText, '00:11 / 00:25');
  assert.match(playHeadline({ motion_run_status: status }).detail, /구간 1:20~1:45/);
  assert.doesNotMatch(playHeadline({ motion_run_status: { ...status, segment_start_sec: 0, segment_end_sec: 0 } }).detail, /구간/);
});

test('3D 따라가기 · 진행 시각에 구간 시작을 더한 파일 시각 · 쉬는 중엔 구간 시작 자세', () => {
  const status = { state: 'running', progress: { elapsed_sec: 11 }, updated_at: 1000, segment_start_sec: 80 };
  assert.equal(followPlayheadSec(status, 1000.5, 0), 91.5);
  assert.equal(followPlayheadSec({ ...status, segment_start_sec: 0 }, 1000.5, 0), 11.5);
  assert.equal(followPlayheadSec({ ...status, state: 'initialized' }, 1000, 0), null);
  assert.equal(followRestSec({ state: 'initialized', segment_start_sec: 80 }), 80);
  assert.equal(followRestSec({}), 0);
});

test('기록 줄 · 구간 재생이면 애니메이션 옆에 구간', () => {
  const [row] = runRows([{ file: 'a.csv', motion_file_id: 'narration.json', segment_start_sec: 80, segment_end_sec: 105, result: 'completed', axes: [] }]);
  assert.equal(row.motion, 'narration · 구간 1:20~1:45');
  const [whole] = runRows([{ file: 'b.csv', motion_file_id: 'narration.json', result: 'completed', axes: [] }]);
  assert.equal(whole.motion, 'narration');
});

test('재생 화면 · 구간 줄 · 단독·그룹 모두 시작 요청에 실음 · 지난 구간은 브라우저 기억(try/catch)', () => {
  const source = readFileSync(new URL('../static/v2/js/pages/play.js', import.meta.url), 'utf8');
  assert.match(source, /segmentRow\(seg, group, running, changed\)/);
  assert.match(source, /act\.startGroup\(\{[^}]*\.\.\.\(segment \? \{ segment \} : \{\}\) \}\)/);
  assert.match(source, /act\.initializeGroup\(\{[^}]*\.\.\.\(segment \? \{ segment \} : \{\}\) \}\)/);
  // 누르는 순간 칸 값으로 다시 검사 · 칸에 커서가 있으면 다시 그리지 않아 그린 때 값이 낡는다(적자마자 누르면 통째 재생)
  assert.match(source, /const withSegmentNow = \(send\) => \{\s*const check = segmentState\(state\)\.check;\s*if \(check\.error\)/);
  assert.match(source, /const start = \(runMode\) => withSegmentNow\(/);
  assert.match(source, /const initialize = \(\) => withSegmentNow\(/);
  assert.match(source, /localPayload\(state, runMode, segment\)/);
  assert.match(source, /모든 PC · 스피커가 같은 시각부터/);
  assert.match(source, /try \{ localStorage\.setItem\(SEGMENT_KEY/);
  assert.match(source, /segStart: '',/, '화면을 열 때는 비어 있다');
});
