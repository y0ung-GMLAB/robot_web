// 수정 목록 144 (실물 2026-10-14 11:35 · V-28 ③) · 재생 중 「프로그램 다시 시작」
// 서버가 `needs_stop` 으로 거절 → 두 번째 확인 「재생을 멈추고 다시 시작합니다 · 서보 토크는 유지됩니다」 →
// `stop_first: true` 로 다시 보냄 · 전에는 「프로젝트를 변경할 수 없습니다」 로 끝나 사람이 무엇을 할지 몰랐다
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { restartProgramFlow } from '../static/v2/js/actions.js';

function refusal(message, data) {
  const error = new Error(message);
  error.status = 200;
  error.data = data;
  return error;
}

function harness({ answers, replies }) {
  const asked = [];
  const sent = [];
  const confirm = async (options) => { asked.push(options); return answers.shift(); };
  const request = async (body) => {
    sent.push(body);
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  return { asked, sent, run: () => restartProgramFlow({ request, confirm }) };
}

const NEEDS_STOP = () => refusal('재생 중입니다 · 정지하고 다시 시작하려면 확인하세요', {
  success: false, needs_stop: true, message: '재생 중입니다 · 정지하고 다시 시작하려면 확인하세요',
});

test('쉬는 중 · 확인 한 번 · 바로 다시 시작', async () => {
  const h = harness({ answers: [true], replies: [{ success: true }] });
  assert.deepEqual(await h.run(), { success: true });
  assert.equal(h.asked.length, 1);
  assert.match(h.asked[0].body, /서보 토크는 유지됩니다/);
  assert.deepEqual(h.sent, [{}]);
});

test('재생 중 · 두 번째 확인 · 정지하고 다시 시작(stop_first)', async () => {
  const h = harness({ answers: [true, true], replies: [NEEDS_STOP(), { success: true, stopped_playback: true }] });
  assert.deepEqual(await h.run(), { success: true, stopped_playback: true });
  assert.equal(h.asked.length, 2);
  assert.equal(h.asked[1].body, '재생을 멈추고 다시 시작합니다 · 서보 토크는 유지됩니다');
  assert.equal(h.asked[1].tone, 'warning');
  assert.deepEqual(h.sent, [{}, { stop_first: true }]);
});

test('두 번째 확인에서 취소 · 아무것도 안 보냄 · null', async () => {
  const h = harness({ answers: [true, false], replies: [NEEDS_STOP()] });
  assert.equal(await h.run(), null);
  assert.deepEqual(h.sent, [{}]);
});

test('첫 확인에서 취소 · 요청 없음', async () => {
  const h = harness({ answers: [false], replies: [] });
  assert.equal(await h.run(), null);
  assert.deepEqual(h.sent, []);
});

test('다른 거절(모터 작업 중 등)은 두 번째 확인 없이 그대로 오류', async () => {
  const h = harness({
    answers: [true],
    replies: [refusal('모터 설정·검색·재시작 작업이 진행 중입니다 · 끝난 뒤 다시 시작하세요', { success: false })],
  });
  await assert.rejects(h.run(), /모터 설정·검색·재시작 작업이 진행 중입니다/);
  assert.equal(h.asked.length, 1);
  assert.deepEqual(h.sent, [{}]);
});

test('정지하고 다시 시작이 실패하면 그 이유로 오류', async () => {
  const h = harness({ answers: [true, true], replies: [NEEDS_STOP(), refusal('프로그램 재시작 요청에 실패했습니다', { success: false })] });
  await assert.rejects(h.run(), /프로그램 재시작 요청에 실패했습니다/);
});

test('버튼은 이 흐름을 쓴다 · 서버 몸통으로 보낸다', () => {
  const actions = readFileSync(new URL('../static/v2/js/actions.js', import.meta.url), 'utf8');
  const start = actions.indexOf('export async function restartProgram()');
  const body = actions.slice(start, actions.indexOf('\n}\n', start));
  assert.match(body, /restartProgramFlow\(/);
  assert.match(body, /api\('POST', '\/api\/system\/program\/restart', \{ body, timeoutMs: 20000 \}\)/);
  assert.match(body, /confirm: confirmBox/);
});

test('옛 화면도 두 번째 확인 뒤 stop_first 로 다시 보낸다', () => {
  const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
  const api = readFileSync(new URL('../static/js/api.js', import.meta.url), 'utf8');
  const start = main.indexOf("el.programRestartButton.addEventListener('click'");
  const handler = main.slice(start, main.indexOf("el.headerProgramRestartButton.addEventListener('click'"));
  assert.match(handler, /payload\?\.needs_stop[\s\S]*?재생을 멈추고 다시 시작합니다 · 서보 토크는 유지됩니다[\s\S]*?restartManagedProgram\(\{ stop_first: true \}\)/);
  assert.match(api, /restartManagedProgram = \(body = \{\}\) => request\('POST', '\/api\/system\/program\/restart', \{ body/);
});
