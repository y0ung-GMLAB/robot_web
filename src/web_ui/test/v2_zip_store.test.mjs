/** UI v2 · 폴더 → zip · CRC · 빼는 파일 · 구조 (로봇 팩 올리기 · 설계안 2026-10-09)
 * 브라우저에서 만든 zip 을 Python zipfile 로 열어 본 것은 화면 시험에서 따로 확인함(한글 이름 포함)
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { buildZip, crc32, keepPath } from '../static/v2/js/zip_store.js';

test('CRC32 · 알려진 값', () => {
  assert.equal(crc32(new TextEncoder().encode('123456789')), 0xCBF43926);
  assert.equal(crc32(new Uint8Array()), 0);
});

test('숨김 · __MACOSX 는 뺀다', () => {
  assert.equal(keepPath('pack/model.xml'), true);
  assert.equal(keepPath('pack/.DS_Store'), false);
  assert.equal(keepPath('__MACOSX/pack/x'), false);
  assert.equal(keepPath('pack/.git/config'), false);
  assert.equal(keepPath(''), false);
});

test('zip 구조 · 첫 서명 · 끝 레코드의 항목 수 · UTF-8 이름 플래그', () => {
  const enc = new TextEncoder();
  const zip = buildZip([{ path: 'p/a.txt', bytes: enc.encode('a') }, { path: 'p/한글.txt', bytes: enc.encode('가') }]);
  const view = new DataView(zip.buffer);
  assert.equal(view.getUint32(0, true), 0x04034B50);
  assert.equal(view.getUint16(6, true), 0x0800);
  const end = zip.length - 22;
  assert.equal(view.getUint32(end, true), 0x06054B50);
  assert.equal(view.getUint16(end + 10, true), 2);
});
