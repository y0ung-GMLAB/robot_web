import assert from 'node:assert/strict';
import test from 'node:test';
import { networkPcRows } from '../static/js/network_pcs.js';

const local = {
  pc_id: 'floating1', display_name: 'floating1', role: 'robot', address: '192.168.0.11',
  web_url: 'http://192.168.0.11:8000', group_id: 'stage-a', joined: true, is_master: true,
  git_hash: 'abc1234', protocol_version: 5, is_local: true, online: true, age_sec: 0,
};

test('같은 망 PC · IP 를 글자로 · 다른 PC 는 열기 링크 · 스피커는 스피커 화면', () => {
  const html = networkPcRows([
    local,
    { ...local, pc_id: 'floating2', display_name: 'floating2', address: '192.168.0.12',
      web_url: 'http://192.168.0.12:8000', is_master: false, is_local: false, joined: false },
    { pc_id: 'speaker', display_name: 'speaker', role: 'speaker', address: '192.168.0.20',
      web_url: 'http://192.168.0.20:8100', group_id: 'stage-a', git_hash: 'abc1234',
      is_local: false, online: false, age_sec: 9.4 },
  ]);
  assert.match(html, /192\.168\.0\.11/);
  assert.match(html, /로봇 · 마스터/);
  assert.match(html, /지금 이 화면/);
  assert.match(html, /href="http:\/\/192\.168\.0\.12:8000"[^>]*target="_blank"/);
  assert.match(html, /stage-a · 나감/);
  assert.match(html, /스피커 화면 열기/);
  assert.match(html, /끊김 · 9초 전/);
});

test('주소가 아닌 웹 주소는 링크로 만들지 않는다 · 이름은 이스케이프', () => {
  const html = networkPcRows([
    local,
    { ...local, pc_id: 'x', display_name: '<b>x</b>', web_url: 'javascript:alert(1)', is_local: false },
  ]);
  assert.doesNotMatch(html, /javascript:/);
  assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
});

test('버전이 다르면 빨갛게 · 이 PC 혼자면 기다리는 이유를 적는다', () => {
  const html = networkPcRows([
    local,
    { ...local, pc_id: 'old', display_name: 'old', is_local: false, git_hash: 'ffff000',
      version_differs: true, protocol_mismatch: true, protocol_version: 4 },
  ]);
  assert.match(html, /이 PC 와 다름 · 약속 번호 4 \(이 PC 5\)/);
  assert.match(networkPcRows([local]), /같은 DDS Domain ID/);
});
