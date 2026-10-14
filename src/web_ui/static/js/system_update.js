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
  idle: ['대기 상태', ''],
  running: ['업데이트 중', 'coordination-state-warn'],
  done: ['완료', 'coordination-state-ok'],
  failed: ['실패', 'coordination-state-bad'],
  unreachable: ['응답 없음 (재시작 중일 수 있음)', 'coordination-state-warn'],
  offline: ['연결 안 됨', 'coordination-state-bad'],
  manual: ['터미널에서 직접 업데이트', ''],
};

export function systemUpdateRows(pcs) {
  const list = Array.isArray(pcs) ? pcs : [];
  if (!list.length) return '<tr><td colspan="4" class="empty">같은 네트워크의 PC를 찾는 중</td></tr>';
  return list.map((pc) => {
    const [label, cls] = STATE_TEXT[pc.state] || [String(pc.state || '-'), ''];
    const name = pc.display_name || pc.pc_id || '-';
    const local = pc.is_local ? ' <small>(현재 접속)</small>' : '';
    const tail = Array.isArray(pc.tail) && pc.tail.length ? pc.tail[pc.tail.length - 1] : '';
    const note = pc.message || tail || '';
    // 「옛 → 새」 는 끝까지 된 때만 · 실패면 지금 버전만 (82 · 그 사이 생긴 커밋을 결과처럼 보였다)
    const after = pc.after_hash || pc.git_hash || '';   // 옛 버전 PC 는 after_hash 가 없다
    const version = pc.state === 'done' && pc.before_hash && after && pc.before_hash !== after
      ? `${pc.before_hash} → ${after}`
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
      if (!running && payload.same_version === false) setMessage('로봇 PC의 버전이 서로 다릅니다. 「모든 PC 업데이트」로 맞추세요.');
      else if (!running) setMessage('');
    } catch (error) {
      // 이 PC 가 업데이트로 재시작 중이면 잠깐 실패한다 · 계속 본다
      setMessage('응답이 없습니다. 현재 접속한 PC도 업데이트 중이면 잠시 뒤 다시 연결됩니다.');
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
      '같은 네트워크의 로봇 PC를 모두 최신 코드로 업데이트합니다(코드 받기 → 빌드 → 서비스 재시작, PC마다 몇 분 걸립니다).\n\n'
      + '· 업데이트하는 동안 해당 PC는 재생이 멈추고 웹 화면이 잠시 끊깁니다. 재생 중인 PC는 업데이트하지 않습니다.\n'
      + '· 현재 접속한 PC도 마지막에 업데이트되므로 이 화면이 잠시 끊겼다가 다시 연결됩니다.\n'
      + '· 스피커 PC도 함께 업데이트합니다. 이전 스피커 앱이면 해당 PC의 터미널에서 직접 업데이트하세요.\n\n'
      + '운영시간 외에 실행하세요. 계속할까요?',
      { title: '모든 PC 업데이트', confirmLabel: '업데이트', tone: 'warning' },
    );
    if (!confirmed) return;
    busy = true;
    if (el.systemUpdateAllButton) el.systemUpdateAllButton.disabled = true;
    setMessage('업데이트 요청을 보내는 중');
    try {
      const payload = await requestSystemUpdateAll();
      if (el.systemUpdateRows) el.systemUpdateRows.innerHTML = systemUpdateRows(payload.pcs);
      setMessage(payload.message || '');
    } catch (error) {
      setMessage(`업데이트 요청 실패 · ${error?.message || error} · 현재 접속한 PC가 먼저 재시작됐다면 잠시 뒤 표가 다시 채워집니다`);
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
