/** 조그 다이얼 · 실시간 스트림 · 동작 취소 · 목표 위치 이동 · 눈금 띠 · ON/OFF · 실제 동작 시험
 *
 * 2026-10-02 처음 · 2026-10-07 조그 하나씩 → 페이더와 같은 스트림으로 바꿈(수정 목록 56) ·
 * 스위치(52) · 가짜 서버(fetch)와 가짜 WebSocket 을 넣고 컨트롤러를 그대로 돌린다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

// ---- 가짜 브라우저 · api.js 가 window.fetch 를 부른다 ----
const calls = [];
let respond = null;   // 시험이 손으로 응답을 내보낸다 · 가장 최근 요청
globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || { activeElement: null };
window.fetch = (url, options) => new Promise((resolve) => {
  const reply = (payload) => resolve({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => payload,
  });
  calls.push({ url, body: JSON.parse(options?.body || '{}'), reply });
  respond = reply;
});
window.setTimeout = (fn, ms) => setTimeout(fn, ms);
window.clearTimeout = (id) => clearTimeout(id);
window.setInterval = (fn, ms) => setInterval(fn, ms);
window.clearInterval = (id) => clearInterval(id);

// ---- 가짜 WebSocket · 열리면 hello 를 받고 hello_ok 를 돌려준다 ----
const sockets = [];
class FakeSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    sockets.push(this);
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.();
    }, 0);
  }

  send(text) {
    const message = JSON.parse(text);
    this.sent.push(message);
    if (message.type === 'hello') setTimeout(() => this.onmessage?.({ data: JSON.stringify({ type: 'hello_ok' }) }), 0);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}
globalThis.WebSocket = FakeSocket;
globalThis.location = { protocol: 'http:', host: 'robot.local:8000' };

// 화면은 모터 deg 로 부르고 서버에는 rad 로 간다 · 수정 목록 6-4 · 시험은 deg 로 되돌려 본다
const sentDeg = (value) => Math.round((value * 180) / Math.PI * 1e6) / 1e6;
const targets = () => sockets.flatMap((socket) => socket.sent).filter((message) => message.type === 'target');
const releases = () => sockets.flatMap((socket) => socket.sent).filter((message) => message.type === 'release');
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const tick = () => wait(0);

const { createJogDialController } = await import('../static/js/jog_dial.js');

const ELEMENTS = [
  'jogDial', 'jogDialRing', 'jogDialStep', 'jogDialPosition', 'jogDialPending',
  'jogDialMessage', 'jogDialCancelPending', 'jogDialSetReference', 'jogDialSetLower',
  'jogDialSetUpper', 'jogDialBlock', 'jogDialEnabledSwitch',
  'jogTargetInput', 'jogTargetMoveButton', 'jogDialMinus', 'jogDialPlus',
];

function fakeElement() {
  const listeners = {};
  const attrs = {};
  const classes = new Set();
  return {
    listeners,
    textContent: '',
    title: '',
    disabled: false,
    value: '',
    style: {},
    classList: {
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
      contains: (name) => classes.has(name),
    },
    setAttribute: (key, value) => { attrs[key] = String(value); },
    getAttribute: (key) => attrs[key] ?? null,
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    dispatch(type, event = {}) {
      for (const fn of listeners[type] || []) {
        fn({ preventDefault() {}, ...event });
      }
    },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }),
    focus() {},
  };
}

function setup({ position = 0, lower = -1000, upper = 1000, jointRow = null, jointMode = false } = {}) {
  calls.length = 0;
  sockets.length = 0;
  respond = null;
  const el = {};
  for (const name of ELEMENTS) el[name] = fakeElement();
  el.jogDialStep.value = '1';
  const motor = {
    controller_index: 1, state: 'detected', servo_on: true, fault: false,
    position_deg: position, motor_type: 'ac_servo', lower, upper,
  };
  const state = { motors: [motor] };
  // 조그 칸의 「조인트 deg 기준」 체크 · 다이얼도 따른다 · 76
  el.motionTestJogJointMode = fakeElement();
  el.motionTestJogJointMode.checked = jointMode;
  for (const name of ['jogDialStepLabel', 'jogDialPositionLabel', 'jogTargetLabel']) el[name] = fakeElement();
  const dial = createJogDialController({
    el, getLatestState: () => state, getSelectedAxis: () => 1,
    getJointRow: (axis) => (axis === 1 ? jointRow : null),
  });
  dial.bindEvents();
  dial.renderRuntimeState();
  el.jogDialEnabledSwitch.dispatch('click');                             // 화면을 열면 OFF · 켠다 (84)
  const wheel = (up = true) => el.jogDial.dispatch('wheel', { deltaY: up ? -100 : 100, deltaMode: 0 });
  const pendingText = () => el.jogDialPending.textContent;
  return { el, dial, motor, wheel, pendingText };
}

test('휠 한 칸 · 잡은 순간 위치에서 목표를 옮겨 스트림으로 보낸다 · 모터 deg · 56', async () => {
  const { dial, wheel, pendingText } = setup({ position: 10 });
  wheel();
  assert.equal(sockets.length, 1);
  assert.match(sockets[0].url, /^ws:\/\/robot\.local:8000\/ws\/manual-stream$/);
  assert.match(pendingText(), /남은 이동 \+1\.00°/);
  await wait(120);
  assert.deepEqual(sockets[0].sent[0], { type: 'hello' });
  const sent = targets();
  assert.ok(sent.length >= 1, '목표가 나가야 한다');
  assert.equal(sent[0].axis, 1);
  assert.equal(sentDeg(sent.at(-1).target_rad), 11);
  dial.reset();
  assert.deepEqual(releases().at(-1), { type: 'release', axes: [1] });
});

test('빨리 돌려도 한 번에 옮기는 양은 속도 상한까지 · 연결 전에는 앞서 나가지 않는다 · 56', async () => {
  const { dial, el } = setup({ position: 0 });
  el.jogDialStep.value = '360';
  el.jogDialStep.dispatch('input');
  for (let index = 0; index < 5; index += 1) el.jogDial.dispatch('wheel', { deltaY: -100 });   // +1800°
  await wait(140);
  const sent = targets().map((message) => sentDeg(message.target_rad));
  assert.ok(sent.length >= 1);
  // 1125 deg/s × 50 ms = 56.25° · 첫 목표가 56.25° 를 넘으면 튄 것이다
  assert.ok(Math.abs(sent[0]) <= 56.25 + 1e-6, `첫 목표 ${sent[0]}°`);
  for (let index = 1; index < sent.length; index += 1) {
    assert.ok(Math.abs(sent[index] - sent[index - 1]) <= 56.25 + 1e-6, '한 번에 상한을 넘겼다');
  }
  dial.reset();
});

test('목표는 모터 운전 한계 안으로 자른다', async () => {
  const { dial, el, wheel } = setup({ position: 0, upper: 2 });
  wheel(); wheel(); wheel();
  assert.match(el.jogDialMessage.textContent, /상한에 닿았습니다/);
  await wait(120);
  assert.ok(targets().every((message) => sentDeg(message.target_rad) <= 2 + 1e-6));
  dial.reset();
});

test('입력이 멈추고 도착하면 놓는다(release) · 서버가 지금 자리에 세운다', async () => {
  const { motor, wheel, pendingText } = setup({ position: 0 });
  wheel();
  await wait(80);
  motor.position_deg = 1;           // 도착
  await wait(300);
  assert.deepEqual(releases().at(-1), { type: 'release', axes: [1] });
  assert.equal(pendingText(), '대기');
});

test('동작 취소 · 놓고(release) 「모터 동작 정지」 와 같은 정지 요청 · 늘 누를 수 있다', async () => {
  const { el, wheel, pendingText } = setup();
  assert.equal(el.jogDialCancelPending.disabled, false);
  wheel(); wheel();
  await wait(60);
  el.jogDialCancelPending.dispatch('click');
  assert.equal(el.jogDialCancelPending.disabled, false);
  assert.deepEqual(releases().at(-1), { type: 'release', axes: [1] });
  assert.doesNotMatch(pendingText(), /남은 이동/);
  assert.ok(calls.some((call) => String(call.url).endsWith('/api/safety/motion-stop')), '정지 요청이 없다');
  respond({ success: true, message: 'stopped' });
  await tick(); await tick();
  assert.match(el.jogDialMessage.textContent, /동작을 취소했습니다/);
  const after = targets().length;
  await wait(120);
  assert.equal(targets().length, after, '취소 뒤에 또 보냈다');
});

test('서버 거절이 오면 그 사유를 보이고 이번 돌림을 끝낸다', async () => {
  const { el, wheel } = setup();
  wheel();
  await wait(80);
  sockets[0].onmessage({ data: JSON.stringify({ type: 'result', success: false, axis: 1, message: '1번 모터 서보가 꺼져 있습니다' }) });
  assert.match(el.jogDialMessage.textContent, /서보가 꺼져 있습니다/);
  assert.deepEqual(releases().at(-1), { type: 'release', axes: [1] });
  const after = targets().length;
  await wait(120);
  assert.equal(targets().length, after);
});

test('한 칸 크기를 바꾸면 돌리던 것을 지금 자리에 세운다', async () => {
  const { el, wheel, pendingText } = setup();
  wheel(); wheel();
  await wait(60);
  el.jogDialStep.value = '0.1';
  el.jogDialStep.dispatch('input');
  assert.doesNotMatch(pendingText(), /남은 이동/);
  assert.match(el.jogDialMessage.textContent, /한 칸 크기를 바꿔 지금 자리에 세웠습니다/);
  assert.deepEqual(releases().at(-1), { type: 'release', axes: [1] });
});

// 사용자 보고 · 모터를 안 골라도 0번 모터가 움직였다 (Number(null) === 0) · 2026-10-02
test('nothing selected means nothing moves · not motor 0', () => {
  calls.length = 0;
  sockets.length = 0;
  const el = {};
  for (const name of ELEMENTS) el[name] = fakeElement();
  el.jogDialStep.value = '1';
  const state = { motors: [{ controller_index: 0, state: 'detected', servo_on: true, fault: false, position_deg: 0, motor_type: 'ac_servo' }] };
  for (const selected of [null, '', undefined]) {
    const dial = createJogDialController({ el, getLatestState: () => state, getSelectedAxis: () => selected });
    dial.bindEvents();
    dial.renderRuntimeState();
    el.jogDial.dispatch('wheel', { deltaY: -100 });
    assert.equal(sockets.length, 0, `선택 ${String(selected)} 인데 열었다`);
    assert.equal(el.jogDial.getAttribute('aria-disabled'), 'true');
    assert.match(el.jogDialMessage.textContent, /모터를 먼저 선택하세요/);
  }
});

test('typed target (always shown next to the dial) moves in motor deg and refuses outside the limits', async () => {
  const { el } = setup();
  assert.equal(el.jogTargetInput.value, '0', '안 고쳤으면 지금 모터 위치');

  el.jogTargetInput.value = '2000';     // 상한 1000 밖
  el.jogTargetInput.dispatch('input');
  assert.equal(el.jogTargetMoveButton.disabled, true);
  el.jogTargetMoveButton.dispatch('click');
  assert.equal(calls.length, 0);
  assert.match(el.jogDialMessage.textContent, /운전 범위\(-1000° ~ 1000°\) 밖/);

  el.jogTargetInput.value = '250.5';
  el.jogTargetInput.dispatch('input');
  assert.equal(el.jogTargetMoveButton.disabled, false);
  el.jogTargetInput.dispatch('keydown', { key: 'Enter' });
  assert.equal(calls.length, 1);
  assert.match(String(calls[0].url), /\/api\/motion-test\/ac-servo\/action$/);
  assert.deepEqual(Object.keys(calls[0].body), ['axis', 'target_rad']);
  assert.equal(calls[0].body.axis, 1);
  assert.equal(sentDeg(calls[0].body.target_rad), 250.5);
  // 앞 요청이 도는 동안엔 또 안 보낸다
  el.jogTargetMoveButton.dispatch('click');
  assert.equal(calls.length, 1);
  respond({ success: true, message: 'ok' });
  await tick(); await tick();
  assert.match(el.jogDialMessage.textContent, /목표 250\.5° 로 이동 시작/);
});

// 다이얼과 목표 칸이 늘 같이 보인다 · 다이얼이 몰고 있으면 목표 이동은 기다린다 · 2026-10-06
test('typed target waits while the dial is still driving', async () => {
  const { el, dial, wheel } = setup();
  wheel();
  el.jogTargetInput.value = '10';
  el.jogTargetInput.dispatch('input');
  assert.equal(el.jogTargetMoveButton.disabled, true);
  el.jogTargetInput.dispatch('keydown', { key: 'Enter' });
  assert.equal(calls.filter((call) => /\/action$/.test(String(call.url))).length, 0);
  assert.match(el.jogDialMessage.textContent, /앞 이동이 끝난 뒤에/);
  dial.reset();
});

test('the tick strip slides with input and there is no needle', () => {
  const { el, dial, wheel } = setup();
  const before = el.jogDialRing.style.backgroundPositionX;
  wheel();
  const after = el.jogDialRing.style.backgroundPositionX;
  assert.notEqual(after, before, '휠 한 칸에 띠가 한 칸 밀려야 한다');
  assert.equal(after, '24px');
  dial.reset();

  // 바늘·기준 표시가 화면에 없다
  assert.doesNotMatch(indexHtml, /jogDialNeedle|jog-dial-needle|jog-wheel-pointer/);
  const css = readFileSync(new URL('../static/css/14-redesign.css', import.meta.url), 'utf8');
  assert.doesNotMatch(css, /jog-dial-needle/);
  // 눈금은 한 가지 모양만 반복한다 (기준 눈금 없음) · 간격 24px = 드래그 한 칸
  const ticks = css.match(/\.jog-dial-ticks \{[\s\S]*?\}/)[0];
  assert.match(ticks, /repeating-linear-gradient\(90deg, #0e1319 0 2px, transparent 2px 24px\)/);
  assert.match(indexHtml, /id="jogDialCancelPending"[^>]*>동작 취소</);
  assert.doesNotMatch(indexHtml, /id="jogDialCancelPending"[^>]*disabled/);
});

test('다이얼 · 오른쪽으로 24px 끌면 +1칸 · 왼쪽은 −1칸 · 띠는 손을 따라 밀린다', () => {
  const { el, dial, pendingText } = setup();
  el.jogDial.dispatch('pointerdown', { clientX: 100, clientY: 40, pointerId: 1 });
  el.jogDial.dispatch('pointermove', { clientX: 112, clientY: 40 });   // 반 칸 · 아직 안 쌓임
  assert.equal(el.jogDialRing.style.backgroundPositionX, '12px');
  assert.ok(el.jogDialRing.classList.contains('dragging'));
  assert.equal(sockets.length, 0);
  el.jogDial.dispatch('pointermove', { clientX: 148, clientY: 40 });   // 누적 48px = 2칸
  assert.match(pendingText(), /남은 이동 \+2\.00°/);
  el.jogDial.dispatch('pointermove', { clientX: 124, clientY: 40 });   // 왼쪽 24px = −1칸
  assert.match(pendingText(), /남은 이동 \+1\.00°/);
  assert.equal(el.jogDialRing.style.backgroundPositionX, '24px');      // 띠는 손 위치 그대로 (100 → 124)
  el.jogDial.dispatch('pointerup', { pointerId: 1 });
  assert.ok(!el.jogDialRing.classList.contains('dragging'));
  dial.reset();
});

test('Shift 는 한 칸의 1/10 · 휠은 굴린 양을 쌓아 100px 마다 한 칸 · 56', () => {
  const { el, dial, pendingText } = setup();
  el.jogDial.dispatch('wheel', { deltaY: -30, deltaMode: 0 });   // 트랙패드 잔 이벤트 · 아직 한 칸 아님
  assert.equal(pendingText(), '대기');
  el.jogDial.dispatch('wheel', { deltaY: -80, deltaMode: 0 });   // 누적 110px = 한 칸
  assert.match(pendingText(), /남은 이동 \+1\.00°/);
  el.jogDial.dispatch('keydown', { key: 'ArrowRight', shiftKey: true });
  assert.match(pendingText(), /남은 이동 \+1\.10°/);
  dial.reset();
});

test('◀ ▶ 화살표 · 한 번에 한 칸 · 잡고 있으면 반복 · 놓으면 멈춤', async () => {
  const { el, dial, pendingText } = setup();
  assert.equal(el.jogDialPlus.disabled, false, '모터가 골라져 있으면 화살표가 열린다');
  el.jogDialPlus.dispatch('pointerdown', { pointerId: 1 });
  assert.match(pendingText(), /남은 이동 \+1\.00°/);
  el.jogDialPlus.dispatch('pointerup', { pointerId: 1 });
  dial.reset();

  el.jogDialMinus.dispatch('pointerdown', { pointerId: 2 });
  await wait(700);                                                      // 400ms 뒤부터 120ms 마다 반복
  assert.match(pendingText(), /남은 이동 -[3-9]\.00°/, '잡고 있으면 반복해서 쌓여야 한다');
  el.jogDialMinus.dispatch('pointerup', { pointerId: 2 });
  const held = pendingText();
  await wait(130);
  assert.equal(pendingText(), held, '놓으면 반복이 멈춘다');
  dial.reset();
});

test('ON/OFF 스위치 · 끄면 다이얼만 잠그고 돌리던 것은 세운다 · 목표 이동은 그대로 · 52', async () => {
  const { el, dial, wheel, pendingText } = setup();
  assert.equal(el.jogDialEnabledSwitch.getAttribute('aria-checked'), 'true');
  wheel();
  await wait(60);
  el.jogDialEnabledSwitch.dispatch('click');                             // OFF
  assert.equal(el.jogDialEnabledSwitch.getAttribute('aria-checked'), 'false');
  assert.equal(el.jogDialEnabledSwitch.textContent, '다이얼 OFF');
  assert.equal(el.jogDial.getAttribute('aria-disabled'), 'true');
  assert.ok(el.jogDial.classList.contains('locked'));
  assert.equal(el.jogDialPlus.disabled, true);
  assert.deepEqual(releases().at(-1), { type: 'release', axes: [1] });
  const opened = sockets.length;
  el.jogDial.dispatch('keydown', { key: 'ArrowRight' });                // 키도 잠김
  el.jogDial.dispatch('wheel', { deltaY: -100 });
  assert.equal(pendingText(), '대기');
  assert.equal(sockets.length, opened);
  // 목표 위치 이동은 스위치와 무관
  el.jogTargetInput.value = '5';
  el.jogTargetInput.dispatch('input');
  assert.equal(el.jogTargetMoveButton.disabled, false);
  el.jogDialEnabledSwitch.dispatch('click');                             // 다시 ON
  assert.equal(el.jogDial.getAttribute('aria-disabled'), 'false');
  dial.reset();
});

test('모터를 고르면(reset) 돌리던 것이 없어도 다시 그린다 · 「모터를 먼저 선택하세요」 가 남지 않는다', () => {
  calls.length = 0;
  sockets.length = 0;
  const el = {};
  for (const name of ELEMENTS) el[name] = fakeElement();
  el.jogDialStep.value = '1';
  const state = { motors: [{ controller_index: 1, state: 'detected', servo_on: true, fault: false, position_deg: 3, motor_type: 'ac_servo' }] };
  let selected = null;
  const dial = createJogDialController({ el, getLatestState: () => state, getSelectedAxis: () => selected });
  dial.bindEvents();
  dial.renderRuntimeState();
  assert.match(el.jogDialMessage.textContent, /모터를 먼저 선택하세요/);
  selected = '1';
  dial.reset();                        // main.js · 모터 고르기 change → reset
  assert.equal(el.jogDialMessage.textContent, '');
  assert.equal(el.jogDialPosition.textContent, '3.00°');
  assert.equal(el.jogDial.getAttribute('aria-disabled'), 'true', '화면을 열면 OFF (84)');
  el.jogDialEnabledSwitch.dispatch('click');
  assert.equal(el.jogDial.getAttribute('aria-disabled'), 'false');
});

// ---- 조인트 deg 체크를 다이얼도 따른다 · 수정 목록 76 (2026-10-08) ----
// 목 상하처럼 감속 150 · 방향 반전 · 기준점 1000 (모터 deg)
const NECK = { motion_id: '1-1', gear_ratio: 150, scale: 1, invert: true, reference_position_deg: 1000, offset_deg: 0 };

test('체크 켜짐 · 한 칸 1° = 조인트 1° = 모터 −150° (감속비 × 방향) · 표시도 조인트 deg · 76', async () => {
  const { el, dial, wheel, pendingText } = setup({ position: 1000, lower: -100000, upper: 100000, jointRow: NECK, jointMode: true });
  assert.equal(el.jogDialPositionLabel.textContent, '조인트 위치');
  assert.equal(el.jogDialPosition.textContent, '0.000°', '기준점 = 조인트 0°');
  assert.equal(el.jogDialStepLabel.textContent, '다이얼 한 칸 = (조인트 deg)');
  assert.equal(el.jogTargetLabel.textContent, '목표 위치 (조인트 deg)');
  wheel();
  assert.match(pendingText(), /남은 이동 \+1\.00°/, '남은 양도 조인트 deg');
  await wait(200);
  assert.equal(sentDeg(targets().at(-1).target_rad), 1000 - 150, '모터에는 −150°');
  dial.reset();
});

test('체크 꺼짐 · 매핑이 있어도 한 칸 = 모터 deg (지금까지와 같음) · 76', async () => {
  const { el, dial, wheel } = setup({ position: 1000, lower: -100000, upper: 100000, jointRow: NECK, jointMode: false });
  assert.equal(el.jogDialPositionLabel.textContent, '모터 위치');
  wheel();
  await wait(120);
  assert.equal(sentDeg(targets().at(-1).target_rad), 1001);
  dial.reset();
});

test('매핑이 없으면 체크가 켜져 있어도 모터 deg · 76', async () => {
  const { el, dial, wheel } = setup({ position: 5, jointRow: null, jointMode: true });
  assert.equal(el.jogDialPositionLabel.textContent, '모터 위치');
  wheel();
  await wait(120);
  assert.equal(sentDeg(targets().at(-1).target_rad), 6);
  dial.reset();
});

test('목표 위치 · 조인트 deg 로 받아 매핑 식으로 모터 deg 로 보낸다 · 범위 글도 조인트 · 76', async () => {
  // 모터 한계 −500 ~ 2500 = 조인트 (1000 − m) / 150 → −10 ~ +10
  const { el } = setup({ position: 1000, lower: -500, upper: 2500, jointRow: NECK, jointMode: true });
  assert.equal(el.jogTargetInput.value, '0', '지금 위치를 조인트 deg 로 채움');
  el.jogTargetInput.value = '12';
  el.jogTargetInput.dispatch('input');
  assert.equal(el.jogTargetMoveButton.disabled, true);
  el.jogTargetMoveButton.dispatch('click');
  assert.match(el.jogDialMessage.textContent, /목표 12° 가 운전 범위\(-10° ~ 10°\) 밖/);
  el.jogTargetInput.value = '2';
  el.jogTargetInput.dispatch('input');
  el.jogTargetMoveButton.dispatch('click');
  assert.equal(calls.length, 1);
  assert.equal(sentDeg(calls[0].body.target_rad), 1000 - 300, '조인트 2° = 모터 700°');
  respond({ success: true });
  await tick(); await tick();
});

test('체크를 바꾸면 돌리던 것을 세우고 목표 칸을 새 단위로 다시 채운다 · 76', async () => {
  const { el, wheel } = setup({ position: 1000, lower: -100000, upper: 100000, jointRow: NECK, jointMode: true });
  wheel();
  await wait(60);
  el.motionTestJogJointMode.checked = false;
  el.motionTestJogJointMode.dispatch('change');
  assert.deepEqual(releases().at(-1), { type: 'release', axes: [1] });
  assert.equal(el.jogTargetInput.value, '1000', '모터 deg 로 다시 채움');
});

test('화면을 열면 다이얼은 OFF · 켜야 돈다 · 기억하지 않는다 · 84', async () => {
  calls.length = 0;
  sockets.length = 0;
  const el = {};
  for (const name of ELEMENTS) el[name] = fakeElement();
  el.jogDialStep.value = '1';
  const state = { motors: [{ controller_index: 1, state: 'detected', servo_on: true, fault: false, position_deg: 0, motor_type: 'ac_servo' }] };
  const dial = createJogDialController({ el, getLatestState: () => state, getSelectedAxis: () => 1 });
  dial.bindEvents();
  dial.renderRuntimeState();
  assert.equal(el.jogDialEnabledSwitch.getAttribute('aria-checked'), 'false');
  assert.equal(el.jogDialEnabledSwitch.textContent, '다이얼 OFF');
  assert.ok(el.jogDial.classList.contains('locked'));
  el.jogDial.dispatch('wheel', { deltaY: -100, deltaMode: 0 });
  assert.equal(sockets.length, 0, 'OFF 에서는 움직이지 않는다');
  el.jogDialEnabledSwitch.dispatch('click');
  assert.equal(el.jogDialEnabledSwitch.textContent, '다이얼 ON');
  assert.ok(el.jogDialEnabledSwitch.classList.contains('on'));
  dial.reset();
});
