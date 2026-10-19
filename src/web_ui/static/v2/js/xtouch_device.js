/** UI v2 · X-Touch 장치 · Web MIDI · 수정 목록 156 (사용자 결정 2026-10-17)
 *
 * 이 화면을 연 PC(Windows · 크롬/엣지)에 꽂힌 X-Touch 를 브라우저가 직접 읽고 쓴다 · 로봇 PC 에는 MIDI 설치 없음.
 *
 * 보안 규칙 · Web MIDI 는 https · localhost 에서만 · 로봇 주소(http://floating<n>.local:8000)는
 *   그 PC 크롬에서 한 번 chrome://flags/#unsafely-treat-insecure-origin-as-secure 에 주소 추가 → 다시 시작 ·
 *   처음 연결할 때 MIDI 권한 허용 · 글씨 칸(SysEx)은 따로 허용 · 거절해도 조종은 된다.
 * Windows MIDI 는 한 프로그램만 장치를 연다 · 다른 프로그램이 쥐고 있으면 열기가 거절된다 → 「다른 곳에서 쓰는 중」.
 * USB 를 뽑았다 꽂으면 다시 붙는다(statechange).
 *
 * 여러 대(허브) · 사용자 결정 2026-10-19 · 로봇 화면마다 쓸 X-Touch 를 골라 그 로봇 주소에 기억(localStorage) ·
 * 여러 대인데 안 골랐으면 아무것도 안 연다 · 같은 로봇의 다른 탭이 같은 장치를 잡으면 먼저 탭이 놓는다(BroadcastChannel) ·
 * 다른 로봇 화면끼리는 브라우저가 주소별로 갈라 서로 모른다 → 글씨 칸에 로봇 표시(f3 등)로 눈으로 확인.
 */
import { looksLikeXTouch, lcdDeviceId, matchOutput, parseMidi, pickPort } from './xtouch_model.js';

const STORAGE_KEY = 'robotweb.xtouch.port';
const CLAIM_CHANNEL = 'robotweb-xtouch';

function loadPreferred() {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(STORAGE_KEY) || 'null');
    return value && (value.id || value.name) ? { id: String(value.id || ''), name: String(value.name || '') } : null;
  } catch { return null; }
}

function savePreferred(value) {
  try { globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(value)); } catch { /* 저장 못 하면 이번만 */ }
}

export const MIDI_FLAG_URL = 'chrome://flags/#unsafely-treat-insecure-origin-as-secure';

/** Web MIDI 를 쓸 수 없는 이유 · 빈 글자면 됨 */
export function midiUnavailableReason(win = globalThis) {
  if (typeof win.navigator?.requestMIDIAccess === 'function') return '';
  if (win.isSecureContext === false) {
    return `이 주소(${win.location?.origin || ''})는 http 라 브라우저가 MIDI 를 막습니다. 크롬에서 ${MIDI_FLAG_URL} 를 열고 이 주소를 추가한 뒤 크롬을 다시 시작하세요.`;
  }
  return '이 브라우저는 Web MIDI 를 지원하지 않습니다. 크롬이나 엣지에서 여세요.';
}

export class XTouchDevice {
  constructor({ onEvent = () => {}, onState = () => {}, onRaw = () => {} } = {}) {
    this.onEvent = onEvent;
    // 받은 그대로 · 화면 「MIDI 받은 것」 (진단 · 2026-10-19)
    this.onRaw = onRaw;
    this.onState = onState;
    this.access = null;
    this.input = null;
    this.output = null;
    this.deviceId = 0x15;
    this.sysex = false;
    this.attaching = null;
    this.again = false;
    this.preferred = loadPreferred();
    /** 연결된 X-Touch 입력 · 고르기 칸 */
    this.ports = [];
    this.tab = Math.random().toString(36).slice(2);
    this.claims = null;
    this.state = { status: 'off', name: '', message: '' };
  }

  /** 이 로봇에 쓸 장치를 고름 · 이 로봇 주소에 기억 · 바로 그것으로 다시 연다 */
  choose(portId) {
    const port = this.ports.find((item) => item.id === portId);
    if (!port) return Promise.resolve(false);
    this.preferred = { id: port.id, name: port.name };
    savePreferred(this.preferred);
    return this.attach();
  }

  /** 같은 로봇 화면의 다른 탭 · 같은 장치를 잡으면 먼저 잡은 탭이 놓는다 */
  listenClaims() {
    if (this.claims || typeof globalThis.BroadcastChannel !== 'function') return;
    this.claims = new BroadcastChannel(CLAIM_CHANNEL);
    this.claims.onmessage = (event) => {
      const claim = event?.data || {};
      if (claim.tab !== this.tab && this.input && claim.id === this.input.id) {
        this.disconnect('같은 로봇의 다른 탭(창)이 이 X-Touch 를 가져갔습니다 · 여기서는 놓았습니다');
      }
    };
  }

