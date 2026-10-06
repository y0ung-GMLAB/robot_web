/** 조그 다이얼 · 동작 취소 · 목표 위치 이동 · 눈금 링 · 실제 동작 시험 · 2026-10-02
 *
 * 가짜 서버 응답을 넣고 컨트롤러를 그대로 돌린다 · 소스 글자만 훑는 시험으로는
 * 「취소했는데 날아가던 요청의 거절 응답이 그 양을 되살리는」 경로를 못 잡는다.
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
const jogCalls = () => calls.filter((call) => String(call.url).includes('/jog'));
// 화면은 모터 deg 로 부르고 서버에는 rad 로 간다 · 수정 목록 6-4 · 시험은 deg 로 되돌려 본다
const sentDeg = (value) => Math.round((value * 180) / Math.PI * 1e9) / 1e9;
window.setTimeout = (fn, ms) => setTimeout(fn, ms);
window.clearTimeout = (id) => clearTimeout(id);
window.setInterval = (fn, ms) => setInterval(fn, ms);
window.clearInterval = (id) => clearInterval(id);

const { createJogDialController } = await import('../static/js/jog_dial.js');

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

function setup() {
  calls.length = 0;
  respond = null;
  const el = {};
  for (const name of [
    'jogDial', 'jogDialRing', 'jogDialStep', 'jogDialPosition', 'jogDialPending',
    'jogDialMessage', 'jogDialCancelPending', 'jogDialSetReference', 'jogDialSetLower',
    'jogDialSetUpper', 'jogDialBlock',
    'jogTargetInput', 'jogTargetMoveButton', 'jogDialMinus', 'jogDialPlus',
  ]) el[name] = fakeElement();
  el.jogDialStep.value = '1';
  const state = {
    motors: [{
      controller_index: 1, state: 'detected', servo_on: true, fault: false,
      position_deg: 0, motor_type: 'ac_servo', lower: -1000, upper: 1000,
    }],
  };
  const dial = createJogDialController({
    el, getLatestState: () => state, getSelectedAxis: () => 1,
  });
  dial.bindEvents();
  dial.renderRuntimeState();
  const wheel = (up = true) => el.jogDial.dispatch('wheel', { deltaY: up ? -100 : 100 });
  const pendingText = () => el.jogDialPending.textContent;
  return { el, dial, wheel, pendingText };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test('동작 취소 drops the unsent amount, stops motion, and the in-flight reply cannot revive it', async () => {
  const { el, wheel, pendingText } = setup();
  wheel();                         // +1 · 바로 날아간다
  assert.equal(jogCalls().length, 1);
  assert.equal(sentDeg(jogCalls()[0].body.relative_rad), 1);
  const inFlightJog = jogCalls()[0];
  wheel(); wheel(); wheel();       // +3 · 앞 조그가 도는 동안 쌓인다
  assert.match(pendingText(), /남은 이동 \+3\.00°/);

  el.jogDialCancelPending.dispatch('click');
  assert.doesNotMatch(pendingText(), /남은 이동/);
  // 움직이던 것도 멈춘다 · 「모터 동작 정지」와 같은 경로
  assert.ok(calls.some((call) => String(call.url).endsWith('/api/safety/motion-stop')), '정지 요청이 없다');
  respond({ success: true, message: 'stopped' });
  await tick(); await tick();
  assert.match(el.jogDialMessage.textContent, /동작을 취소했습니다/);

  // 날아가던 요청이 「이전 조그」로 거절돼도 취소한 양을 되살리지 않는다
  inFlightJog.reply({ success: false, message: '1번 모터의 이전 조그가 아직 돌고 있습니다' });
  await tick(); await tick();
  await new Promise((resolve) => setTimeout(resolve, 200));   // 재시도 간격(120ms)보다 길게
  assert.equal(jogCalls().length, 1, '취소 뒤에 다시 보냈다');
  assert.doesNotMatch(pendingText(), /남은 이동/);
});

test('changing the step size clears the unsent amount', async () => {
  const { el, wheel, pendingText } = setup();
  wheel();                         // 날아감
  wheel(); wheel();                // 쌓임 +2
  assert.match(pendingText(), /남은 이동 \+2\.00°/);
  el.jogDialStep.value = '0.1';
  el.jogDialStep.dispatch('input');
  assert.doesNotMatch(pendingText(), /남은 이동/);
  assert.match(el.jogDialMessage.textContent, /한 칸 크기를 바꿔 쌓인 양을 비웠습니다/);
  respond({ success: true, message: 'ok' });
  await tick(); await tick();
  assert.equal(jogCalls().length, 1, '비운 양이 이어서 나가면 안 된다');
});

// 사용자 보고 · 모터를 안 골라도 0번 모터가 움직였다 (Number(null) === 0) · 2026-10-02
test('nothing selected means nothing moves · not motor 0', () => {
  calls.length = 0;
  const el = {};
  for (const name of [
    'jogDial', 'jogDialRing', 'jogDialStep', 'jogDialPosition', 'jogDialPending',
    'jogDialMessage', 'jogDialCancelPending', 'jogDialSetReference', 'jogDialSetLower',
    'jogDialSetUpper', 'jogDialBlock',
    'jogTargetInput', 'jogTargetMoveButton', 'jogDialMinus', 'jogDialPlus',
  ]) el[name] = fakeElement();
  el.jogDialStep.value = '1';
  const state = { motors: [{ controller_index: 0, state: 'detected', servo_on: true, fault: false, position_deg: 0, motor_type: 'ac_servo' }] };
  for (const selected of [null, '', undefined]) {
    const dial = createJogDialController({ el, getLatestState: () => state, getSelectedAxis: () => selected });
    dial.bindEvents();
    dial.renderRuntimeState();
    el.jogDial.dispatch('wheel', { deltaY: -100 });
    assert.equal(calls.length, 0, `선택 ${String(selected)} 인데 보냈다`);
    assert.equal(el.jogDial.getAttribute('aria-disabled'), 'true');
    assert.match(el.jogDialMessage.textContent, /모터를 먼저 선택하세요/);
  }
});

test('동작 취소 is always pressable', () => {
  const { el, wheel } = setup();
  assert.equal(el.jogDialCancelPending.disabled, false, '처음부터 켜져 있다');
  wheel();
  assert.equal(el.jogDialCancelPending.disabled, false, '움직이는 중에도 켜져 있다');
});

test('typed target (always shown next to the dial) moves in motor deg and refuses outside the limits', async () => {
  const { el } = setup();
  assert.equal(el.jogTargetInput.value, '0', '안 고쳤으면 지금 모터 위치');

  el.jogTargetInput.value = '2000';     // 상한 1000 밖
  el.jogTargetInput.dispatch('input');
  assert.equal(el.jogTargetMoveButton.disabled, true);
  el.jogTargetMoveButton.dispatch('click');
  assert.equal(calls.length, 0);
  assert.match(el.jogDialMessage.textContent, /상한 1000° 밖/);

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

// 다이얼과 목표 칸이 늘 같이 보인다 · 다이얼 양이 남았으면 목표 이동은 기다린다 · 2026-10-06
test('typed target waits while dial ticks are still pending', async () => {
  const { el, wheel, pendingText } = setup();
  wheel();                         // 날아감
  wheel();                         // 쌓임 +1
  assert.match(pendingText(), /남은 이동/);
  el.jogTargetInput.value = '10';
  el.jogTargetInput.dispatch('input');
  assert.equal(el.jogTargetMoveButton.disabled, true);
  el.jogTargetInput.dispatch('keydown', { key: 'Enter' });
  assert.equal(calls.filter((call) => /\/action$/.test(String(call.url))).length, 0);
  assert.match(el.jogDialMessage.textContent, /앞 이동이 끝난 뒤에/);
});

test('the tick strip slides with input and there is no needle', () => {
  const { el, wheel } = setup();
  const before = el.jogDialRing.style.backgroundPositionX;
  wheel();
  const after = el.jogDialRing.style.backgroundPositionX;
  assert.notEqual(after, before, '휠 한 칸에 띠가 한 칸 밀려야 한다');
  assert.equal(after, '24px');

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
  const { el, pendingText } = setup();
  el.jogDial.dispatch('pointerdown', { clientX: 100, clientY: 40, pointerId: 1 });
  el.jogDial.dispatch('pointermove', { clientX: 112, clientY: 40 });   // 반 칸 · 아직 안 쌓임
  assert.equal(el.jogDialRing.style.backgroundPositionX, '12px');
  assert.ok(el.jogDialRing.classList.contains('dragging'));
  assert.equal(jogCalls().length, 0);
  el.jogDial.dispatch('pointermove', { clientX: 148, clientY: 40 });   // 누적 48px = 2칸 · 바로 날아간다
  assert.equal(jogCalls().length, 1);
  assert.equal(sentDeg(jogCalls()[0].body.relative_rad), 2);
  el.jogDial.dispatch('pointermove', { clientX: 124, clientY: 40 });   // 왼쪽 24px = −1칸 · 앞 조그가 도는 동안 쌓임
  assert.match(pendingText(), /남은 이동 -1\.00°/);
  assert.equal(el.jogDialRing.style.backgroundPositionX, '24px');      // 띠는 손 위치 그대로 (100 → 124)
  el.jogDial.dispatch('pointerup', { pointerId: 1 });
  assert.ok(!el.jogDialRing.classList.contains('dragging'));
});

test('◀ ▶ 화살표 · 한 번에 한 칸 · 잡고 있으면 반복 · 놓으면 멈춤', async () => {
  const { el, pendingText } = setup();
  assert.equal(el.jogDialPlus.disabled, false, '모터가 골라져 있으면 화살표가 열린다');
  el.jogDialPlus.dispatch('pointerdown', { pointerId: 1 });
  assert.equal(jogCalls().length, 1);
  assert.equal(sentDeg(jogCalls()[0].body.relative_rad), 1);
  el.jogDialPlus.dispatch('pointerup', { pointerId: 1 });
  await new Promise((resolve) => setTimeout(resolve, 600));
  assert.doesNotMatch(pendingText(), /남은 이동/, '놓은 뒤에는 더 쌓이면 안 된다');

  el.jogDialMinus.dispatch('pointerdown', { pointerId: 2 });           // 앞 조그가 도는 동안 · 쌓임
  assert.match(pendingText(), /남은 이동 -1\.00°/);
  await new Promise((resolve) => setTimeout(resolve, 700));            // 400ms 뒤부터 120ms 마다 반복
  assert.match(pendingText(), /남은 이동 -[3-9]\.00°/, '잡고 있으면 반복해서 쌓여야 한다');
  el.jogDialMinus.dispatch('pointerup', { pointerId: 2 });
  const held = pendingText();
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(pendingText(), held, '놓으면 반복이 멈춘다');
});
