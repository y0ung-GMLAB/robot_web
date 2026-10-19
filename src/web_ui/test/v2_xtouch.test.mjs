/** UI v2 · X-Touch · MIDI 읽기 · 잡기(pickup) · 채널 상태 · 매핑 칸 · 수정 목록 156 (사용자 결정 2026-10-17) */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FADER_MAX, XTouchSession, channelConfig, faderMessage, faderToJoint, jointToFader, lcdDeviceId, lcdMessages,
  ledMessage, looksLikeXTouch, parseMidi, pickupReached, recordLed,
} from '../static/v2/js/xtouch_model.js';
import { midiUnavailableReason } from '../static/v2/js/xtouch_device.js';
import { draftProblems, draftToRow, faderNumber, rowToDraft } from '../static/v2/js/mapping_model.js';

test('MIDI 읽기 · 페이더 14비트 · 터치 104+ · SELECT 24+ · REC 0+ · 모르는 것은 null', () => {
  assert.deepEqual(parseMidi([0xE2, 0x7F, 0x7F]), { kind: 'fader', channel: 2, value: FADER_MAX });
  assert.deepEqual(parseMidi([0xE0, 0x00, 0x40]), { kind: 'fader', channel: 0, value: 8192 });
  assert.deepEqual(parseMidi([0x90, 104 + 3, 127]), { kind: 'touch', channel: 3, down: true });
  assert.deepEqual(parseMidi([0x90, 104 + 3, 0]), { kind: 'touch', channel: 3, down: false });
  assert.deepEqual(parseMidi([0x80, 104, 64]), { kind: 'touch', channel: 0, down: false });
  assert.deepEqual(parseMidi([0x90, 24 + 7, 127]), { kind: 'button', group: 'select', channel: 7, down: true });
  assert.deepEqual(parseMidi([0x90, 0, 127]), { kind: 'button', group: 'rec', channel: 0, down: true });
  assert.equal(parseMidi([0xE9, 0, 0]), null, '채널 9 이상');
  assert.equal(parseMidi([0xB0, 16, 1]), null, '다이얼(CC)은 안 씀');
  assert.equal(parseMidi([0x90, 50, 127]), null);
});

test('보내기 · 페이더 · 불빛 · 글씨 칸(Extender 15)', () => {
  assert.deepEqual(faderMessage(1, 8192), [0xE1, 0x00, 0x40]);
  assert.deepEqual(faderMessage(0, 99999), [0xE0, 0x7F, 0x7F], '끝에서 자름');
  assert.deepEqual(ledMessage('select', 2, 'on'), [0x90, 26, 127]);
  assert.deepEqual(ledMessage('rec', 0, 'blink'), [0x90, 0, 1]);
  assert.deepEqual(ledMessage('rec', 0, 'off'), [0x90, 0, 0]);
  const [top, bottom] = lcdMessages(0x15, 1, 'neck_pitch', 'LIVE');
  assert.deepEqual(top.slice(0, 7), [0xF0, 0x00, 0x00, 0x66, 0x15, 0x12, 7]);
  assert.equal(String.fromCharCode(...top.slice(7, 14)), 'neck_pi');
  assert.equal(bottom[6], 56 + 7);
  assert.equal(top.at(-1), 0xF7);
  assert.equal(lcdDeviceId('X-Touch-Ext'), 0x15);
  assert.equal(lcdDeviceId('X-TOUCH'), 0x14);
  assert.ok(looksLikeXTouch('MIDIIN2 (X-Touch-Ext)') && looksLikeXTouch('XTOUCH') && !looksLikeXTouch('loopMIDI'));
});

test('페이더 ↔ 조인트 범위 전체 · 맨 아래 최소 · 맨 위 최대', () => {
  assert.equal(faderToJoint(-15, 15, 0), -15);
  assert.equal(faderToJoint(-15, 15, FADER_MAX), 15);
  assert.ok(Math.abs(faderToJoint(-15, 15, FADER_MAX / 2)) < 1e-9);
  assert.equal(jointToFader(-15, 15, 15), FADER_MAX);
  assert.equal(jointToFader(-15, 15, 99), FADER_MAX, '범위 밖은 끝');
  assert.equal(jointToFader(-10, 13, faderToJoint(-10, 13, 5000)), 5000);
});

