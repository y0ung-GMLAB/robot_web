import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { WORKSPACE_GROUPS, workspaceGroupFor, workspacePanelFor } from '../static/js/workspace_navigation.js';

/**
 * 터미널 · btop 탭 · §6-311
 *
 * 탭 하나는 네 곳이 맞아야 보인다 · 상단바 버튼 · 라우트 묶음 · 패널 조각 ·
 * 모듈 적재 · 어느 하나가 빠지면 버튼은 있는데 눌러도 빈 화면이거나, 패널은
 * 있는데 갈 길이 없다 · 그리고 xterm.js 는 CDN 이 아니라 저장소 안에 있어야
 * 한다 · 현장 PC 는 인터넷이 없을 수 있다.
 */

const shell = readFileSync(new URL('../static/index.html', import.meta.url), 'utf8');
const panelJs = readFileSync(new URL('../static/js/terminal_panel.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../static/css/13b-terminal.css', import.meta.url), 'utf8');

test('터미널 탭은 설정 묶음에 있고 제 패널로 간다', () => {
  assert.ok(WORKSPACE_GROUPS.setup.includes('terminal'));
  assert.equal(workspaceGroupFor('terminal'), 'setup');
  assert.equal(workspacePanelFor('terminal'), 'terminal');
  assert.match(indexHtml, /data-workspace-tab="terminal"/);
});

test('터미널 패널은 숨긴 채 시작하고 셸·btop 화면 둘을 가진다', () => {
  const section = indexHtml.match(/<section([^>]*data-workspace-panel="terminal"[^>]*)>/);
  assert.ok(section, '터미널 패널이 화면에 없다');
  assert.match(section[1], /\bhidden\b/);
  assert.match(indexHtml, /data-terminal-screen="shell"/);
  assert.match(indexHtml, /data-terminal-screen="btop"/);
  for (const id of ['terminalPicker', 'terminalStatus', 'terminalReconnectButton', 'terminalDisconnectButton']) {
    assert.match(indexHtml, new RegExp(`id="${id}"`), `${id} 가 없다`);
  }
});

test('셸이 CSS 와 모듈을 싣는다', () => {
  assert.match(shell, /13b-terminal\.css/);
  assert.match(shell, /js\/terminal_panel\.js/);
  const order = ['13-motion-trace.css', '13b-terminal.css', '14-redesign.css'].map((name) => shell.indexOf(name));
  assert.ok(order[0] < order[1] && order[1] < order[2], '터미널 CSS 는 재생 기록 뒤 · 재설계 층 앞에 실린다');
});

test('xterm.js 는 저장소 안에 있고 패널이 그 길을 쓴다', () => {
  for (const name of ['xterm.js', 'xterm.css', 'addon-fit.js', 'LICENSE']) {
    assert.ok(
      existsSync(new URL(`../static/vendor/xterm/${name}`, import.meta.url)),
      `vendor/xterm/${name} 이 없다 · npm pack 으로 받아 두세요`,
    );
  }
  assert.match(panelJs, /\/static\/vendor\/xterm/);
  assert.doesNotMatch(panelJs, /https?:\/\//, 'CDN 을 쓰면 인터넷 없는 PC 에서 안 뜬다');
});

test('패널은 서버의 두 길을 부른다', () => {
  const api = readFileSync(new URL('../static/js/api.js', import.meta.url), 'utf8');
  assert.match(panelJs, /'\/ws\/terminal'/);
  assert.match(api, /'\/api\/terminal\/programs'/);
  assert.match(panelJs, /fetchTerminalPrograms\(/);
});

test('숨겨지는 화면 칸은 display 를 :not(.hidden) 안에서만 정한다', () => {
  assert.match(css, /\.terminal-screen:not\(\.hidden\)\s*\{[^}]*display:/);
  assert.doesNotMatch(css, /^\.terminal-screen\s*\{[^}]*display:/m);
  assert.match(css, /\.terminal-panel:not\(\.hidden\)\s*\{[^}]*display:/);
});
