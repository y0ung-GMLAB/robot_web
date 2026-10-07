/** 재생 목록 · 수정 목록 35 (2026-10-06)
 *
 * 매핑 파일의 `motion_playlist: [A, B, C]` · 없으면 옛 파일처럼
 * `motion_file_id` 하나가 목록이다. A → B → C → A … 끝없이 · 사이마다 다음
 * 애니의 첫 프레임으로 초기 위치 이동 · 재시작은 늘 1번부터.
 *
 * 순서만 정한다 · 같은 파일을 두 번 넣어도 된다 (그만큼 두 번 재생).
 * 여기는 값 계산만 · 화면과 저장은 `motion_data.js`.
 */

import { displayText, formatNumber } from './format.js';

/** 서버와 같은 상한 (`registered_motion_file.MAX_PLAYLIST_LENGTH`) */
export const MAX_PLAYLIST_LENGTH = 50;

export function registeredPlaylist(mapping = {}) {
  const raw = Array.isArray(mapping?.motion_playlist) ? mapping.motion_playlist : [];
  const items = raw.map((item) => String(item || '').trim()).filter(Boolean);
  if (items.length) return items;
  const single = String(mapping?.motion_file_id || '').trim();
  return single ? [single] : [];
}

export function playlistWithAdded(list, fileId) {
  const id = String(fileId || '').trim();
  if (!id || list.length >= MAX_PLAYLIST_LENGTH) return [...list];
  return [...list, id];
}

/** `index` 칸을 `delta`(−1 위 · +1 아래)만큼 옮긴다 · 끝을 넘으면 그대로 */
export function playlistWithMoved(list, index, delta) {
  const target = index + delta;
  if (index < 0 || index >= list.length || target < 0 || target >= list.length) {
    return [...list];
  }
  const next = [...list];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function playlistWithout(list, index) {
  return list.filter((_item, position) => position !== index);
}

/** 재생 중 「재생 목록 2/3 · B · 다음 C」 · 목록 재생이 아니면 빈 글자 */
export function playlistProgressText(status = {}) {
  const list = Array.isArray(status?.motion_playlist) ? status.motion_playlist : [];
  const length = Number(status?.playlist_length) || 0;
  if (length < 2 || list.length !== length) return '';
  const index = Math.min(Math.max(Number(status?.playlist_index) || 0, 0), length - 1);
  return `재생 목록 ${index + 1}/${length} · ${list[index]} · 다음 ${list[(index + 1) % length]}`;
}


/** 재생 목록 칸 · 0개 · 1개여도 늘 보인다 · 수정 목록 59
 *
 * 전에는 2개 이상일 때만 보여서, 하나를 빼 1개가 되면 칸이 통째로 사라져 헷갈렸다 ·
 * 저장 형식은 그대로(1개면 옛 `motion_file_id`) · 화면만.
 * `fileOf(id)` → `{ filename, durationSec }` 또는 null(파일 없음).
 */
export function playlistPanelHtml(list, { fileOf = () => null, busy = false } = {}) {
  if (!list.length) {
    return (
      '<div class="motion-playlist-head"><strong>재생 목록 · 비어 있음</strong>'
      + '<span>애니메이션 파일을 고르고 「재생 등록」 을 누르세요</span></div>'
    );
  }
  const rows = list.map((id, index) => {
    const file = fileOf(id);
    const duration = Number(file?.durationSec);
    const missing = !file;
    const only = list.length === 1;
    return (
      `<li class="motion-playlist-row${missing ? ' missing' : ''}">`
      + `<span class="motion-playlist-index">${index + 1}</span>`
      + `<span class="motion-playlist-name" title="${displayText(file?.filename || id)}">${displayText(file?.filename || id)}${missing ? ' · 파일 없음' : ''}</span>`
      + `<span class="motion-playlist-time">${Number.isFinite(duration) ? `${formatNumber(duration, 1)} s` : '-'}</span>`
      + `<button type="button" data-playlist-action="up" data-playlist-index="${index}" ${busy || index === 0 ? 'disabled' : ''} title="한 칸 위로">↑</button>`
      + `<button type="button" data-playlist-action="down" data-playlist-index="${index}" ${busy || index === list.length - 1 ? 'disabled' : ''} title="한 칸 아래로">↓</button>`
      + `<button type="button" class="danger" data-playlist-action="remove" data-playlist-index="${index}" ${busy ? 'disabled' : ''} title="${only ? '재생 등록을 해제합니다 · 파일은 지우지 않습니다' : '목록에서 뺍니다 · 파일은 지우지 않습니다'}">${only ? '등록 해제' : '빼기'}</button>`
      + '</li>'
    );
  }).join('');
  const note = list.length === 1
    ? '이 애니메이션만 반복 · 다른 파일을 「재생 등록」 하면 뒤에 붙어 차례로 돕니다'
    : '차례로 돌고 끝나면 1번부터 · 사이마다 다음 애니의 초기 위치로 이동';
  return (
    `<div class="motion-playlist-head"><strong>재생 목록 · ${list.length}개</strong>`
    + `<span>${note}</span></div>`
    + `<ol class="motion-playlist-rows">${rows}</ol>`
  );
}
