/** UI v2 · 네트워크·시간 · Wi-Fi 입력 검사 · 그룹 설정 검사 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { groupProblem, wifiProblem } from '../static/v2/js/pages/network.js';

test('Wi-Fi · 고르기 · 비밀번호 8~63 · 열린 망은 비밀번호 없이 · 802.1X 거절 · 고정 IP 형식', () => {
  const base = { ssid: 'shop', password: 'password123', security: 'WPA2', useStatic: false };
  assert.equal(wifiProblem({ ...base, ssid: '' }), '연결할 Wi-Fi를 선택하세요');
  assert.equal(wifiProblem({ ...base, password: '' }), '비밀번호를 입력하세요');
  assert.equal(wifiProblem({ ...base, password: 'short' }), '비밀번호는 8~63자여야 합니다');
  assert.equal(wifiProblem({ ...base, security: '--', password: '' }), '');
  assert.match(wifiProblem({ ...base, security: 'WPA2 802.1X' }), /802\.1X/);
  assert.match(wifiProblem({ ...base, useStatic: true, address: '192.168.0.300x' }), /고정 IP/);
  assert.equal(wifiProblem({ ...base, useStatic: true, address: '192.168.0.24/24', gateway: '192.168.0.1' }), '');
  assert.equal(wifiProblem(base), '');
});

test('그룹 설정 · ID 모양 · Domain 0~101 · 마스터는 그룹 ID 필요', () => {
  const base = { is_master: false, group_id: 'stage-a', dds_domain_id: 21, display_name: '' };
  assert.equal(groupProblem(base), '');
  assert.match(groupProblem({ ...base, group_id: '-bad' }), /그룹 ID/);
  assert.match(groupProblem({ ...base, dds_domain_id: 102 }), /0~101/);
  assert.match(groupProblem({ ...base, is_master: true, group_id: '' }), /마스터/);
});
