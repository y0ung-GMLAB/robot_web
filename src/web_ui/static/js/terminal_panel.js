/** 터미널 · btop · 이 PC 의 셸을 브라우저 안에서 연다 · §6-311
 *
 * **다른 PC 의 터미널에 URL 로 닿는 길이 없었다.** 현장 PC 는 모니터 없이
 * 돌고 사람은 다른 PC 의 브라우저 앞에 있다 · 깃을 받거나 로그를 보려면
 * SSH 를 따로 열어야 했다 · 웹 화면은 이미 모든 PC 에 열려 있으니 그 안에
 * 터미널을 둔다.
 *
 * 그리는 것은 xterm.js(`/static/vendor/xterm/`) · 잇는 것은 `/ws/terminal`
 * · 셸·btop 은 서버의 PTY 안에서 돈다 (`terminal_service.py`).
 *
 * 탭을 처음 열 때 xterm.js 를 읽는다 · 290KB 를 첫 화면에 얹지 않는다.
 * 탭을 떠나도 세션은 끊지 않는다 · 긴 `git pull` 중에 다른 탭을 봐도 된다.
 */

import { fetchTerminalPrograms } from './api.js';

const VENDOR = '/static/vendor/xterm';
const SOCKET_PATH = '/ws/terminal';

const THEME = Object.freeze({
  background: '#0b0f14',
  foreground: '#d9e1ea',
  cursor: '#d9e1ea',
  selectionBackground: 'rgba(120, 160, 220, 0.35)',
});

const panel = document.querySelector('[data-workspace-panel="terminal"]');

/** xterm.js 두 파일과 CSS · 한 번만 · 전역 `Terminal`·`FitAddon` 을 남긴다 */
let vendorLoading = null;
function loadVendor() {
  if (vendorLoading) return vendorLoading;
  const script = (src) => new Promise((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = src;
    tag.onload = resolve;
    tag.onerror = () => reject(new Error(`${src} 을(를) 읽지 못했습니다`));
    document.head.appendChild(tag);
  });
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = `${VENDOR}/xterm.css`;
  document.head.appendChild(link);
  vendorLoading = script(`${VENDOR}/xterm.js`)
    .then(() => script(`${VENDOR}/addon-fit.js`))
    .catch((error) => {
      vendorLoading = null;
      throw error;
    });
  return vendorLoading;
}

function socketUrl(program, cols, rows) {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const query = new URLSearchParams({ program, cols: String(cols), rows: String(rows) });
  return `${protocol}://${location.host}${SOCKET_PATH}?${query}`;
}

/** 프로그램 하나의 화면 + 소켓 · 셸과 btop 이 각각 하나씩 가진다 */
class TerminalTab {
  constructor(program, screen, onStatus) {
    this.program = program;
    this.screen = screen;
    this.onStatus = onStatus;
    this.terminal = null;
    this.fit = null;
    this.socket = null;
    this.state = 'idle';
    this.lastMessage = '';
    this.resizeObserver = null;
  }

  ensureTerminal() {
    if (this.terminal) return;
    this.terminal = new window.Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"DejaVu Sans Mono", "Noto Sans Mono", Menlo, Consolas, monospace',
      scrollback: 5000,
      theme: THEME,
      allowProposedApi: false,
    });
    this.fit = new window.FitAddon.FitAddon();
    this.terminal.loadAddon(this.fit);
    this.terminal.open(this.screen);
    this.terminal.onData((data) => this.send({ type: 'input', data }));
    this.terminal.onResize(({ cols, rows }) => this.send({ type: 'resize', cols, rows }));
    this.resizeObserver = new ResizeObserver(() => this.refit());
    this.resizeObserver.observe(this.screen);
    this.refit();
  }

  refit() {
    if (!this.fit || this.screen.classList.contains('hidden')) return;
    try {
      this.fit.fit();
    } catch {
      // 아직 그려지지 않은 칸 · 다음 크기 변화 때 다시 맞춘다
    }
  }

  send(payload) {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(payload));
  }

  connected() {
    return this.socket && this.socket.readyState !== WebSocket.CLOSED;
  }

  connect() {
    if (this.connected()) return;
    this.ensureTerminal();
    this.refit();
    this.terminal.focus();
    const { cols, rows } = this.terminal;
    this.setState('connecting', '연결 중');
    const socket = new WebSocket(socketUrl(this.program, cols, rows));
    socket.binaryType = 'arraybuffer';
    socket.onmessage = (event) => this.receive(event.data);
    socket.onclose = () => {
      // 우리가 끊은 소켓이면 상태는 이미 적었다 · 서버가 끊은 것만 여기서 말한다
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.state !== 'error' && this.state !== 'exited') this.setState('closed', '연결이 끊어졌습니다 · 「다시 연결」');
    };
    socket.onerror = () => {
      if (this.socket === socket) this.setState('error', '서버에 닿지 못했습니다');
    };
    this.socket = socket;
  }

  receive(data) {
    if (typeof data !== 'string') {
      this.terminal.write(new Uint8Array(data));
      return;
    }
    let message;
    try {
      message = JSON.parse(data);
    } catch {
      return;
    }
    if (message.type === 'ready') {
      this.setState('ready', `${message.program} 실행 중 · PID ${message.pid}`);
      this.refit();
    } else if (message.type === 'exit') {
      this.setState('exited', `프로세스가 끝났습니다 (코드 ${message.code}) · 「다시 연결」`);
      this.terminal.write(`\r\n\x1b[90m[프로세스 종료 · 코드 ${message.code}]\x1b[0m\r\n`);
    } else if (message.type === 'error') {
      this.setState('error', message.message || '오류');
      this.terminal.write(`\r\n\x1b[31m${message.message || '오류'}\x1b[0m\r\n`);
    }
  }

  disconnect() {
    if (!this.socket) return;
    const socket = this.socket;
    this.socket = null;
    socket.close();
    this.setState('closed', '끊었습니다 · 「다시 연결」');
  }

  reconnect() {
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      socket.close();
    }
    this.terminal?.reset();
    this.state = 'idle';
    this.connect();
  }

  setState(state, message) {
    this.state = state;
    this.lastMessage = message;
    this.onStatus(this);
  }
}

