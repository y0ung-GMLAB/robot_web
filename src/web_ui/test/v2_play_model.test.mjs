/** UI v2 · 재생 화면 값 · 시작 막는 이유 · 재생 목록 · 실행 축 · 그룹 PC 줄 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  axisRows, defaultScope, excludedText, fileInfo, groupRows, groupStartPreview, groupStopCommand, initialMoveChoices, phaseSteps, playHeadline, REPEAT_MODES,
  playlistAdd, playlistMove, playlistRemove, registeredPlaylist, repeatChoice, startBlocker,
} from '../static/v2/js/play_model.js';

const group = (extra = {}) => ({ coordination: { config: { is_master: true, enabled: true }, runtime: { joined: true, execution: {}, ...extra } } });

test('범위 · 기본은 단독 · 마스터에서 그룹 실행이 돌고 있을 때만 그룹 전체 (수정 목록 120 (나))', () => {
  assert.equal(defaultScope(group()), 'local', '그룹에 든 마스터라도 처음엔 단독');
  assert.equal(defaultScope(group({ execution: { execution_id: 'exec-1' } })), 'group', '돌고 있는 그룹 실행');
  assert.equal(defaultScope({ coordination: { config: { is_master: false }, runtime: { joined: true, execution: { execution_id: 'e' } } } }), 'local');
  assert.equal(defaultScope({}), 'local');
});

test('회차 사이 · 늘 하나 골라짐 · 모르는 값·빈 값은 「초기 위치로 돌아간 뒤」 (수정 목록 120 (다))', () => {
  assert.equal(repeatChoice(''), 'reinitialize');
  assert.equal(repeatChoice(undefined), 'reinitialize');
  assert.equal(repeatChoice('direct'), 'reinitialize');
  assert.equal(repeatChoice('dwell'), 'dwell_reinitialize');
  assert.equal(repeatChoice('DWELL_REINITIALIZE'), 'dwell_reinitialize');
  assert.equal(repeatChoice('weird'), 'reinitialize');
  for (const mode of REPEAT_MODES) assert.equal(repeatChoice(mode.id), mode.id);
});

test('시작 막는 이유 · 자동·끔 모드는 수동으로 바꾸기 버튼 · 긴급 정지가 먼저', () => {
  const ok = { scope: 'local', playlist: ['a.json'], mappingId: 'm.yaml' };
  assert.equal(startBlocker({}, { run_mode: 'manual' }, ok), null);
  assert.equal(startBlocker({}, { run_mode: 'schedule' }, ok).fix, 'mode-manual');
  assert.equal(startBlocker({}, { run_mode: 'off' }, ok).fix, 'mode-manual');
  assert.equal(startBlocker({ safety_status: { emergency_latched: true } }, { run_mode: 'off' }, ok).fix, 'restart-program');
  assert.match(startBlocker({}, { run_mode: 'manual' }, { ...ok, playlist: [] }).text, /재생 목록이 비어 있습니다/);
  assert.equal(startBlocker({}, { run_mode: 'manual' }, { ...ok, mappingId: '' }).fix, 'open-mapping');
  assert.match(startBlocker({ execution_context: { ready: false, message: '모터 설정 미적용' } }, { run_mode: 'manual' }, ok).text, /미적용/);
  assert.match(startBlocker({ motion_run_status: { state: 'running' } }, { run_mode: 'manual' }, ok).text, /재생 중/);
  const range = startBlocker({ mapping_range_blocker: '조인트 범위 미확인 · A' }, { run_mode: 'manual' }, ok);
  assert.deepEqual([range.text, range.fix], ['조인트 범위 미확인 · A', 'open-mapping'], '수정 목록 97');
  const slave = { coordination: { config: { is_master: false }, runtime: { joined: true } } };
  assert.match(startBlocker(slave, { run_mode: 'manual' }, { ...ok, scope: 'group' }).text, /마스터 PC에서만/);
  assert.equal(startBlocker(group({ coordination_error: { active: true, message: 'x' } }), { run_mode: 'manual' }, { ...ok, scope: 'group' }).fix, 'ack-group-error');
});

test('재생 목록 · 매핑에서 읽기 · 옮기기 · 빼기 · 50개까지', () => {
  assert.deepEqual(registeredPlaylist({ motion_file_id: 'a', motion_playlist: ['a', 'b'] }), ['a', 'b']);
  assert.deepEqual(registeredPlaylist({ motion_file_id: 'a' }), ['a']);
  assert.deepEqual(registeredPlaylist(null), []);
  assert.deepEqual(playlistMove(['a', 'b', 'c'], 2, -1), ['a', 'c', 'b']);
  assert.deepEqual(playlistMove(['a', 'b'], 0, -1), ['a', 'b']);
  assert.deepEqual(playlistRemove(['a', 'b', 'a'], 2), ['a', 'b']);
  assert.equal(playlistAdd(Array(50).fill('x'), 'y').length, 50);
  assert.deepEqual(playlistAdd(['a'], 'a'), ['a', 'a'], '같은 파일 두 번도 된다');
});

test('파일 줄 · 서버(analysis)와 프리뷰(최상위) 둘 다', () => {
  assert.deepEqual(fileInfo({ id: 'a.json', analysis: { valid: true, time: { duration_sec: 556 } } }).duration, 556);
  assert.equal(fileInfo({ id: 'b.json', valid: false, message: '헤더 없음' }).checkText, '헤더 없음');
  assert.equal(fileInfo({ id: 'c.json' }).check, 'unknown');
});

test('지금 · 단계 · 머리글', () => {
  const status = { state: 'running', current_cycle: 3, motion_file_id: 'n.json', run_mode: 'continuous', playlist_index: 0, playlist_length: 2 };
  const head = playHeadline({ motion_run_status: status });
  assert.equal(head.title, '3회차 재생 중');
  assert.equal(head.detail, '목록 1/2 · 연속');
  assert.deepEqual(phaseSteps(status).map((s) => s.state), ['done', 'now', 'todo']);
  assert.deepEqual(phaseSteps({ state: 'idle' }).map((s) => s.state), ['todo', 'todo', 'todo']);
  assert.equal(playHeadline({ motion_run_status: { state: 'error', message: '도달 실패' } }).message, '도달 실패');
});

test('실행 축 · 끔 = 그 자리 · 다시 켬 = 다음 회차부터 · 지금 값은 조인트 deg', () => {
  const mapping = { mappings: [
    { motion_id: 'A', motor_axis: 0, motion_lower_rad: -Math.PI / 18, motion_upper_rad: Math.PI / 18 },
    { motion_id: 'B', motor_axis: 1 }, { motion_id: 'C', motor_axis: 2 }, { motion_id: 'off', enabled: false },
  ] };
  const snap = {
    motion_run_status: { state: 'running', live_overrides: { A: { muted: true } }, held_motion_ids: ['B'], axes: [{ motion_id: 'C', motion_clamped: true }] },
    motion_state: { motors: [{ controller_index: 0, motion_actual_rad: Math.PI / 180 * 2.5 }] },
  };
  const rows = axisRows(snap, mapping);
  assert.deepEqual(rows.map((r) => [r.id, r.state]), [['A', '꺼짐 · 현재 위치에서 정지'], ['B', '다음 회차부터 적용'], ['C', '재생 중']]);
  assert.equal(rows[0].range, '−10.0 ~ +10.0°');
  assert.equal(rows[0].now, '+2.50');
  assert.equal(rows[2].clamped, '잘라서 재생');
});

test('그룹 PC 줄 · 빠진 PC 는 이유 · 연결 안 됨 · 출발 전 멈춤은 지금 멈춤', () => {
  const snap = group({
    local: { pc_id: 'f1' },
    peers: [{ pc_id: 'f2', motion_cycle_text: '3회차' }, { pc_id: 'f3' }, { pc_id: 'f4', state: 'offline' }],
    execution: { state: 'running', excluded: { f3: '버전 다름' } },
  });
  assert.deepEqual(groupRows(snap).map((r) => [r.id, r.note]), [['f1', '그룹 대기'], ['f2', '그룹 대기'], ['f3', '제외됨 · 버전 다름'], ['f4', '연결 안 됨']]);
  assert.equal(groupRows(snap)[0].local, true);
  assert.equal(groupStopCommand(snap), 'stop_after_cycle');
  assert.equal(groupStopCommand(group({ execution: { state: 'armed' } })), 'stop_now');
});

test('첫 자세 이동 시간 · 매핑 시간이 하나면 그 값이 골라져 있고 중복 칸 없음 · 다를 때만 「조인트마다 다름」', () => {
  const same = initialMoveChoices([{ initial_move_time_sec: 5 }, { initial_move_time_sec: 5 }, { enabled: false, initial_move_time_sec: 10 }], null);
  assert.deepEqual(same.options.map(([value]) => value), [5, 7, 10]);
  assert.equal(same.selected, 5);
  assert.equal(same.pick(5), null, '매핑과 같으면 null = 매핑대로');
  assert.equal(same.pick(7), 7);
  assert.equal(initialMoveChoices([{ initial_move_time_sec: 5 }], 7).selected, 7);
  assert.deepEqual(initialMoveChoices([{ initial_move_time_sec: 8 }], null).options.map(([value]) => value), [5, 7, 8, 10]);
  const mixed = initialMoveChoices([{ initial_move_time_sec: 5 }, { initial_move_time_sec: 10 }], null);
  assert.deepEqual(mixed.options[0], [null, '조인트마다 다름 (매핑)']);
  assert.equal(mixed.selected, null);
  assert.equal(mixed.pick(5), 5);
});

test('회차 사이 · 초기 위치를 거치지 않는 「바로 다음」 · 「대기 후 다음」 은 고를 수 없다 · 안전 (2026-10-12)', () => {
  assert.deepEqual(REPEAT_MODES.map((mode) => mode.id), ['reinitialize', 'dwell_reinitialize']);
  assert.equal(REPEAT_MODES[0].id, 'reinitialize');
});

test('그룹 PC 줄 · 모터 설정이 없어 빠진 PC 는 짧게 「모터 설정 없음」 (2026-10-12)', () => {
  const snap = { coordination: { runtime: { joined: true, local: { pc_id: 'f4' }, peers: [{ pc_id: 'f1', state: 'online' }],
    execution: { execution_id: 'e', excluded: { f1: '준비 거절 · 현재 프로젝트의 실행 준비가 끝나지 않았습니다: 모터 설정과 조인트 매핑을 저장해 확정하세요' } } } } };
  const row = groupRows(snap).find((r) => r.id === 'f1');
  assert.equal(row.note, '제외됨 · 모터 설정 없음(재생할 모터가 없는 PC)');
});

test('그룹 전체 N대 · 실제로 들어갈 PC 수 · 빠질 PC 와 이유 · 수정 목록 122 (다)', () => {
  // 실물 S-10 · 4대 모두 수동인데 「그룹 전체 · 3대」 로 보이고 마스터 혼자 돌았다
  const snap = group({
    local: { pc_id: 'floating4', display_name: 'floating4' },
    peers: [{ pc_id: 'floating1' }, { pc_id: 'floating2', display_name: '두번째' }, { pc_id: 'floating3' }],
    start_preview: {
      participants: ['floating1', 'floating3', 'floating4'],
      excluded: { floating2: '끔 모드' },
    },
  });
  const preview = groupStartPreview(snap);
  assert.equal(preview.count, 3);
  assert.deepEqual(preview.excluded, [{ id: 'floating2', name: '두번째', reason: '끔 모드' }]);
  assert.equal(excludedText(preview.excluded), '빠짐 · 두번째(끔 모드)');
  assert.equal(excludedText([]), '');
  // 미리 보기가 없으면(슬레이브 · 옛 서버) 모른다 · 화면이 옛 방식으로 센다
  assert.equal(groupStartPreview(group()).count, null);
});
