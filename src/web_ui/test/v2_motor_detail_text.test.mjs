/** UI v2 · 모터 상세 칸 글 · Alias 「마지막 검색 때 읽은 값」 · 내부 ID 는 원본 안 (사용자 2026-10-13) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/v2/js/pages/motors.js', import.meta.url), 'utf8');

test('Alias · 「지금 N」 이 아니라 「마지막 검색 때 읽은 값 N」', () => {
  assert.match(source, /`마지막 검색 때 읽은 값 \$\{motor\.identity\?\.ethercat_alias/);
  assert.doesNotMatch(source, /text: `지금 \$\{motor\.identity/);
});

test('내부 ID 는 카드 머리에 없고 「원본」 안에', () => {
  const head = source.slice(source.indexOf("h('div', { class: 'card-head' }, h('h2', { text: `${row.axis}번 · ${row.name"));
  assert.doesNotMatch(head.split('\n')[0], /row\.id/);
  const raw = source.slice(source.indexOf("'원본 (드라이브 정보)'"));
  assert.match(raw.split('\n').slice(0, 3).join('\n'), /내부 ID · .*text: row\.id/);
});

test('「운영 시간이 끝나면 서보 끄기」 · 안 적었으면 켬으로 보인다 · 서버 기본과 같게', () => {
  assert.match(source, /checked: motor\.config\?\.schedule_end_servo_off !== false/);
});
