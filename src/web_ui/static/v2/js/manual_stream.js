/** UI v2 · /ws/manual-stream · 수동 실시간 목표 (다이얼 · 페이더 같이) (설계안 2026-10-09)
 *
 * 규약(서버 manual_stream_socket.py) ·
 *   ← {type:'hello', mapping_file_id?, base_mapping_revision?} → {type:'hello_ok'} | {type:'error'} 후 닫힘
 *   ← {type:'target', axis, target_rad, motion_id?, motion_rad?, source?}   (모터 rad · source fader|dial)
 *   ← {type:'release', axes:[..]}  → 마지막 목표까지 천천히 간 뒤 선다 (수정 목록 126)
 *   ← {type:'stop', axes:[..]}     → 그 자리에 선다 (페이지를 떠날 때)
 *   → {type:'result', success, message}
 *   X-Touch 화면(수정 목록 156) · 인사에 watchdog_sec · ← ping → pong · ← record_start|record_add|record_stop|record_cancel → record
 * 목표는 「가고 싶은 곳」 · 서버가 조인트 2 °/s · 4 °/s² 로 천천히 다가간다 (수정 목록 126).
 * 수동 모드가 아니면 서버가 거절하고 닫는다 · 끊기면 서버가 만졌던 축을 그 자리에 세운다.
 */

export class ManualStream {
  constructor({ onResult = () => {}, onClose = () => {}, onMessage = () => {} } = {}) {
    this.onResult = onResult;
    this.onClose = onClose;
    // 그 밖의 응답(X-Touch · pong · record) · 수정 목록 156
    this.onMessage = onMessage;
    this.socket = null;
    this.ready = null;
    this.hello = null;
  }

  /** 열기 · 같은 인사면 있는 것을 쓴다 · Promise<true> 또는 거절 이유로 reject */
  open(hello = {}) {
    const key = JSON.stringify(hello);
    if (this.ready && this.hello === key && this.socket?.readyState <= 1) return this.ready;
    this.close();
    this.hello = key;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/ws/manual-stream`);
    this.socket = socket;
    this.ready = new Promise((resolve, reject) => {
      let settled = false;
      socket.onopen = () => socket.send(JSON.stringify({ type: 'hello', ...hello }));
      socket.onmessage = (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === 'hello_ok' && !settled) { settled = true; resolve(true); return; }
        if (message.type === 'error') {
          if (!settled) { settled = true; reject(new Error(message.message || '수동 조작이 거부되었습니다')); }
          this.onClose(message.message || '');
          return;
        }
        if (message.type === 'result') this.onResult(message);
        else this.onMessage(message);
      };
      socket.onclose = () => {
        if (!settled) { settled = true; reject(new Error('수동 조작 연결이 끊겼습니다')); }
        if (this.socket === socket) { this.socket = null; this.ready = null; }
        this.onClose('');
      };
      socket.onerror = () => {};
    });
    return this.ready;
  }

  isOpen() {
    return this.socket?.readyState === 1;
  }

  /** 보냈으면 true · 안 열렸으면 false(보낸 것으로 치지 않는다) */
  target(axis, targetRad, extra = {}) {
    if (!this.isOpen()) return false;
    this.socket.send(JSON.stringify({ type: 'target', axis, target_rad: targetRad, ...extra }));
    return true;
  }

  release(axes) {
    if (!this.isOpen()) return false;
    this.socket.send(JSON.stringify({ type: 'release', axes }));
    return true;
  }

  /** 그 밖의 요청 · ping · 녹화(수정 목록 156) · 보냈으면 true */
  send(payload) {
    if (!this.isOpen()) return false;
    this.socket.send(JSON.stringify(payload));
    return true;
  }

  /** 그 자리에 세운다 · 놓기와 달리 남은 이동을 버린다 */
  stop(axes) {
    if (!this.isOpen()) return false;
    this.socket.send(JSON.stringify({ type: 'stop', axes }));
    return true;
  }

  close() {
    const socket = this.socket;
    this.socket = null;
    this.ready = null;
    if (socket && socket.readyState <= 1) socket.close();
  }
}
