/** 조그 다이얼 · 쌓인 양 취소와 눈금 링 · 실제 동작 시험 · 2026-10-02
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
let respond = null;   // 시험이 손으로 응답을 내보낸다
globalThis.window = globalThis.window || {};
window.fetch = (url, options) => new Promise((resolve) => {
  calls.push({ url, body: JSON.parse(options?.body || '{}') });
  respond = (payload) => resolve({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => payload,
  });
});
window.setTimeout = (fn, ms) => setTimeout(fn, ms);
window.clearTimeout = (id) => clearTimeout(id);

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
    'jogDialSetUpper',
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

test('cancel drops only the unsent amount and the in-flight reply cannot revive it', async () => {
  const { el, wheel, pendingText } = setup();
  wheel();                         // +1 · 바로 날아간다
  assert.equal(calls.length, 1);
  assert.equal(calls[0].body.relative_deg, 1);
  wheel(); wheel(); wheel();       // +3 · 앞 조그가 도는 동안 쌓인다
  assert.match(pendingText(), /보낼 양 \+3\.00°/);
  assert.equal(el.jogDialCancelPending.disabled, false, '쌓인 양이 있으면 켜진다');

  el.jogDialCancelPending.dispatch('click');
  assert.equal(el.jogDialCancelPending.disabled, true, '비운 뒤엔 꺼진다');
  assert.doesNotMatch(pendingText(), /보낼 양/);
  assert.match(el.jogDialMessage.textContent, /움직이던 조그는 끝까지/);

  // 날아가던 요청이 「이전 조그」로 거절돼도 취소한 양을 되살리지 않는다
  respond({ success: false, message: '1번 모터의 이전 조그가 아직 돌고 있습니다' });
  await tick(); await tick();
  await new Promise((resolve) => setTimeout(resolve, 200));   // 재시도 간격(120ms)보다 길게
  assert.equal(calls.length, 1, '취소 뒤에 다시 보냈다');
  assert.doesNotMatch(pendingText(), /보낼 양/);
});

test('changing the step size clears the unsent amount', async () => {
  const { el, wheel, pendingText } = setup();
  wheel();                         // 날아감
  wheel(); wheel();                // 쌓임 +2
  assert.match(pendingText(), /보낼 양 \+2\.00°/);
  el.jogDialStep.value = '0.1';
  el.jogDialStep.dispatch('input');
  assert.doesNotMatch(pendingText(), /보낼 양/);
  assert.match(el.jogDialMessage.textContent, /한 칸 크기를 바꿔 쌓인 양을 비웠습니다/);
  assert.equal(el.jogDialCancelPending.disabled, true);
  respond({ success: true, message: 'ok' });
  await tick(); await tick();
  assert.equal(calls.length, 1, '비운 양이 이어서 나가면 안 된다');
});

test('the cancel button is off when nothing is queued, even while a jog is moving', () => {
  const { el, wheel } = setup();
  assert.equal(el.jogDialCancelPending.disabled, true, '처음엔 꺼져 있다');
  wheel();                         // 날아가는 중 · 쌓인 양은 0
  assert.equal(el.jogDialCancelPending.disabled, true, '날아가는 것만 있으면 비울 게 없다');
});

test('the tick ring turns with input and there is no needle', () => {
  const { el, wheel } = setup();
  const before = el.jogDialRing.style.transform;
  wheel();
  const after = el.jogDialRing.style.transform;
  assert.notEqual(after, before, '휠 한 칸에 링이 돌아야 한다');
  assert.equal(after, 'rotate(15deg)');

  // 바늘·기준 표시가 화면에 없다
  assert.doesNotMatch(indexHtml, /jogDialNeedle|jog-dial-needle/);
  const css = readFileSync(new URL('../static/css/14-redesign.css', import.meta.url), 'utf8');
  assert.doesNotMatch(css, /jog-dial-needle/);
  // 눈금은 한 가지 모양만 반복한다 (기준 눈금 없음)
  const ticks = css.match(/\.jog-dial-ticks \{[\s\S]*?\}/)[0];
  assert.match(ticks, /repeating-conic-gradient\(#56647a 0deg 2deg, transparent 2deg 15deg\)/);
  assert.match(indexHtml, /id="jogDialCancelPending"[^>]*>쌓인 양 취소</);
});