  setState(next) {
    this.state = { ...this.state, ...next };
    this.onState(this.state);
  }

  /** 연결 · 사람이 누른 버튼에서 부른다(권한 창) */
  async connect() {
    const reason = midiUnavailableReason();
    if (reason) { this.setState({ status: 'unavailable', message: reason }); return false; }
    this.setState({ status: 'connecting', message: '' });
    try {
      try {
        this.access = await navigator.requestMIDIAccess({ sysex: true });
        this.sysex = true;
      } catch {
        // 글씨 칸 권한만 거절 · 조종은 된다
        this.access = await navigator.requestMIDIAccess({ sysex: false });
        this.sysex = false;
      }
    } catch (error) {
      this.setState({ status: 'denied', message: `MIDI 권한이 거절되었습니다 · 주소창 왼쪽 자물쇠에서 MIDI 를 허용하세요 (${error?.message || error})` });
      return false;
    }
    // 뽑힘 · 꽂힘만 · 여는 중에도 statechange(connection) 가 오므로 연결 상태(state)가 바뀐 X-Touch 포트만 본다
    this.access.onstatechange = (event) => {
      const port = event?.port;
      if (!port || !looksLikeXTouch(port.name)) return;
      if (port.state === 'disconnected' || !this.input) this.attach();
      else this.refreshPorts();
    };
    this.listenClaims();
    return this.attach();
  }

  /** 포트를 찾아 연다 · 한 번에 하나씩(겹치면 끝난 뒤 한 번 더) */
  attach() {
    if (this.attaching) { this.again = true; return this.attaching; }
    this.attaching = (async () => {
      let ok = false;
      do {
        this.again = false;
        ok = await this.attachOnce();
      } while (this.again);
      this.attaching = null;
      return ok;
    })();
    return this.attaching;
  }

  connectedPorts() {
    const inputs = [...this.access.inputs.values()].filter((port) => looksLikeXTouch(port.name) && port.state === 'connected');
    const outputs = [...this.access.outputs.values()].filter((port) => looksLikeXTouch(port.name) && port.state === 'connected');
    return { inputs, outputs };
  }

  /** 고르기 칸 목록만 새로 · 꽂힌 장치가 늘거나 줄 때 */
  refreshPorts() {
    if (!this.access) return;
    this.ports = this.connectedPorts().inputs.map((port) => ({ id: port.id, name: port.name }));
    this.setState({});
  }

  async attachOnce() {
    if (!this.access) return false;
    const { inputs, outputs } = this.connectedPorts();
    this.ports = inputs.map((port) => ({ id: port.id, name: port.name }));
    const picked = pickPort(this.ports, this.preferred);
    const input = picked.port ? inputs.find((port) => port.id === picked.port.id) : null;
    const output = matchOutput(input, inputs, outputs);
    if (!input) {
      this.detach();
      this.setState({ status: picked.status === 'none' ? 'missing' : picked.status, name: '', message: picked.message });
      return false;
    }
    if (this.input === input && this.output === output && this.state.status === 'ready') return true;
    this.detach();
    try {
      await input.open();
      if (output) await output.open();
    } catch (error) {
      this.setState({ status: 'busy', name: input.name, message: `X-Touch 를 다른 곳에서 쓰는 중입니다 · 다른 탭이나 프로그램(DAW 등)을 닫고 다시 연결하세요 (${error?.name || error})` });
      return false;
    }
    this.input = input;
    this.output = output;
    this.deviceId = lcdDeviceId(input.name);
    input.onmidimessage = (message) => {
      const event = parseMidi(message.data);
      this.onRaw(Array.from(message.data || []), event);
      if (event) this.onEvent(event);
    };
    this.setState({ status: 'ready', name: input.name, message: output ? '' : '보낼 포트가 없어 페이더 모터·불빛이 움직이지 않습니다' });
    // 같은 로봇의 다른 탭에 알림 · 그 탭은 놓는다
    try { this.claims?.postMessage({ tab: this.tab, id: input.id }); } catch { /* 알림 못 해도 연결은 됨 */ }
    return true;
  }

  detach() {
    if (this.input) this.input.onmidimessage = null;
    for (const port of [this.input, this.output]) {
      try { port?.close?.(); } catch { /* 이미 닫힘 */ }
    }
    this.input = null;
    this.output = null;
  }

  disconnect(message = '') {
    if (this.access) this.access.onstatechange = null;
    this.detach();
    this.access = null;
    this.ports = [];
    this.setState({ status: 'off', name: '', message });
  }

  ready() {
    return this.state.status === 'ready';
  }

  send(bytes) {
    if (!this.output || (bytes[0] === 0xF0 && !this.sysex)) return false;
    try { this.output.send(bytes); return true; } catch { return false; }
  }
}
