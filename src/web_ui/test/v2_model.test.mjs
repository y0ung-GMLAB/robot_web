/** UI v2 · 상태 한 문장 · 확인할 일 · 지금 카드 · 오늘 스케줄 (설계안 2026-10-09 · 뼈대 + 홈) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  collectIssues, headline, modePhrase, motorChips, pcRole, pcRows, RUN_MODE_HINT, runSummary, todayWindows,
} from '../static/v2/js/model.js';

test('위 막대 역할 · is_master 는 설정 파일 요약에서 · 돌고 있는 노드 칸이 먼저 와도 마스터 (수정 목록 119)', () => {
  const runtime = { config: { pc_id: 'floating4', enabled: true, group_id: 'stage-a', dds_domain_id: 21 } };
  const master = { coordination: { config: { pc_id: 'floating4', enabled: true, is_master: true, group_id: 'stage-a' }, runtime } };
  assert.deepEqual(pcRole(master), { pcId: 'floating4', text: '마스터 · 그룹 stage-a' });
  const slave = { coordination: { config: { ...master.coordination.config, is_master: false }, runtime } };
  assert.equal(pcRole(slave).text, '슬레이브 · 그룹 stage-a');
  assert.equal(pcRole({ coordination: { config: { enabled: false }, runtime: { config: { enabled: false } } } }).text, '단독');
  assert.equal(pcRole({}).text, '단독');
  // 돌고 있는 노드 값이 우선(그룹 ID 를 바꾸고 아직 재시작 전)
  const pending = { coordination: { config: { enabled: true, is_master: true, group_id: 'new' }, runtime: { config: { enabled: true, group_id: 'old' } } } };
  assert.equal(pcRole(pending).text, '마스터 · 그룹 old');
});

const pcs = (...extra) => ({ coordination: { runtime: { network_pcs: [
  { pc_id: 'floating4', is_local: true, is_master: true, online: true, joined: true },
  ...extra,
] } } });

test('정상이면 한 문장 · 모드와 운영 시간', () => {
  const sched = { run_mode: 'schedule', active_schedule_id: 'a' };
  assert.deepEqual(headline(pcs(), sched).text, '정상 · 스케줄 운영 중');
  assert.equal(headline(pcs(), { run_mode: 'schedule' }).text, '정상 · 운영 시간 외');
  assert.equal(headline(pcs(), { run_mode: 'manual' }).tone, 'info');
  assert.equal(modePhrase({ run_mode: 'off' }), '끔 · 명령 차단');
});

test('나쁜 문제가 있으면 그 문제가 한 문장 · 주의만 있으면 개수', () => {
  const snap = { ...pcs({ pc_id: 'floating2', online: true, version_differs: true }),
    minas_absolute_blocker: '0번 모터 Pr0.15=1' };
  const line = headline(snap, { run_mode: 'schedule', active_schedule_id: 'a' });
  assert.equal(line.tone, 'bad');
  assert.match(line.text, /앱솔루트 방식이 확인되지 않아/);
  assert.equal(line.issues[0].action.kind, 'open');
  const warnOnly = headline(pcs({ pc_id: 'floating2', online: true, version_differs: true }), { run_mode: 'schedule', active_schedule_id: 'a' });
  assert.equal(warnOnly.tone, 'warn');
  assert.equal(warnOnly.text, '스케줄 운영 중 · 확인할 일 1개');
  assert.equal(warnOnly.issues[0].action.kind, 'update-all');
});

test('조인트 범위 미확인 · 빨간 문제 · 조인트 매핑 열기 (수정 목록 97)', () => {
  const line = headline({ ...pcs(), mapping_range_blocker: '조인트 범위 미확인 · Neck_Pitch · …' }, { run_mode: 'manual' });
  assert.equal(line.tone, 'bad');
  assert.deepEqual([line.issues[0].title, line.issues[0].action.target], ['조인트 범위가 확인되지 않아 재생과 수동 조작이 차단되어 있습니다', 'mapping']);
});

test('문제마다 해결 버튼 · 긴급 정지 · 알람 · 그룹 오류 · 스케줄 거부 · 연결 끊김', () => {
  const snap = {
    ...pcs({ pc_id: 'floating2', online: false }),
    safety_status: { emergency_latched: true },
    motion_state: { motors: [{ controller_index: 2, fault: true, error_text: 'Err16.0' }] },
  };
  snap.coordination.runtime.coordination_error = { active: true, message: '회차 실패' };
  const kinds = collectIssues(snap, { last_failure: { count: 3, message: '피어 없음' } }).map((i) => i.action?.kind || i.title);
  assert.deepEqual(kinds.slice(0, 3), ['restart-program', 'fault-reset', 'ack-group-error']);
  assert.ok(kinds.includes('스케줄 시작 거부됨 (3회)'));
  assert.ok(kinds.some((k) => /floating2 연결 안 됨/.test(k)));
  assert.equal(collectIssues(snap, {}, { connected: false }).length, 1, '연결이 끊기면 그것 하나만');
});

test('스케줄 시작 대기 · 잠그지 않은 그룹 시작 실패 · 수정 목록 123·124', () => {
  // 부팅 직후 앱솔루트 확인 전 · 거부가 아니라 대기 · 3번 넘게 이어지면 빨강
  const waiting = collectIssues({}, { last_failure: { count: 1, deferred: true, message: '앱솔루트 미확인' } });
  assert.equal(waiting[0].title, '스케줄 시작 대기 중 (1회)');
  assert.equal(waiting[0].tone, 'warn');
  assert.match(waiting[0].detail, /스스로 시작/);
  assert.equal(collectIssues({}, { last_failure: { count: 3, deferred: true, message: 'x' } })[0].tone, 'bad');
  // 진행 PC 준비 안 됨 · 그룹 오류로 잠그지 않지만 이유는 보인다 · 그룹이 돌면 안 보인다
  const failed = { coordination: { runtime: { last_start_failure: { message: 'floating4 실행 준비 안 됨: 앱솔루트 미확인' }, execution: {} } } };
  assert.deepEqual(collectIssues(failed, {}).map((i) => [i.tone, i.title]), [['warn', '그룹 시작이 취소되었습니다']]);
  failed.coordination.runtime.execution = { execution_id: 'exec-1' };
  assert.equal(collectIssues(failed, {}).length, 0);
});

test('그룹 시작 실패 노란 줄 · 제목을 code 로 나눔 · 수정 목록 147', () => {
  const issue = (failure) => {
    const snap = { coordination: { runtime: { last_start_failure: failure, execution: {} } } };
    const found = collectIssues(snap, {});
    assert.equal(found.length, 1);
    assert.equal(found[0].tone, 'warn');
    return found[0];
  };
  // 실물 2026-10-15 12:42 · 참가 0대 거절 · 서버 글이 제목과 같은 말로 시작하면 한 번만
  const empty = issue({ code: 'GROUP_START_NOT_READY', message: '그룹 시작 불가 · 들어갈 PC 가 없습니다 · 참가 0대' });
  assert.equal(empty.title, '그룹 시작 불가');
  assert.equal(empty.detail, '들어갈 PC 가 없습니다 · 참가 0대');
  // 준비 중 거절 · 같은 코드 · 다른 글
  assert.equal(issue({ code: 'GROUP_START_NOT_READY', message: 'floating4 실행 준비 안 됨: 앱솔루트 미확인' }).title, '그룹 시작 불가');
  // W-A10 · 9회차 돈 뒤 PC 빠짐 · 「시작이 취소」 가 아니다
  const left = issue({ code: 'GROUP_PARTICIPANT_LEFT', message: '그룹 실행 정지 · 남은 PC 없음 · 잠그지 않음 · floating4(웹 다시 시작)' });
  assert.equal(left.title, '그룹 실행 정지 · PC 빠짐');
  assert.match(left.detail, /남은 PC 없음/);
  // 이 PC 웹 서비스 끊김 · 잠그지 않고 놓음(145) · 145 ② 코드가 이 칸에 와도 같은 제목
  assert.equal(issue({ code: 'GROUP_RELEASED', message: '로컬 Web Bridge 상태 수신 중단: 519ms' }).title, '그룹 실행 정지 · 웹 서비스 끊김');
  assert.equal(issue({ code: 'GROUP_LOCAL_BRIDGE_LOST', message: 'floating4 웹 서비스 끊김으로 그룹 정지' }).title, '그룹 실행 정지 · 웹 서비스 끊김');
  // 정말 시작 전 취소 · 코드 없는 옛 연동 노드 · 전 글 그대로
  for (const code of ['TRIGGER_SYNC_FAILED', 'GROUP_START_REJECTED', 'GROUP_SCHEDULE_ACK_TIMEOUT', 'GROUP_SCHEDULE_SELF_LATE', '', undefined]) {
    const other = issue({ code, message: '예약 확인 늦음' });
    assert.equal(other.title, '그룹 시작이 취소되었습니다', String(code));
    assert.equal(other.detail, '예약 확인 늦음');
  }
  // 서버가 남기는 코드는 모두 여기서 다룬다(새 코드가 생기면 제목을 정할 것)
  const node = readFileSync(new URL('../../motion_coordination/motion_coordination/coordination_node.py', import.meta.url), 'utf8');
  const codes = new Set([...node.matchAll(/_(?:remember_start_failure|cancel_before_start)\([^)]*?code=(?:'([A-Z_]+)' if \w+ else '([A-Z_]+)'|'([A-Z_]+)')/gs)]
    .flatMap((m) => m.slice(1).filter(Boolean)));
  const known = ['GROUP_START_NOT_READY', 'GROUP_PARTICIPANT_LEFT', 'GROUP_RELEASED', 'TRIGGER_SYNC_FAILED',
    'GROUP_START_REJECTED', 'GROUP_SCHEDULE_ACK_TIMEOUT', 'GROUP_SCHEDULE_SELF_LATE'];
  assert.ok(codes.size >= 5, `코드를 못 찾음 · ${[...codes]}`);
  for (const code of codes) assert.ok(known.includes(code), `제목을 정하지 않은 새 시작 실패 코드 · ${code}`);
});

test('운전 모드 버튼 설명 · 누가 시작하나 · 수정 목록 122', () => {
  const shell = readFileSync(new URL('../static/v2/js/shell.js', import.meta.url), 'utf8');
  assert.match(shell, /RUN_MODE_HINT\[button\.dataset\.mode\]/);
  assert.match(RUN_MODE_HINT.manual, /사람이 시작/);
  assert.match(RUN_MODE_HINT.manual, /그룹 재생/);
  assert.match(RUN_MODE_HINT.schedule, /저절로/);
  assert.match(RUN_MODE_HINT.off, /움직이지 않/);
});

test('지금 카드 · 재생 중이면 파일 · 회차 · 진행 · 매장 전체', () => {
  const run = runSummary({ motion_run_status: { state: 'running', motion_file_id: 'narration.json', current_cycle: 3,
    run_mode: 'continuous', group_execution: true, progress: { elapsed_sec: 256, duration_sec: 556 } },
  coordination: { runtime: { execution: { participants: ['a', 'b', 'c', 'd'] } } } });
  assert.equal(run.title, 'narration 재생 중');
  assert.equal(run.subtitle, '그룹 전체 4대 · 3회차 · 연속');
  assert.equal(run.timeText, '04:16 / 09:16');
  assert.ok(run.moving && Math.abs(run.ratio - 256 / 556) < 1e-9);
  assert.equal(runSummary({ motion_run_status: { state: 'idle' } }).title, '대기 상태');
  assert.equal(runSummary({}).moving, false);
});

test('모터 · 조인트 값이 있으면 조인트 deg · 알람·서보 꺼짐', () => {
  const chips = motorChips({ motion_state: { motors: [
    { controller_index: 0, name: '눈 상하', motion_actual_rad: Math.PI / 180 * 2.31, servo_on: true, overload_ratio_pct: 18 },
    { controller_index: 1, name: '눈 좌우', position_rad: -Math.PI / 180 * 80.4, servo_on: false },
    { controller_index: 2, fault: true, errorcode: 0, error_text: 'Err16.0' },
    { controller_index: 3, name: '빈 조인트', motion_actual_rad: null, position_rad: 0, servo_on: true, error_text: 'No error' },
  ] } });
  assert.deepEqual(chips.map((c) => [c.value, c.unit, c.tone, c.note]), [
    ['+2.31°', '조인트', 'ok', '과부하율 18%'], ['−80.40°', '모터', 'warn', '서보 꺼짐'], ['-', '모터', 'bad', '알람 Err16.0'],
    ['+0.00°', '모터', 'ok', ''],
  ]);
});

test('매장 PC 줄 · 연결 안 됨 · 버전 다름 · 그룹 참여 꺼짐', () => {
  const rows = pcRows(pcs({ pc_id: 'f1', online: false }, { pc_id: 'f2', version_differs: true }, { pc_id: 'f3', joined: false }, { pc_id: 'sp', role: 'speaker' }));
  assert.deepEqual(rows.map((r) => r.note), ['마스터', '연결 안 됨', '버전 다름', '그룹 미참여', '스피커']);
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
  for (const file of ['main.js', 'shell.js', 'net.js', 'actions.js', 'play_model.js', 'schedule_model.js', 'store_model.js', 'anim_model.js', 'pages/home.js', 'pages/play.js', 'pages/schedule.js', 'pages/store.js', 'pages/animations.js', 'pages/playlist_card.js', 'markdown.js', 'pages/docs.js', 'pages/tools.js', 'pages/alarms.js', 'pages/network.js', 'pages/backup.js', 'dialog.js', 'net.js', 'pages/pack.js', 'zip_store.js', 'records_model.js', 'pages/records.js', 'mapping_model.js', 'pages/mapping.js', 'motors_model.js', 'pages/motors.js', 'pages/minas_base.js', 'pages/drive_gains.js', 'pages/drive_params.js', 'pages/manual.js', 'dial_session.js', 'manual_stream.js', 'viewer3d.js']) {
    const text = readFileSync(new URL(`../static/v2/js/${file}`, import.meta.url), 'utf8');
    // 기존 화면 코드는 안 쓴다 · 예외 하나 · 3D 순수 계산(sim3d_math.js)은 두 화면이 같은 시계·자세를 쓰게 함께 쓴다
    const imports = [...text.matchAll(/from '((?:\.\.\/)+js\/[^']+)'/g)].map((m) => m[1]);
    assert.deepEqual(imports.filter((path) => !path.endsWith('/js/sim3d_math.js')), [], file);
    assert.doesNotMatch(text, /innerHTML/, `${file} · 글은 textContent 로`);
  }
});

test('메뉴의 모든 화면에 페이지가 있다 · 빈 자리 없음', async () => {
  const { NAV } = await import('../static/v2/js/shell.js');
  const main = readFileSync(new URL('../static/v2/js/main.js', import.meta.url), 'utf8');
  const block = main.slice(main.indexOf('const PAGES = {'), main.indexOf('};', main.indexOf('const PAGES = {')));
  for (const group of NAV) {
    for (const [id] of group.items) {
      assert.ok(block.includes(`
  ${id}: {`) || block.includes(`'${id}': {`), `${id} 페이지 없음`);
    }
  }
});

test('PREOP 에 멈춘 드라이브 · 감시 노드 글 그대로 빨강 · 제어 전원 안내 (수정 목록 125)', () => {
  const snap = { motion_state: { ethercat: { stuck_slaves: [
    { master_index: 0, slave_position: 1, axis: 1, state: 'PREOP', error_flag: true, message: '1번 드라이브가 PREOP 에 멈춤 · 그 드라이브 제어 전원을 껐다 켜세요' },
  ] } } };
  const issues = collectIssues(snap, { run_mode: 'manual' });
  const stuck = issues.find((i) => i.title.includes('PREOP 에 멈춤'));
  assert.equal(stuck.tone, 'bad');
  assert.equal(stuck.title, '1번 드라이브가 PREOP 에 멈춤 · 그 드라이브 제어 전원을 껐다 켜세요');
  assert.match(stuck.detail, /제어 전원/);
  assert.equal(collectIssues({ motion_state: { ethercat: {} } }, { run_mode: 'manual' }).length, 0);
});

test('메일박스가 멈춘 드라이브 · 감시 노드 글 그대로 빨강 · 재생은 그대로라고 (수정 목록 139 ③)', () => {
  const snap = { motion_state: { minas_absolute: { state: 'ok', drives: [], stuck_mailboxes: [
    { master_index: 0, slave_position: 2, axis: 2, since: 1, message: '2번 드라이브 메일박스 응답 없음 · 그 드라이브 제어 전원을 껐다 켜세요' },
  ] } } };
  const issues = collectIssues(snap, { run_mode: 'manual' });
  const box = issues.find((i) => i.title.includes('메일박스'));
  assert.equal(box.tone, 'bad');
  assert.equal(box.title, '2번 드라이브 메일박스 응답 없음 · 그 드라이브 제어 전원을 껐다 켜세요');
  assert.match(box.detail, /재생/);
  assert.equal(collectIssues({ motion_state: { minas_absolute: { state: 'ok', stuck_mailboxes: [] } } }, { run_mode: 'manual' }).length, 0);
  assert.equal(collectIssues({ motion_state: { minas_absolute: { state: 'ok' } } }, { run_mode: 'manual' }).length, 0);
});
