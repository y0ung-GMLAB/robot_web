/** 오래 걸리는 일 표시 · 수정 목록 87 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { busyText, createBusyIndicator, SHOW_AFTER_MS } from '../static/js/motion_busy.js';

function fakeEl() {
  const classes = new Set(['hidden']);
  return {
    textContent: '',
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c),
    },
  };
}

function fakeTimers() {
  let t = 0;
  const pending = [];
  return {
    now: () => t,
    timers: {
      setTimeout: (fn, ms) => { const job = { fn, at: t + ms, every: 0 }; pending.push(job); return job; },
      setInterval: (fn, ms) => { const job = { fn, at: t + ms, every: ms }; pending.push(job); return job; },
      clearTimeout: (job) => { const i = pending.indexOf(job); if (i >= 0) pending.splice(i, 1); },
      clearInterval: (job) => { const i = pending.indexOf(job); if (i >= 0) pending.splice(i, 1); },
    },
    advance(ms) {
      const end = t + ms;
      for (;;) {
        const due = pending.filter((job) => job.at <= end).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        t = due.at;
        if (due.every) due.at += due.every; else pending.splice(pending.indexOf(due), 1);
        due.fn();
      }
      t = end;
    },
  };
}

test('짧게 끝나는 일은 안 보이고 · 0.4초 넘으면 무엇을 · 몇 초째인지 보인다', () => {
  const clock = fakeTimers();
  const el = { motionBusy: fakeEl(), motionBusyText: fakeEl() };
  const busy = createBusyIndicator({ el, now: clock.now, timers: clock.timers });
  busy.begin('files', '애니메이션 읽는 중');
  clock.advance(SHOW_AFTER_MS - 50);
  busy.end('files');
  clock.advance(1000);
  assert.ok(el.motionBusy.classList.contains('hidden'), '짧은 일은 깜빡이지 않는다');

  busy.begin('upload', '올리는 중 1/1');
  clock.advance(SHOW_AFTER_MS + 10);
  assert.ok(!el.motionBusy.classList.contains('hidden'));
  assert.equal(el.motionBusyText.textContent, '올리는 중 1/1');
  clock.advance(3000);                                               // 1초마다 다시 그린다
  assert.equal(el.motionBusyText.textContent, '올리는 중 1/1 · 3초');
  busy.begin('files', '애니메이션 읽는 중');                         // 겹쳐도 된다 · 마지막 글자
  assert.match(el.motionBusyText.textContent, /^애니메이션 읽는 중/);
  busy.end('files');
  assert.match(el.motionBusyText.textContent, /^올리는 중 1\/1/);
  busy.end('upload');
  assert.ok(el.motionBusy.classList.contains('hidden'));
});

test('run 은 실패해도 표시를 내린다', async () => {
  const clock = fakeTimers();
  const el = { motionBusy: fakeEl(), motionBusyText: fakeEl() };
  const busy = createBusyIndicator({ el, now: clock.now, timers: clock.timers });
  await assert.rejects(busy.run('x', '하는 중', async () => { throw new Error('boom'); }));
  assert.equal(busy.active, false);
  assert.equal(busyText('a', 0.5), 'a');
});

test('올리기 · 읽기 · 재생 등록이 표시를 쓴다 · 등록 중엔 다시 못 누른다', () => {
  assert.match(indexHtml, /<div id="motionBusy" class="motion-busy hidden" role="status"/);
  const data = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
  assert.match(data, /busy\.begin\('upload', `올리는 중/);
  assert.match(data, /busy\.begin\('register'/);
  assert.match(data, /if \(l\) busy\.begin\('files'/);
  assert.match(data, /async function registerSelectedMotionFile\(\) \{\n    if \(mappingLoading\) return;/);
  const css = readFileSync(new URL('../static/css/07-motion.css', import.meta.url), 'utf8');
  assert.match(css, /@keyframes motion-busy-spin/);
});