if (panel) {
  const picker = document.getElementById('terminalPicker');
  const status = document.getElementById('terminalStatus');
  const subtitle = document.getElementById('terminalSubtitle');
  const reconnectButton = document.getElementById('terminalReconnectButton');
  const disconnectButton = document.getElementById('terminalDisconnectButton');
  const screens = new Map(
    [...panel.querySelectorAll('[data-terminal-screen]')]
      .map((screen) => [screen.dataset.terminalScreen, screen]),
  );

  const state = {
    active: 'shell',
    programs: new Map(),
    enabled: true,
    tabs: new Map(),
  };

  const TONES = {
    ready: 'tone-ok',
    connecting: '',
    closed: 'tone-warn',
    exited: 'tone-warn',
    error: 'tone-error',
    idle: '',
  };

  function renderStatus(tab) {
    if (tab.program !== state.active) return;
    status.textContent = tab.lastMessage || '연결 전';
    status.className = `terminal-status ${TONES[tab.state] || ''}`.trim();
  }

  function tabFor(program) {
    if (!state.tabs.has(program)) {
      state.tabs.set(program, new TerminalTab(program, screens.get(program), renderStatus));
    }
    return state.tabs.get(program);
  }

  function renderPicker() {
    picker.querySelectorAll('[data-terminal-tab]').forEach((button) => {
      const program = button.dataset.terminalTab;
      const active = program === state.active;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      const info = state.programs.get(program);
      if (info && !info.available) {
        button.title = `${info.executable} 이(가) 이 PC 에 없습니다 · ${info.install_hint}`;
        button.classList.add('missing');
      }
    });
    screens.forEach((screen, program) => {
      screen.classList.toggle('hidden', program !== state.active);
    });
  }

  function unavailableMessage(program) {
    if (!state.enabled) return '웹 터미널이 꺼져 있습니다 · MOTION_WEB_TERMINAL=0';
    const info = state.programs.get(program);
    if (info && !info.available) {
      return `${info.executable} 이(가) 이 PC 에 없습니다 · 설치: ${info.install_hint}`;
    }
    return '';
  }

  async function open(program) {
    state.active = program;
    renderPicker();
    const blocked = unavailableMessage(program);
    if (blocked) {
      status.textContent = blocked;
      status.className = 'terminal-status tone-error';
      return;
    }
    try {
      await loadVendor();
    } catch (error) {
      status.textContent = String(error.message || error);
      status.className = 'terminal-status tone-error';
      return;
    }
    const tab = tabFor(program);
    tab.connect();
    tab.refit();
    renderStatus(tab);
  }

  async function loadPrograms() {
    try {
      const payload = await fetchTerminalPrograms();
      state.enabled = payload.enabled !== false;
      state.programs = new Map((payload.programs || []).map((item) => [item.id, item]));
      if (subtitle && !state.enabled) subtitle.textContent = '웹 터미널이 꺼져 있습니다';
    } catch {
      // 목록을 못 읽어도 연결은 시도한다 · 서버가 거절하면 그 말을 보여 준다
    }
  }

  picker.addEventListener('click', (event) => {
    const button = event.target.closest('[data-terminal-tab]');
    if (!button) return;
    open(button.dataset.terminalTab);
  });

  reconnectButton?.addEventListener('click', async () => {
    if (unavailableMessage(state.active)) return open(state.active);
    await loadVendor().catch(() => null);
    const tab = tabFor(state.active);
    tab.reconnect();
    return undefined;
  });

  disconnectButton?.addEventListener('click', () => {
    state.tabs.get(state.active)?.disconnect();
  });

  let openedOnce = false;
  async function onShown() {
    if (!openedOnce) {
      openedOnce = true;
      await loadPrograms();
      await open(state.active);
      return;
    }
    state.tabs.get(state.active)?.refit();
  }

  // 탭을 눌러 이 화면이 보일 때 연다 · 패널의 `hidden` 이 곧 신호다
  new MutationObserver(() => {
    if (!panel.classList.contains('hidden')) onShown();
  }).observe(panel, { attributes: true, attributeFilter: ['class'] });

  if (!panel.classList.contains('hidden')) onShown();
}
