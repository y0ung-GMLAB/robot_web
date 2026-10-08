/** Wi-Fi 화면 · 시스템 정보 · 수정 목록 81 (2026-10-08) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { indexHtml } from '../tools/index_html.mjs';
import { wifiNetworkOptions, wifiStatusText } from '../static/js/wifi_settings.js';

const main = readFileSync(new URL('../static/js/main.js', import.meta.url), 'utf8');
const dom = readFileSync(new URL('../static/js/dom.js', import.meta.url), 'utf8');
const controller = readFileSync(new URL('../static/js/wifi_settings.js', import.meta.url), 'utf8');

test('the Wi-Fi card lives in system information with keep/revert for the 60 s rollback', () => {
  assert.match(indexHtml, /<section class="project-system-manager wifi-card" aria-label="Wi-Fi">/);
  for (const id of ['wifiNetworkSelect', 'wifiPasswordInput', 'wifiConnectButton', 'wifiKeepButton', 'wifiRevertButton', 'wifiStaticToggle']) {
    assert.match(indexHtml, new RegExp(`id="${id}"`), id);
    assert.ok(dom.includes(`${id}: document.getElementById('${id}')`), id);
  }
  assert.match(indexHtml, /<input id="wifiPasswordInput" type="password" autocomplete="new-password">/);
  assert.match(main, /const wifi = createWifiController\(\{ el \}\);/);
  // 비밀번호는 보낸 뒤 칸에서 지운다
  assert.match(controller, /el\.wifiPasswordInput\.value = '';/);
  // 연결 방식(보안)을 서버에 함께 보낸다 · WPA3 판단용
  assert.match(controller, /ssid, password: String\(el\.wifiPasswordInput\?\.value \|\| ''\), static: staticSettings\(\), security,/);
});

test('status text and network options', () => {
  assert.equal(wifiStatusText({ available: false, message: '장치 없음' }), '장치 없음');
  assert.equal(wifiStatusText({ available: true, device: 'wlp2s0', ssid: '' }), '연결 안 됨 (wlp2s0)');
  assert.equal(wifiStatusText({ available: true, ssid: 'shop', signal: 72 }), 'shop · 신호 72%');
  const html = wifiNetworkOptions([
    { ssid: 'shop', signal: 72, security: 'WPA2', in_use: true },
    { ssid: 'guest', signal: 40, security: '--' },
  ]);
  assert.match(html, /value="shop" data-security="WPA2">shop · 72% 🔒 · 지금 연결/);
  assert.match(html, /value="guest" data-security="--">guest · 40%<\/option>/);
  assert.match(wifiNetworkOptions([]), /주변 Wi-Fi 찾기/);
});
