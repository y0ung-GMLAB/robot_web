/** UI v2 · 서버와 말하기 · 요청 하나 · 상태 소켓 하나 (설계안 2026-10-09)
 *
 * 프로젝트 세대 · 서버가 상태마다 실어 주는 `project_generation` 을 기억했다가 요청에 붙인다 ·
 * 그사이 프로젝트가 바뀌었으면 서버가 409 로 버린다(엉뚱한 프로젝트에 명령이 가지 않게).
 */

let generation = null;

export function rememberGeneration(value) {
  const parsed = Number(value);
  if (Number.isInteger(parsed) && parsed >= 0) generation = parsed;
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/** JSON 요청 · 실패면 서버가 준 이유로 ApiError */
export async function api(method, path, { body, timeoutMs = 15000 } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (generation !== null) headers['X-Project-Generation'] = String(generation);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(path, {
      method, headers, signal: controller.signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new ApiError(error?.name === 'AbortError' ? '응답이 너무 늦습니다' : '서버에 닿지 않습니다', 0);
  } finally {
    clearTimeout(timer);
  }
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { message: text }; }
  if (!response.ok || data?.success === false) {
    const reason = data?.message || data?.detail || `요청 실패 (${response.status})`;
    throw new ApiError(typeof reason === 'string' ? reason : JSON.stringify(reason), response.status);
  }
  return data;
}

/** `/ws/status` · 끊기면 1 → 2 → 4 … 최대 8초 간격으로 다시 붙는다 */
export class StatusStream {
  constructor(onSnapshot, onConnection) {
    this.onSnapshot = onSnapshot;
    this.onConnection = onConnection;
    this.delay = 1000;
    this.socket = null;
    this.closed = false;
  }

  start() {
    this.closed = false;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/ws/status`);
    this.socket = socket;
    socket.onopen = () => { this.delay = 1000; this.onConnection(true); };
    socket.onmessage = (event) => {
      try {
        const snap = JSON.parse(event.data);
        rememberGeneration(snap?.project_generation);
        this.onSnapshot(snap);
      } catch { /* 한 장 깨져도 다음 장을 기다린다 */ }
    };
    socket.onclose = () => {
      this.onConnection(false);
      if (this.closed) return;
      setTimeout(() => this.start(), this.delay);
      this.delay = Math.min(this.delay * 2, 8000);
    };
    socket.onerror = () => socket.close();
  }

  stop() {
    this.closed = true;
    this.socket?.close();
  }
}

/** 몇 초마다 읽기 · 화면이 안 보이면(다른 탭) 쉰다 */
export function poll(fn, intervalMs) {
  let timer = null;
  const run = async () => {
    if (!document.hidden) {
      try { await fn(); } catch { /* 다음 차례에 다시 */ }
    }
    timer = setTimeout(run, intervalMs);
  };
  run();
  return () => clearTimeout(timer);
}
