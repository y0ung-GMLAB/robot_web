/** UI v2 · X-Touch 장치 · Web MIDI · 수정 목록 156 (사용자 결정 2026-10-17)
 *
 * 이 화면을 연 PC(Windows · 크롬/엣지)에 꽂힌 X-Touch 를 브라우저가 직접 읽고 쓴다 · 로봇 PC 에는 MIDI 설치 없음.
 *
 * 보안 규칙 · Web MIDI 는 https · localhost 에서만 · 로봇 주소(http://floating<n>.local:8000)는
 *   그 PC 크롬에서 한 번 chrome://flags/#unsafely-treat-insecure-origin-as-secure 에 주소 추가 → 다시 시작 ·
 *   처음 연결할 때 MIDI 권한 허용 · 글씨 칸(SysEx)은 따로 허용 · 거절해도 조종은 된다.
 * Windows MIDI 는 한 프로그램만 장치를 연다 · 다른 프로그램이 쥐고 있으면 열기가 거절된다 → 「다른 곳에서 쓰는 중」.
 * USB 를 뽑았다 꽂으면 다시 붙는다(statechange).
 */
import { looksLikeXTouch, lcdDeviceId, parseMidi } from './xtouch_model.js';

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
  constructor({ onEvent = () => {}, onState = () => {} } = {}) {
    this.onEvent = onEvent;
    this.onState = onState;
    this.access = null;
    this.input = null;
    this.output = null;
    this.deviceId = 0x15;
    this.sysex = false;
    this.attaching = null;
    this.again = false;
    this.state = { status: 'off', name: '', message: '' };
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
    };
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

  async attachOnce() {
    if (!this.access) return false;
    const inputs = [...this.access.inputs.values()].filter((port) => looksLikeXTouch(port.name) && port.state === 'connected');
    const outputs = [...this.access.outputs.values()].filter((port) => looksLikeXTouch(port.name) && port.state === 'connected');
    const input = inputs[0] || null;
    const output = outputs.find((port) => input && sameDevice(port.name, input.name)) || outputs[0] || null;
    if (!input) {
      this.detach();
      this.setState({ status: 'missing', name: '', message: 'X-Touch 를 찾지 못했습니다 · USB 를 확인하세요' });
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
      if (event) this.onEvent(event);
    };
    this.setState({ status: 'ready', name: input.name, message: output ? '' : '보낼 포트가 없어 페이더 모터·불빛이 움직이지 않습니다' });
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

  disconnect() {
    if (this.access) this.access.onstatechange = null;
    this.detach();
    this.access = null;
    this.setState({ status: 'off', name: '', message: '' });
  }

  ready() {
    return this.state.status === 'ready';
  }

  send(bytes) {
    if (!this.output || (bytes[0] === 0xF0 && !this.sysex)) return false;
    try { this.output.send(bytes); return true; } catch { return false; }
  }
}

/** 같은 장치의 입력·출력 이름 · Windows 는 「X-Touch-Ext」 · 「MIDIOUT2 (X-Touch-Ext)」 처럼 다를 수 있다 */
function sameDevice(a, b) {
  const key = (name) => String(name || '').toLowerCase().replace(/midi(in|out)\d*|[()\s]/g, '');
  return key(a) === key(b) || key(a).includes(key(b)) || key(b).includes(key(a));
}
