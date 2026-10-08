import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';

const html = indexHtml;
const coordination = readFileSync(
  new URL('../static/js/coordination.js', import.meta.url), 'utf8',
);
const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');

/**
 * 「그룹 참여」 스위치 하나 · 수정 목록 83 (2026-10-09 사용자)
 *
 * 전에는 「연동 사용」(설정 · 저장·재시작) 과 「연동 참가 · 탈퇴」(버튼) 가 따로 있어 둘 다
 * 맞춰야 그룹으로 돌았다 · 「그룹 참여 · 미참여」 배지까지 이름이 셋이었다 · 하나로 합쳤다.
 *
 *   켜기  설정이 꺼져 있으면 enabled + joined 를 한 번에 저장(연동 재시작 한 번) · 켜져 있으면 join
 *   끄기  leave 만(재시작 없음 · 설정은 그대로) · 끄면 이 PC 혼자(스케줄도)
 */

test('설정 접이 칸은 열린 채로 · 「연동 사용」 선택은 없다', () => {
  assert.match(html, /<details class="coordination-settings-details" open>/);
  assert.doesNotMatch(html, /id="coordinationEnabled"/);
  assert.doesNotMatch(dom, /coordinationEnabled/);
  assert.doesNotMatch(coordination, /coordinationEnabled/);
  assert.doesNotMatch(html, /<span>연동 사용<\/span>/);
});

test('설정 칸은 역할이 맨 앞이다', () => {
  const fields = html.match(
    /<div class="coordination-settings-fields">[\s\S]*?<\/div>\s*<div class="coordination-settings-actions">/,
  )?.[0] || '';
  assert.ok(fields, '설정 칸 묶음을 읽지 못했다');
  const order = ['coordinationIsMaster', 'coordinationGroupId', 'coordinationPcId']
    .map((id) => fields.indexOf(id));
  assert.ok(order.every((at) => at >= 0), '세 칸이 모두 있어야 한다');
  assert.deepEqual([...order].sort((a, b) => a - b), order);
});

test('「그룹 참여」 스위치 하나 · 참가·탈퇴 버튼은 없다', () => {
  assert.match(html, /<input id="coordinationJoinSwitch" type="checkbox" role="switch"/);
  assert.match(html, /<span>그룹 참여<\/span>/);
  assert.match(dom, /coordinationJoinSwitch: document\.getElementById\('coordinationJoinSwitch'\)/);
  for (const gone of ['coordinationJoinButton', 'coordinationLeaveButton', '연동 참가', '연동 탈퇴']) {
    assert.doesNotMatch(html, new RegExp(gone));
    assert.doesNotMatch(dom, new RegExp(gone));
  }
  assert.match(coordination, /coordinationJoinSwitch\.checked = joined/);
  assert.match(coordination, /addEventListener\('change', onJoinSwitch\)/);
});

test('켜기는 설정이 꺼져 있으면 설정과 참가를 한 번에 · 켜져 있으면 join', () => {
  const body = coordination.match(/async function joinGroup\(\)[\s\S]*?\n  \}/)?.[0] || '';
  assert.ok(body);
  assert.match(body, /config\.enabled === true[\s\S]*control\('join'\)/);
  assert.match(body, /enabled: true, joined: true/);
  assert.match(body, /그룹 ID 가 없습니다/);
});

test('헤더에 번호를 붙이지 않는다', () => {
  for (const title of ['그룹 상태', '그룹 참가 PC', '그룹 실행']) {
    assert.match(html, new RegExp(`<strong>${title}</strong>`));
  }
  assert.doesNotMatch(html, /<strong>[1-3]\. (연동|그룹)/);
});

test('없앤 「지금 빠지기」가 코드에 남아 조용히 죽지 않는다', () => {
  // 요소가 사라졌는데 등록부와 쓰는 코드가 남으면 `if (el.X)` 안에서
  // 아무 일도 하지 않는다 · §6-61
  assert.doesNotMatch(html, /coordinationTemporaryDisableButton/);
  assert.doesNotMatch(dom, /coordinationTemporaryDisableButton/);
  assert.doesNotMatch(coordination, /coordinationTemporaryDisableButton/);
  assert.doesNotMatch(coordination, /temporarily_disable/);
});

test('무엇이 남고 무엇이 풀리는지 화면이 말한다', () => {
  // 참가·탈퇴는 **남는다** · §6-282 · 전에는 다시 켜면 설정만 보고 자동으로
  // 참가해서, 탈퇴가 화면에서만 막는 것처럼 보였다.
  assert.match(html, /켜고 끈 것은 프로그램을 다시 켜도 그대로 유지됩니다/);
  assert.match(html, /저장하면 계속 유지됩니다/);
});

test('끄기는 도는 중에 아예 눌리지 않는다', () => {
  // 전에는 도는 중에도 눌렸고, 누르면 **세 대를 다 세우고** 나갔다 ·
  // 한 대만 빼려던 사람이 공연을 멈췄다 · 이제 먼저 정지해야 한다 · §6-164
  assert.match(coordination, /coordinationJoinSwitch\.disabled =[^;]*\|\| active/);
  assert.match(coordination, /그룹 재생이 도는 중입니다 · 먼저 정지한 뒤 끄세요/);
});

test('끄기 확인창은 무엇이 남는지 말한다', () => {
  const body = coordination.match(
    /async function leaveGroup\(\)[\s\S]*?\n  \}/,
  )?.[0] || '';
  assert.ok(body, '확인창 코드를 읽지 못했다');
  assert.match(body, /이 PC 혼자 재생합니다/);
  assert.match(body, /프로그램을 다시 켜도 꺼진 채로 있습니다/);
  // 확인창은 글자 그대로 나온다 · 꾸밈 기호는 그대로 보인다
  assert.doesNotMatch(body, /\*\*/);
});