test('잡기 · 0.5° 안이거나 지나감', () => {
  assert.equal(pickupReached(null, 3.4, 3.0), true);
  assert.equal(pickupReached(null, 4.0, 3.0), false);
  assert.equal(pickupReached(2.0, 4.0, 3.0), true, '지나감');
  assert.equal(pickupReached(4.0, 2.0, 3.0), true, '반대로 지나감');
  assert.equal(pickupReached(4.0, 5.0, 3.0), false);
  assert.equal(pickupReached(2.0, 4.0, null), false, '축 값을 모르면 안 잡음');
});

const rows = [
  { motion_id: 'neck_yaw', enabled: true, xtouch_fader: 1, motion_lower_deg: -15, motion_upper_deg: 15, max_velocity_deg_s: 9, max_acceleration_deg_s2: 14 },
  { motion_id: 'eye_yaw', enabled: true, xtouch_fader: 3, motion_lower_deg: -11.3, motion_upper_deg: 11.3 },
  { motion_id: 'off', enabled: false, xtouch_fader: 2, motion_lower_deg: -1, motion_upper_deg: 1 },
];
const axisOf = (row) => ({ neck_yaw: 1, eye_yaw: 4 })[row.motion_id] ?? null;

test('채널 · 「사용」 줄의 페이더 번호 · 상한 둘 다 있어야 조종', () => {
  const config = channelConfig(rows, axisOf);
  assert.equal(config.length, 8);
  assert.equal(config[0].motionId, 'neck_yaw');
  assert.equal(config[0].axis, 1);
  assert.equal(config[0].ratesSet, true);
  assert.equal(config[1], null, '꺼진 줄');
  assert.equal(config[2].ratesSet, false);
});

function session(jointNow = { 1: 0 }) {
  const s = new XTouchSession();
  s.configure(channelConfig(rows, axisOf));
  const ctx = (extra = {}) => ({ now: 0, blocked: '', recording: false, jointOf: (axis) => jointNow[axis] ?? null, ...extra });
  return { s, ctx, jointNow };
}

test('SELECT · 불빛 켜고 페이더를 축 위치로 · 손 대고 맞추면 조종 · 떼면 release', () => {
  const { s, ctx } = session({ 1: 3 });
  const select = s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  assert.deepEqual(select[0], { type: 'led', group: 'select', channel: 0, state: 'on' });
  assert.deepEqual(select[1], { type: 'feedback', channel: 0, value: jointToFader(-15, 15, 3) });
  assert.deepEqual(s.handle({ kind: 'button', group: 'select', channel: 0, down: false }, ctx()), [], '뗌은 무시');

  s.handle({ kind: 'touch', channel: 0, down: true }, ctx());
  assert.equal(s.channels[0].phase, 'pickup');
  // 축 값 근처(페이더가 이미 거기 있음) → 바로 조종
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 3.2) }, ctx());
  assert.equal(s.channels[0].phase, 'live');
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 6) }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 7) }, ctx());
  const sent = s.tick(ctx());
  assert.equal(sent.length, 1, '주기마다 마지막 값 하나');
  assert.equal(sent[0].type, 'target');
  assert.equal(sent[0].axis, 1);
  assert.ok(Math.abs(sent[0].joint - 7) < 0.01);
  assert.deepEqual(s.tick(ctx()), [], '새 값이 없으면 안 보냄 · 손 대는 중엔 따라가기 없음');

  // 「뗌」 은 0.2 s 기다렸다 확정(터치 끊김 · 2026-10-19)
  assert.deepEqual(s.handle({ kind: 'touch', channel: 0, down: false }, ctx({ now: 1000 })), []);
  assert.deepEqual(s.tick(ctx({ now: 1300 })), [{ type: 'release', axes: [1] }]);
  assert.equal(s.channels[0].phase, 'ready');
});

