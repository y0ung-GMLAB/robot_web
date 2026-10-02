/** 폴더 드롭 → 화면이 만든 zip · 서버(zipfile)가 그대로 읽어야 한다
 *
 * 로봇 팩 폴더를 끌어다 놓으면 zip_store 가 무압축 zip 으로 묶어 기존
 * 업로드 길로 보낸다 · 형식이 하나라도 틀리면 서버가 「zip 파일이 아님」으로
 * 거부한다 · 여기서는 머리말 구조와 CRC 를 본다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { buildStoredZip, crc32 } from '../static/js/zip_store.js';

const encoder = new TextEncoder();

test('crc32 는 표준값을 낸다', () => {
  assert.equal(crc32(encoder.encode('hello')), 0x3610a686);
  assert.equal(crc32(new Uint8Array()), 0);
});

test('항목마다 머리말 · 끝에 목차와 끝 표시', () => {
  const zip = buildStoredZip([
    { path: 'pack/robot.yaml', data: encoder.encode('axes: []\n') },
    { path: 'pack/한글.txt', data: encoder.encode('가') },
  ]);
  const view = new DataView(zip.buffer);
  assert.equal(view.getUint32(0, true), 0x04034b50);
  assert.equal(view.getUint16(6, true) & 0x0800, 0x0800, 'UTF-8 이름 표시');
  const end = zip.length - 22;
  assert.equal(view.getUint32(end, true), 0x06054b50);
  assert.equal(view.getUint16(end + 10, true), 2);
  const centralStart = view.getUint32(end + 16, true);
  assert.equal(view.getUint32(centralStart, true), 0x02014b50);
  assert.equal(view.getUint32(centralStart + 16, true), crc32(encoder.encode('axes: []\n')));
});

test('폴더 드롭은 숨김 파일을 빼고 zip 으로 묶어 같은 길로 보낸다', () => {
  const source = readFileSync(new URL('../static/js/robot_pack.js', import.meta.url), 'utf8');
  assert.match(source, /webkitGetAsEntry/);
  assert.match(source, /buildStoredZip/);
  assert.match(source, /startsWith\('\.'\)/);
  assert.doesNotMatch(source, /FormData|multipart/);
});
