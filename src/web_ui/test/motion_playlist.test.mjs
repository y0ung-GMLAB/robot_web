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