test('잡기 전 · 페이더가 축 값과 멀면 안 보낸다 · 지나가는 순간부터', () => {
  const { s, ctx } = session({ 1: 0 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  s.channels[0].value = jointToFader(-15, 15, 10);           // 모터 페이더가 못 감(손으로 붙잡음 등)
  s.handle({ kind: 'touch', channel: 0, down: true }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 9) }, ctx());
  assert.equal(s.channels[0].phase, 'pickup');
  assert.deepEqual(s.tick(ctx()), []);
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, -2) }, ctx());   // 0 을 지나감
  assert.equal(s.channels[0].phase, 'live');
  assert.equal(s.tick(ctx())[0].type, 'target');
});

test('손 안 댄 선택 페이더는 축을 따라 움직인다 · 0.1 s 마다 · 바뀐 만큼만', () => {
  const { s, ctx, jointNow } = session({ 1: 0 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  assert.deepEqual(s.tick(ctx({ now: 50 })), [], '0.1 s 전');
  assert.deepEqual(s.tick(ctx({ now: 200 })), [], '그대로면 안 보냄');
  jointNow[1] = 5;
  assert.deepEqual(s.tick(ctx({ now: 400 })), [{ type: 'feedback', channel: 0, value: jointToFader(-15, 15, 5) }]);
});

test('막힘 · 연결 없음 · 상한 없음 · 수동 모드 아님 → 선택 안 됨 + 이유', () => {
  const { s, ctx } = session();
  assert.match(s.handle({ kind: 'button', group: 'select', channel: 1, down: true }, ctx())[0].text, /연결된 조인트가 없습니다/);
  assert.match(s.handle({ kind: 'button', group: 'select', channel: 2, down: true }, ctx())[0].text, /속도·가속도 상한을 먼저 채우세요/);
  assert.match(s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx({ blocked: '스케줄 모드' }))[0].text, /스케줄/);
  assert.equal(s.channels[0].selected, false);
  // 조종 중에 막히면 페이더 값을 안 보낸다
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  s.handle({ kind: 'touch', channel: 0, down: true }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 0) }, ctx({ blocked: '스케줄 모드' }));
  assert.equal(s.channels[0].phase, 'pickup');
});

test('SELECT 끔 · 보낸 적 있으면 release · 녹화 중 SELECT 는 녹화 축에 더함 · REC 는 녹화 토글', () => {
  const { s, ctx } = session({ 1: 0 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  s.handle({ kind: 'touch', channel: 0, down: true }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 0) }, ctx());
  s.tick(ctx());
  const off = s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  assert.deepEqual(off, [{ type: 'led', group: 'select', channel: 0, state: 'off' }, { type: 'release', axes: [1] }]);
  const on = s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx({ recording: true }));
  assert.deepEqual(on.at(-1), { type: 'record-add', axes: [1] });
  assert.deepEqual(s.handle({ kind: 'button', group: 'rec', channel: 5, down: true }, ctx()), [{ type: 'record-toggle' }]);
  assert.deepEqual(s.selectedAxes(), [1]);
  assert.deepEqual(s.reset().map((a) => a.type), ['led']);
  assert.deepEqual(s.selectedAxes(), []);
});

