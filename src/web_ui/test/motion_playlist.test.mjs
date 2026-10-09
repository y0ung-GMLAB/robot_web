// 재생 목록 · 수정 목록 35 (2026-10-06)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  MAX_PLAYLIST_LENGTH,
  playlistProgressText,
  playlistWithAdded,
  playlistWithMoved,
  playlistWithout,
  registeredPlaylist,
} from '../static/js/motion_playlist.js';

test('old mapping files read as a list of the registered file', () => {
  assert.deepEqual(registeredPlaylist({ motion_file_id: 'a.json' }), ['a.json']);
  assert.deepEqual(registeredPlaylist({ motion_file_id: '' }), []);
  assert.deepEqual(registeredPlaylist({}), []);
  assert.deepEqual(
    registeredPlaylist({ motion_file_id: 'a.json', motion_playlist: ['a.json', 'b.json'] }),
    ['a.json', 'b.json'],
  );
});

test('adding appends · duplicates are allowed · the cap holds', () => {
  assert.deepEqual(playlistWithAdded(['a.json'], 'a.json'), ['a.json', 'a.json']);
  assert.deepEqual(playlistWithAdded([], ''), []);
  const full = Array(MAX_PLAYLIST_LENGTH).fill('a.json');
  assert.equal(playlistWithAdded(full, 'b.json').length, MAX_PLAYLIST_LENGTH);
});

test('moving swaps neighbours and stops at the ends', () => {
  const list = ['a.json', 'b.json', 'c.json'];
  assert.deepEqual(playlistWithMoved(list, 1, -1), ['b.json', 'a.json', 'c.json']);
  assert.deepEqual(playlistWithMoved(list, 1, 1), ['a.json', 'c.json', 'b.json']);
  assert.deepEqual(playlistWithMoved(list, 0, -1), list);
  assert.deepEqual(playlistWithMoved(list, 2, 1), list);
  assert.deepEqual(playlistWithout(list, 1), ['a.json', 'c.json']);
});

test('progress names the current and the next item and wraps to the first', () => {
  const status = {
    motion_playlist: ['a.json', 'b.json', 'c.json'],
    playlist_length: 3,
    playlist_index: 2,
  };
  assert.equal(playlistProgressText(status), '재생 목록 3/3 · c.json · 다음 a.json');
  assert.equal(playlistProgressText({ ...status, playlist_length: 0 }), '');
  assert.equal(playlistProgressText({}), '');
});

test('registration sends the whole list on the narrow path', () => {
  const source = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
  assert.match(source, /motion_playlist: playlist/);
  // 같이 보기는 목록 재생 중 지금 도는 애니를 따라간다
  assert.match(source, /playingId \|\| registeredMotionFileIdValue/);
});

test('group start carries the sync mode', () => {
  const source = readFileSync(new URL('../static/js/coordination.js', import.meta.url), 'utf8');
  assert.match(source, /sync_mode: String\(el\.coordinationSyncMode/);
  assert.match(source, /group_sync_mode: mode/);
});

test('수정 목록 59 · 재생 목록 칸은 0개 · 1개여도 보인다 · 1개의 빼기는 등록 해제', async () => {
  const { playlistPanelHtml } = await import('../static/js/motion_playlist.js');
  assert.match(playlistPanelHtml([]), /재생 목록 · 비어 있음/);
  const one = playlistPanelHtml(['a.json'], { fileOf: () => ({ filename: 'a_long_name.json', durationSec: 12.34 }) });
  assert.match(one, /재생 목록 · 1개/);
  assert.match(one, />등록 해제</);
  assert.match(one, /title="a_long_name\.json"/);
  assert.equal((one.match(/disabled/g) || []).length, 2);          // ↑ ↓ 꺼짐
  const two = playlistPanelHtml(['a.json', 'gone.json'], { fileOf: (id) => (id === 'a.json' ? { filename: 'a.json' } : null) });
  assert.match(two, /재생 목록 · 2개/);
  assert.match(two, /gone\.json · 파일 없음/);
  assert.doesNotMatch(two, />등록 해제</);
  const source = readFileSync(new URL('../static/js/motion_data.js', import.meta.url), 'utf8');
  assert.match(source, /if \(!next\.length\) \{\s*const confirmed = await showConfirm/);
});
