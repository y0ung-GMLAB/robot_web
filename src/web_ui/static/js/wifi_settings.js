/** Wi-Fi · 이 PC 의 연결 보기·바꾸기 · 수정 목록 81 (2026-10-08)
 *
 * 바꾸면 서버가 먼저 「60초 뒤 이전 연결로 되돌리기」 를 걸고 바꾼다 · 화면은 남은 초를 세며
 * 「유지」 / 「되돌리기」 를 보여 준다 · 원격으로 바꾸다 연결이 끊기면 아무것도 안 눌러도
 * 60초 뒤 이전 연결로 돌아온다(그 사이 이 화면은 응답 없음).
 */
import {
  confirmWifi, connectWifi, fetchWifiStatus, rollbackWifi, scanWifi,
} from './api.js';
import { escapeHtml } from './format.js';
import { showConfirm } from './ui_dialogs.js';

const PENDING_POLL_MS = 1000;

export function wifiStatusText(status) {
  if (!status || status.available === false) return status?.message || 'Wi-Fi 장치 없음';
  if (!status.ssid) return `연결 안 됨 (${status.device || '-'})`;
  const signal = Number.isFinite(Number(status.signal)) && status.signal !== null ? ` · 신호 ${status.signal}%` : '';
  return `${status.ssid}${signal}`;
}

export function wifiNetworkOptions(networks) {
  const list = Array.isArray(networks) ? networks : [];
  if (!list.length) return '<option value="">「주변 Wi-Fi 찾기」 를 누르세요</option>';
  return list.map((net) => {
    const lock = net.security && net.security !== '--' ? ' 🔒' : '';
    const used = net.in_use ? ' · 지금 연결' : '';
    return `<option value="${escapeHtml(net.ssid)}" data-security="${escapeHtml(net.security || '')}">${escapeHtml(net.ssid)} · ${Number(net.signal) || 0}%${lock}${used}</option>`;
  }).join('');
}

export function createWifiController({ el }) {
  let pendingTimer = null;
  let busy = false;

  function setMessage(text) {
    if (el.wifiMessage) el.wifiMessage.textContent = text || '';
  }

  function render(status) {
    if (!status) return;
    if (el.wifiCurrent) el.wifiCurrent.textContent = wifiStatusText(status);
    if (el.wifiAddress) el.wifiAddress.textContent = status.address || '-';
    if (el.wifiMethod) el.wifiMethod.textContent = status.method === 'manual' ? '고정' : (status.method === 'auto' ? '자동 (DHCP)' : '-');
    if (el.wifiPowersave) el.wifiPowersave.textContent = status.powersave || '-';
    const pending = status.pending;
    el.wifiPendingBox?.classList.toggle('hidden', !pending);
    if (pending && el.wifiPendingText) {
      el.wifiPendingText.textContent = `${pending.ssid} 로 바꿨습니다 · ${pending.seconds_left}초 안에 「유지」 를 누르지 않으면 이전 연결로 되돌립니다`;
    }
    if (pending) startPendingWatch(); else stopPendingWatch();
  }

  async function refresh() {
    try {
      render(await fetchWifiStatus());
    } catch (error) {
      setMessage(`Wi-Fi 상태를 못 읽었습니다 · ${error?.message || error}`);
    }
  }

  function startPendingWatch() {
    if (pendingTimer) return;
    pendingTimer = window.setInterval(refresh, PENDING_POLL_MS);
  }

  function stopPendingWatch() {
    if (!pendingTimer) return;
    window.clearInterval(pendingTimer);
    pendingTimer = null;
  }

  async function scan() {
    setMessage('주변 Wi-Fi 찾는 중 (몇 초)');
    try {
      const payload = await scanWifi();
      if (el.wifiNetworkSelect) el.wifiNetworkSelect.innerHTML = wifiNetworkOptions(payload.networks);
      setMessage(payload.message || '');
    } catch (error) {
      setMessage(`찾기 실패 · ${error?.message || error}`);
    }
  }

  function staticSettings() {
    if (!el.wifiStaticToggle?.checked) return null;
    return {
      address: String(el.wifiStaticAddress?.value || '').trim(),
      gateway: String(el.wifiStaticGateway?.value || '').trim(),
      dns: String(el.wifiStaticDns?.value || '').trim(),
    };
  }

  async function connect() {
    if (busy) return;
    const option = el.wifiNetworkSelect?.selectedOptions?.[0];
    const ssid = String(el.wifiSsidInput?.value || option?.value || '').trim();
    if (!ssid) {
      setMessage('Wi-Fi 를 고르거나 이름(SSID)을 넣으세요');
      return;
    }
    const security = el.wifiSsidInput?.value ? '' : String(option?.dataset?.security || '');
    const confirmed = await showConfirm(
      `이 PC 의 Wi-Fi 를 「${ssid}」 로 바꿉니다.\n\n`
      + '· 바꾸는 동안 이 PC 의 연동·원격 접속이 잠깐 끊길 수 있습니다\n'
      + '· 60초 안에 「유지」 를 누르지 않으면 이전 연결로 저절로 되돌립니다\n'
      + '  (원격에서 바꾸다 연결이 끊겨도 60초 뒤 원래대로 돌아옵니다)\n'
      + '· 이 PC 를 고정 IP 로 쓰려면 공유기 「DHCP 예약」 이 더 간단합니다\n\n계속할까요?',
      { title: 'Wi-Fi 바꾸기', confirmLabel: '바꾸기', tone: 'warning' },
    );
    if (!confirmed) return;
    busy = true;
    if (el.wifiConnectButton) el.wifiConnectButton.disabled = true;
    setMessage(`${ssid} 에 연결하는 중 (최대 45초)`);
    try {
      const payload = await connectWifi({
        ssid, password: String(el.wifiPasswordInput?.value || ''), static: staticSettings(), security,
      });
      setMessage(payload.message || '');
      if (el.wifiPasswordInput) el.wifiPasswordInput.value = '';
      render(payload.success ? payload : await fetchWifiStatus());
    } catch (error) {
      setMessage('응답 없음 · 연결이 바뀌어 이 화면이 끊겼을 수 있습니다 · 60초 안에 새 주소로 들어가 「유지」 를 누르거나, 그대로 두면 원래 연결로 돌아옵니다');
    } finally {
      busy = false;
      if (el.wifiConnectButton) el.wifiConnectButton.disabled = false;
    }
  }

  async function keep() {
    const payload = await confirmWifi();
    setMessage(payload.message || '');
    render(payload);
  }

  async function revert() {
    const payload = await rollbackWifi();
    setMessage(payload.message || '');
    render(payload);
  }

  function bindEvents() {
    el.wifiScanButton?.addEventListener('click', scan);
    el.wifiConnectButton?.addEventListener('click', connect);
    el.wifiKeepButton?.addEventListener('click', keep);
    el.wifiRevertButton?.addEventListener('click', revert);
    el.wifiStaticToggle?.addEventListener('change', () => {
      el.wifiStaticFields?.classList.toggle('hidden', !el.wifiStaticToggle.checked);
    });
    el.wifiRefreshButton?.addEventListener('click', refresh);
  }

  return { bindEvents, refresh };
}