test('매핑이 바뀌어 연결이 달라진 채널은 놓는다', () => {
  const { s, ctx } = session({ 1: 0 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  assert.deepEqual(s.configure(channelConfig(rows, axisOf)), [], '같으면 그대로');
  const moved = rows.map((row) => (row.motion_id === 'neck_yaw' ? { ...row, motion_upper_deg: 20 } : row));
  assert.deepEqual(s.configure(channelConfig(moved, axisOf)).map((a) => a.type), ['led']);
  assert.equal(s.channels[0].selected, false);
});

test('녹화 불빛 · 카운트다운 깜빡 · 녹화 중 켬', () => {
  assert.equal(recordLed('countdown'), 'blink');
  assert.equal(recordLed('recording'), 'on');
  assert.equal(recordLed('idle'), 'off');
});

test('MIDI 를 못 쓰는 이유 · http 주소면 크롬 설정 안내', () => {
  assert.equal(midiUnavailableReason({ navigator: { requestMIDIAccess: () => {} } }), '');
  assert.match(midiUnavailableReason({ navigator: {}, isSecureContext: false, location: { origin: 'http://floating3.local:8000' } }),
    /chrome:\/\/flags\/#unsafely-treat-insecure-origin-as-secure.*floating3\.local:8000|floating3\.local:8000.*chrome:\/\/flags/);
  assert.match(midiUnavailableReason({ navigator: {}, isSecureContext: true }), /크롬이나 엣지/);
});

test('조인트 매핑 「X-Touch 페이더」 · 1 ~ 8 · 비우면 칸을 뺀다 · 같은 번호 두 줄은 저장 전에 막음', () => {
  assert.equal(faderNumber('3'), 3);
  assert.equal(faderNumber(0), null);
  assert.equal(faderNumber(9), null);
  assert.equal(faderNumber(''), null);
  const draft = rowToDraft({ motion_id: 'a', motion_lower_rad: -0.1, motion_upper_rad: 0.1, xtouch_fader: 2 });
  assert.equal(draft.xtouch_fader, 2);
  assert.equal(draftToRow(draft).xtouch_fader, 2);
  assert.equal('xtouch_fader' in draftToRow({ ...draft, xtouch_fader: null }), false);
  const base = { enabled: true, gear_ratio: 1, scale: 1, motion_lower_deg: -1, motion_upper_deg: 1 };
  const problems = draftProblems([
    { ...base, motion_id: 'a', motor_axis: 0, xtouch_fader: 1 },
    { ...base, motion_id: 'b', motor_axis: 1, xtouch_fader: 1 },
  ]);
  assert.ok(problems.some((p) => p.includes('X-Touch 페이더 1')), problems.join('\n'));
});

test('바탕 위 녹화 · 바탕 조인트는 선택 안 해도 재생 따라 · 잡으면 punch · 떼면 punch-release · 보통 축은 그대로', () => {
  const { s, ctx, jointNow } = session({ 1: 0, 4: 0 });
  assert.deepEqual(s.setTake(['neck_yaw']), []);
  assert.equal(s.isPunch(0), true);
  assert.equal(s.isPunch(2), false);
  jointNow[1] = 4;
  const follow = s.tick(ctx({ now: 500 }));
  assert.deepEqual(follow, [{ type: 'feedback', channel: 0, value: jointToFader(-15, 15, 4) }], '선택 안 해도 따라감');
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  s.handle({ kind: 'touch', channel: 0, down: true }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 4.1) }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 6) }, ctx());
  const sent = s.tick(ctx({ now: 520 }));
  assert.equal(sent[0].type, 'punch');
  assert.equal(sent[0].motionId, 'neck_yaw');
  assert.deepEqual(s.handle({ kind: 'touch', channel: 0, down: false }, ctx({ now: 600 })), []);
  assert.deepEqual(s.tick(ctx({ now: 900 })), [{ type: 'punch-release', motionId: 'neck_yaw' }]);
  assert.deepEqual(s.setTake([]).map((a) => a.type), ['led', 'punch-release'], '녹화 끝 · 잡던 덮어쓰기 채널은 놓음');
  assert.equal(s.isPunch(0), false);
});

test('여러 대 · 이 로봇이 고른 것 · 한 대면 그것 · 여러 대인데 안 골랐으면 아무것도 안 엶 (2026-10-19)', async () => {
  const { pickPort, matchOutput, robotTag } = await import('../static/v2/js/xtouch_model.js');
  const a = { id: 'in-a', name: 'X-Touch-Ext' };
  const b = { id: 'in-b', name: '2- X-Touch-Ext' };
  assert.equal(pickPort([], null).status, 'none');
  assert.equal(pickPort([a], null).port, a);
  const choose = pickPort([a, b], null);
  assert.equal(choose.port, null);
  assert.equal(choose.status, 'choose');
  assert.match(choose.message, /2대/);
  assert.equal(pickPort([a, b], { id: 'in-b', name: '2- X-Touch-Ext' }).port, b);
  assert.equal(pickPort([a, b], { id: 'gone', name: '2- X-Touch-Ext' }).port, b, 'id 가 바뀌어도 이름이 하나면');
  const missing = pickPort([a], { id: 'in-b', name: '2- X-Touch-Ext' });
  assert.equal(missing.port, null, '고른 것이 없으면 다른 것을 대신 열지 않음');
  assert.equal(missing.status, 'missing');
  const outA = { id: 'out-a', name: 'X-Touch-Ext' };
  const outB = { id: 'out-b', name: '2- X-Touch-Ext' };
  assert.equal(matchOutput(b, [a, b], [outA, outB]), outB, '이름이 같은 것 · 「X-Touch-Ext」 가 「2- X-Touch-Ext」 안에 들어 있어도 헷갈리지 않음');
  assert.equal(matchOutput(a, [a, b], [outA, outB]), outA);
  assert.equal(matchOutput(b, [a, b], [{ id: 'o1', name: 'MIDIOUT2 (X-Touch-Ext)' }, { id: 'o2', name: 'MIDIOUT3 (2- X-Touch-Ext)' }]).id, 'o2');
  assert.equal(robotTag('floating3'), 'f3');
  assert.equal(robotTag('floating12.local'), 'f12');
  assert.equal(robotTag('stage-a.local'), 'stage-a');
});

