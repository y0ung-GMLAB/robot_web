/** 모든 PC 업데이트 · 같은 망 로봇 PC 마다 `install.sh --code-only` · 2026-10-08 (사용자 요청)
 *
 * 버튼 하나 → 이 PC 서버가 같은 망 PC 표(`runtime.network_pcs`)의 연결된 로봇 PC 마다 그 PC 의
 * `POST /api/system/update` 를 대신 부른다(이 PC 는 맨 뒤) · 진행은 `GET /api/system/update-all` 을
 * 3초마다 · 업데이트 중인 PC 는 웹이 잠깐 내려가서 「응답 없음」 이 정상 · 이 PC 자신도 업데이트되면
 * 이 화면이 잠깐 끊겼다 돌아온다 · 스피커 PC 는 다른 설치라 안내만.
 */
import { fetchSystemUpdateAll, requestSystemUpdateAll } from './api.js';
import { escapeHtml } from './format.js';
import { showConfirm } from './ui_dialogs.js';

const POLL_MS = 3000;
//: 시작 뒤 이만큼은 계속 본다 · 다 끝났다고 나와도 늦게 뜨는 PC 가 있다
const WATCH_AFTER_START_MS = 15 * 60 * 1000;

const STATE_TEXT = {
  idle: ['대기', ''],
  running: ['업데이트 중', 'coordination-state-warn'],
  done: ['완료', 'coordination-state-ok'],
  failed: ['실패', 'coordination-state-bad'],
  unreachable: ['응답 없음 (재시작 중일 수 있음)', 'coordination-state-warn'],
  offline: ['연결 안 됨', 'coordination-state-bad'],
  manual: ['터미널에서', ''],
};

export function systemUpdateRows(pcs) {
  const list = Array.isArray(pcs) ? pcs : [];
  if (!list.length) return '<tr><td colspan="4" class="empty">같은 망 PC 를 기다리는 중</td></tr>';
  return list.map((pc) => {
    const [label, cls] = STATE_TEXT[pc.state] || [String(pc.state || '-'), ''];
    const name = pc.display_name || pc.pc_id || '-';
    const local = pc.is_local ? ' <small>(이 PC)</small>' : '';
    const tail = Array.isArray(pc.tail) && pc.tail.length ? pc.tail[pc.tail.length - 1] : '';
    const note = pc.message || tail || '';
    const version = pc.before_hash && pc.git_hash && pc.before_hash !== pc.git_hash
      ? `${pc.before_hash} → ${pc.git_hash}`
      : (pc.git_hash || '-');
    return `<tr>
      <td><strong>${escapeHtml(name)}</strong>${local}</td>
      <td class="${cls}">${escapeHtml(label)}</td>
      <td class="mono">${escapeHtml(version)}</td>
      <td title="${escapeHtml((pc.tail || []).join('\n'))}">${escapeHtml(note)}</td>
    </tr>`;
  }).join('');
}

export function createSystemUpdateController({ el }) {
  let timer = null;
  let watchUntil = 0;
  let busy = false;

  function setMessage(text) {
    if (!el.systemUpdateMessage) return;
    el.systemUpdateMessage.textContent = text || '';
    el.systemUpdateMessage.classList.toggle('hidden', !text);
  }

  async function refresh() {
    try {
      const payload = await fetchSystemUpdateAll();
      if (el.systemUpdateRows) el.systemUpdateRows.innerHTML = systemUpdateRows(payload.pcs);
      const running = (payload.pcs || []).some((pc) => ['running', 'unreachable'].includes(pc.state));
      if (!running && Date.now() > watchUntil) stop();
      if (!running && payload.same_version === false) setMessage('로봇 PC 버전이 서로 다릅니다 · 「모든 PC 업데이트」 로 맞추세요');
      else if (!running) setMessage('');
    } catch (error) {
      // 이 PC 가 업데이트로 재시작 중이면 잠깐 실패한다 · 계속 본다
      setMessage('이 PC 응답 없음 · 이 PC 도 업데이트 중이면 잠시 뒤 다시 연결됩니다');
    }
  }

  function start() {
    if (timer) return;
    timer = window.setInterval(refresh, POLL_MS);
  }

  function stop() {
    if (!timer) return;
    window.clearInterval(timer);
    timer = null;
  }

  async function updateAll() {
    if (busy) return;
    const confirmed = await showConfirm(
      '같은 망의 로봇 PC 전부를 최신 코드로 업데이트합니다 (코드 받기 → 빌드 → 서비스 재시작 · PC 마다 몇 분).\n\n'
      + '· 업데이트하는 동안 그 PC 는 재생이 멈추고 웹이 잠깐 끊깁니다 · 재생 중인 PC 는 거절합니다\n'
      + '· 이 PC 도 마지막에 업데이트되어 이 화면이 잠깐 끊겼다 돌아옵니다\n'
      + '· 스피커 PC 는 포함되지 않습니다(그 PC 터미널에서)\n\n'
      + '운영 시간 밖에 하세요. 계속할까요?',
      { title: '모든 PC 업데이트', confirmLabel: '업데이트', tone: 'warning' },
    );
    if (!confirmed) return;
    busy = true;
    if (el.systemUpdateAllButton) el.systemUpdateAllButton.disabled = true;
    setMessage('업데이트 요청 보내는 중');
    try {
      const payload = await requestSystemUpdateAll();
      if (el.systemUpdateRows) el.systemUpdateRows.innerHTML = systemUpdateRows(payload.pcs);
      setMessage(payload.message || '');
    } catch (error) {
      setMessage(`업데이트 요청 실패 · ${error?.message || error} · 이 PC 가 먼저 재시작됐으면 잠시 뒤 표가 다시 채워집니다`);
    } finally {
      busy = false;
      if (el.systemUpdateAllButton) el.systemUpdateAllButton.disabled = false;
      watchUntil = Date.now() + WATCH_AFTER_START_MS;
      start();
    }
  }

  function bindEvents() {
    el.systemUpdateAllButton?.addEventListener('click', updateAll);
    el.systemUpdateRefreshButton?.addEventListener('click', () => {
      watchUntil = Date.now() + POLL_MS * 3;
      refresh();
      start();
    });
  }

  return { bindEvents, refresh };
}
