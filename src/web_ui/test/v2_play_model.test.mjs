/** UI v2 · 공연 화면 값 · 시작 막는 이유 · 재생 목록 · 실행 축 · 그룹 PC 줄 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  axisRows, defaultScope, fileInfo, groupRows, groupStopCommand, phaseSteps, playHeadline,
  playlistAdd, playlistMove, playlistRemove, registeredPlaylist, startBlocker,
} from '../static/v2/js/play_model.js';

const group = (extra = {}) => ({ coordination: { config: { is_master: true, enabled: true }, runtime: { joined: true, execution: {}, ...extra } } });

test('범위 · 그룹에 든 마스터만 매장 전체가 기본', () => {
  assert.equal(defaultScope(group()), 'group');
  assert.equal(defaultScope({ coordination: { config: { is_master: false }, runtime: { joined: true } } }), 'local');
  assert.equal(defaultScope({}), 'local');
});

test('시작 막는 이유 · 자동·끔 모드는 수동으로 바꾸기 버튼 · 긴급 정지가 먼저', () => {
  const ok = { scope: 'local', playlist: ['a.json'], mappingId: 'm.yaml' };
  assert.equal(startBlocker({}, { run_mode: 'manual' }, ok), null);
  assert.equal(startBlocker({}, { run_mode: 'schedule' }, ok).fix, 'mode-manual');
  assert.equal(startBlocker({}, { run_mode: 'off' }, ok).fix, 'mode-manual');
  assert.equal(startBlocker({ safety_status: { emergency_latched: true } }, { run_mode: 'off' }, ok).fix, 'restart-program');
  assert.match(startBlocker({}, { run_mode: 'manual' }, { ...ok, playlist: [] }).text, /재생 목록이 비었/);
  assert.equal(startBlocker({}, { run_mode: 'manual' }, { ...ok, mappingId: '' }).fix, 'open-mapping');
  assert.match(startBlocker({ execution_context: { ready: false, message: '모터 설정 미적용' } }, { run_mode: 'manual' }, ok).text, /미적용/);
  assert.match(startBlocker({ motion_run_status: { state: 'running' } }, { run_mode: 'manual' }, ok).text, /재생 중/);
  const slave = { coordination: { config: { is_master: false }, runtime: { joined: true } } };
  assert.match(startBlocker(slave, { run_mode: 'manual' }, { ...ok, scope: 'group' }).text, /마스터에서만/);
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
  assert.deepEqual(rows.map((r) => [r.id, r.state]), [['A', '꺼짐 · 그 자리에 섬'], ['B', '다음 회차부터'], ['C', '도는 중']]);
  assert.equal(rows[0].range, '−10.0 ~ +10.0°');
  assert.equal(rows[0].now, '+2.50');
  assert.equal(rows[2].clamped, '범위로 자름');
});

test('그룹 PC 줄 · 빠진 PC 는 이유 · 연결 안 됨 · 출발 전 멈춤은 지금 멈춤', () => {
  const snap = group({
    local: { pc_id: 'f1' },
    peers: [{ pc_id: 'f2', motion_cycle_text: '3회차' }, { pc_id: 'f3' }, { pc_id: 'f4', state: 'offline' }],
    execution: { state: 'running', excluded: { f3: '버전 다름' } },
  });
  assert.deepEqual(groupRows(snap).map((r) => [r.id, r.note]), [['f1', '그룹 대기'], ['f2', '그룹 대기'], ['f3', '빠짐 · 버전 다름'], ['f4', '연결 안 됨']]);
  assert.equal(groupRows(snap)[0].local, true);
  assert.equal(groupStopCommand(snap), 'stop_after_cycle');
  assert.equal(groupStopCommand(group({ execution: { state: 'armed' } })), 'stop_now');
});