test('놓은 뒤 · 축이 아직 따라오는 중이면 페이더를 놓은 자리에 둔다 · 닿으면 다시 따라감 (툭 튀던 것 · 실물 2026-10-19)', () => {
  const { s, ctx, jointNow } = session({ 1: 5 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  s.handle({ kind: 'touch', channel: 0, down: true }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 5) }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, -10) }, ctx());   // 빠르게 아래로
  s.tick(ctx({ now: 0 }));
  s.handle({ kind: 'touch', channel: 0, down: false }, ctx());                          // 바로 놓음
  jointNow[1] = 3;                                                                      // 축은 아직 위쪽
  assert.deepEqual(s.tick(ctx({ now: 200 })).filter((a) => a.type === 'feedback'), [], '위로 안 보낸다');
  jointNow[1] = -2;
  assert.deepEqual(s.tick(ctx({ now: 600 })), [], '가는 중에도 그대로');
  jointNow[1] = -9.8;                                                                   // 닿음(0.5° 안)
  const near = s.tick(ctx({ now: 1000 }));
  assert.ok(near.every((a) => Math.abs(a.value - jointToFader(-15, 15, -10)) <= jointToFader(-15, 15, -9.5) - jointToFader(-15, 15, -10)),
    '닿은 뒤 보정은 놓은 자리 0.5° 안 · 튀지 않음');
  jointNow[1] = -6;                                                                     // 그 뒤엔 다시 따라감
  assert.equal(s.tick(ctx({ now: 1200 }))[0]?.type, 'feedback');
});

test('놓은 자리에 끝내 못 닿으면 8 s 뒤 다시 축을 따라감', async () => {
  const { SETTLE_MAX_MS } = await import('../static/v2/js/xtouch_model.js');
  const { s, ctx, jointNow } = session({ 1: 0 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx());
  s.handle({ kind: 'touch', channel: 0, down: true }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 0) }, ctx());
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 10) }, ctx());
  s.tick(ctx({ now: 0 }));
  s.handle({ kind: 'touch', channel: 0, down: false }, ctx());
  jointNow[1] = 2;                                                                      // 거절 등으로 멈춤
  assert.deepEqual(s.tick(ctx({ now: 500 })).filter((a) => a.type === 'feedback'), []);
  assert.deepEqual(s.tick(ctx({ now: 700 })), []);
  assert.equal(s.tick(ctx({ now: 700 + SETTLE_MAX_MS + 10 }))[0]?.type, 'feedback');
});

