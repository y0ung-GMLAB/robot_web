import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { WORKSPACE_GROUPS, workspaceGroupFor, workspacePanelFor } from '../static/js/workspace_navigation.js';

/**
 * 터미널 · PC 성능 (btop) 탭 · 전신(motion_web §6-99)과 같은 구조로 되살렸다
 *
 * 둘 다 **별도 서비스**(ttyd · 8081 · 8080)를 iframe 으로 보여 준다 · 웹 브리지
 * 안에 두면 코드를 받아 다시 빌드할 때 그 화면이 올라가 있는 서버가 멈추면서
 * 터미널도 끊긴다 · 그래서 서버 코드가 아니라 화면 조각·유닛 파일만 있다.
 */

const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');

test('두 탭은 운영 묶음에 있고 제 패널로 간다', () => {
  for (const route of ['btop', 'terminal']) {
    assert.ok(WORKSPACE_GROUPS.operations.includes(route), `${route} 가 운영 묶음에 없다`);
    assert.equal(workspaceGroupFor(route), 'operations');
    assert.equal(workspacePanelFor(route), route);
    assert.match(indexHtml, new RegExp(`data-workspace-tab="${route}"`));
  }
});

test('패널은 숨긴 채 시작하고 iframe 하나씩 가진다', () => {
  for (const [route, id] of [['terminal', 'terminalIframe'], ['btop', 'btopIframe']]) {
    const section = indexHtml.match(new RegExp(`<section([^>]*data-workspace-panel="${route}"[^>]*)>`));
    assert.ok(section, `${route} 패널이 화면에 없다`);
    assert.match(section[1], /\bhidden\b/);
    assert.match(indexHtml, new RegExp(`<iframe id="${id}"`));
    assert.match(dom, new RegExp(`${id}: document\\.getElementById\\('${id}'\\)`));
  }
});

test('iframe 은 탭을 열 때 한 번만 · 터미널 8081 · btop 8080', () => {
  assert.match(main, /activePanel === 'terminal' && el\.terminalIframe && !el\.terminalIframe\.src/);
  assert.match(main, /terminalIframe\.src = `http:\/\/\$\{window\.location\.hostname\}:8081\/`/);
  assert.match(main, /activePanel === 'btop' && el\.btopIframe && !el\.btopIframe\.src/);
  assert.match(main, /btopIframe\.src = `http:\/\/\$\{window\.location\.hostname\}:8080\/`/);
});

test('터미널 화면에 갱신 명령이 적혀 있다 · git pull && 는 앞에 붙이지 않는다', () => {
  assert.match(indexHtml, /<pre class="terminal-howto-command">bash scripts\/install\.sh<\/pre>/);
  assert.doesNotMatch(indexHtml, /git pull &amp;&amp; bash|git pull && bash/);
});

test('유닛 파일의 포트가 화면과 같다', () => {
  const terminal = readFileSync(new URL('../../web_bridge/deploy/motion-terminal.service.in', import.meta.url), 'utf8');
  const btop = readFileSync(new URL('../../web_bridge/deploy/motion-btop.service', import.meta.url), 'utf8');
  const runner = readFileSync(new URL('../../web_bridge/deploy/run_terminal_service.sh', import.meta.url), 'utf8');
  assert.match(terminal, /run_terminal_service\.sh @WORKSPACE@/);
  assert.match(runner, /MOTION_WEB_TERMINAL_PORT:-8081/);
  assert.match(runner, /--writable/, 'ttyd 1.7 은 -W 가 없으면 읽기 전용이다');
  assert.match(btop, /ttyd -p 8080 \/usr\/bin\/btop/);
  for (const unit of [terminal, btop]) assert.match(unit, /Environment=LANG=C\.UTF-8/);
});