test('터치 신호가 안 오는 페이더 · 움직이면 손으로 침 · 0.5 s 멈추면 놓음 · 보낸 값이 되돌아온 것은 무시 (floating4 5번 · 2026-10-19)', () => {
  const { s, ctx } = session({ 1: 0 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx({ now: 0 }));   // 페이더를 0° 로 보냄
  const sent = jointToFader(-15, 15, 0);
  s.handle({ kind: 'fader', channel: 0, value: sent + 40 }, ctx({ now: 100 }));             // 모터 이동이 되돌아온 값
  assert.equal(s.channels[0].touched, false, '되돌아온 값은 손이 아님');
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 0.2) }, ctx({ now: 1000 }));
  assert.equal(s.channels[0].touched, true);
  assert.equal(s.channels[0].phase, 'live', '축 값 근처라 바로 잡음');
  s.handle({ kind: 'fader', channel: 0, value: jointToFader(-15, 15, 3) }, ctx({ now: 1100 }));
  const out = s.tick(ctx({ now: 1120 }));
  assert.equal(out[0].type, 'target');
  assert.ok(Math.abs(out[0].joint - 3) < 0.01);
  assert.deepEqual(s.tick(ctx({ now: 1400 })), [], '아직 0.5 s 안 지남');
  const release = s.tick(ctx({ now: 1700 }));
  assert.deepEqual(release.map((a) => a.type), ['release'], '0.5 s 멈춤 = 놓음');
  assert.equal(s.channels[0].touched, false);
});

test('되먹임 막기 · 보낸 뒤 1 s 안의 움직임(모터가 가는 중간 위치 포함)은 손이 아님 · 터치 신호를 보내는 채널은 움직임으로 안 침', () => {
  const { s, ctx } = session({ 1: 0 });
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx({ now: 0 }));
  s.handle({ kind: 'fader', channel: 0, value: 1000 }, ctx({ now: 300 }));                   // 가는 중간 위치(보낸 값과 멂)
  assert.equal(s.channels[0].touched, false);
  const other = session({ 1: 0 });
  other.s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, other.ctx({ now: 0 }));
  other.s.handle({ kind: 'touch', channel: 0, down: true }, other.ctx({ now: 100 }));
  other.s.handle({ kind: 'touch', channel: 0, down: false }, other.ctx({ now: 200 }));
  other.s.handle({ kind: 'fader', channel: 0, value: 2000 }, other.ctx({ now: 5000 }));      // 터치 없는 움직임
  assert.equal(other.s.channels[0].touched, false, '이 채널은 터치 신호를 보냄 · 움직임으로 안 침');
});

test('터치가 미는 도중 끊겼다 붙어도(floating4 4번 실물 기록) 조종은 이어지고 페이더를 되돌려 보내지 않음', () => {
  const { s, ctx, jointNow } = session({ 1: -9 });
  const v = (deg) => jointToFader(-15, 15, deg);
  s.handle({ kind: 'button', group: 'select', channel: 0, down: true }, ctx({ now: 0 }));
  s.handle({ kind: 'touch', channel: 0, down: true }, ctx({ now: 2000 }));
  s.handle({ kind: 'fader', channel: 0, value: v(-9) }, ctx({ now: 2010 }));
  const out = [];
  let t = 2010;
  for (let deg = -8.5; deg <= 2; deg += 0.5) {
    t += 50;
    if (Math.round(deg * 2) % 8 === 0) {          // 0.4 s 마다 끊겼다 25 ms 뒤 붙음
      out.push(...s.handle({ kind: 'touch', channel: 0, down: false }, ctx({ now: t })));
      out.push(...s.tick(ctx({ now: t + 10 })));
      out.push(...s.handle({ kind: 'touch', channel: 0, down: true }, ctx({ now: t + 25 })));
    }
    out.push(...s.handle({ kind: 'fader', channel: 0, value: v(deg) }, ctx({ now: t + 30 })));
    jointNow[1] = deg - 1;                         // 축은 조금 늦게 따라옴
    out.push(...s.tick(ctx({ now: t + 40 })));
  }
  assert.equal(out.filter((a) => a.type === 'release').length, 0, '끊김마다 놓지 않음');
  assert.equal(out.filter((a) => a.type === 'feedback').length, 0, '페이더를 되돌려 보내지 않음');
  const targets = out.filter((a) => a.type === 'target');
  assert.ok(targets.at(-1).joint > 1.5, `마지막 목표까지 따라감 ${targets.at(-1).joint}`);
  // 진짜로 놓음 · 0.2 s 뒤 확정
  s.handle({ kind: 'touch', channel: 0, down: false }, ctx({ now: t + 100 }));
  assert.deepEqual(s.tick(ctx({ now: t + 150 })).map((a) => a.type), []);
  assert.ok(s.tick(ctx({ now: t + 400 })).some((a) => a.type === 'release'));
});
