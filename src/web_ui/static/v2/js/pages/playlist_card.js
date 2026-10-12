/** UI v2 · 이 PC 재생 목록 칸 · 공연 · 애니메이션 두 화면이 같이 쓴다 (설계안 2026-10-09)
 *
 * 차례로 돌고 끝나면 1번부터 · 넣기 · ↑↓ · 빼기 · 재생 중엔 잠김(서버도 거절 · change_blocker).
 * 값은 `state.play`(loadPlay 가 받아 온 매핑 · 파일 목록)에서 읽는다.
 */
import { h } from '../dom.js';
import {
  PLAYLIST_MAX, fileInfo, formatDuration, isRunning, playlistAdd, playlistMove, playlistRemove, registeredPlaylist, runStatus,
} from '../play_model.js';
import * as act from '../actions.js';

const ui = { busy: false, addPick: '' };

/**
 * link · 머리 오른쪽 바로가기 [주소, 글]
 * adding · 아래 「넣기」 줄 (애니메이션 화면은 상세에 넣기 버튼이 있어 끈다)
 * onPick · 이름을 누르면 (애니메이션 화면 · 그 파일 상세 열기)
 * reload · 저장 뒤 다시 받기
 */
export function playlistCard(state, changed, { link = null, adding = true, onPick = null, selected = '', reload }) {
  const play = state.play || {};
  const status = runStatus(state.snap);
  const running = isRunning(status);
  const list = registeredPlaylist(play.mapping);
  const files = new Map((play.files || []).map((file) => [String(file.id || file.filename), fileInfo(file)]));
  const locked = running || ui.busy || !play.mappingId;
  const playingIndex = running ? (Number.isInteger(Number(status.playlist_index)) ? Number(status.playlist_index) : 0) : -1;
  const save = async (next) => {
    if (ui.busy) return;
    ui.busy = true;
    changed();
    try {
      if (await act.savePlaylist(play.mappingId, next)) await reload(state, changed);
    } finally {
      ui.busy = false;
      changed();
    }
  };

  const choices = [...files.values()].filter((file) => file.check !== 'bad');
  if (!choices.some((file) => file.id === ui.addPick)) ui.addPick = choices[0]?.id || '';
  const total = list.reduce((sum, id) => sum + (files.get(id)?.duration || 0), 0);

  return h('section', { class: 'card', 'aria-label': '재생 목록' },
    h('div', { class: 'card-head' },
      h('h2', { text: `재생 목록 · ${list.length}` }),
      link ? h('a', { href: link[0], text: link[1] }) : null),
    h('p', { class: 'muted small', text: `전체 ${formatDuration(total || null)} · 순서대로 재생하고, 끝나면 1번부터 다시 재생합니다. 애니메이션 사이마다 다음 애니메이션의 첫 자세로 천천히 이동합니다.` }),
    play.error ? h('p', { class: 'tone-text-bad', text: play.error }) : null,
    list.length
      ? h('ol', { class: 'playlist' }, list.map((id, index) => {
        const info = files.get(id) || { name: id, duration: null, check: 'unknown', checkText: '목록에 없는 파일' };
        const name = onPick
          ? h('button', { class: `link-button grow name${id === selected ? ' picked' : ''}`, type: 'button', title: info.name, onclick: () => onPick(id) }, info.name)
          : h('span', { class: 'grow name', title: info.name, text: info.name });
        return h('li', { class: `playlist-row${index === playingIndex ? ' playing' : ''}` },
          h('span', { class: 'mono muted num', text: String(index + 1) }),
          name,
          h('span', { class: 'mono muted', text: formatDuration(info.duration) }),
          h('span', { class: `small tone-text-${index === playingIndex ? 'ok' : info.check === 'bad' ? 'bad' : info.check === 'ok' ? 'ok' : 'warn'}`,
            text: index === playingIndex ? '지금' : info.checkText }),
          h('span', { class: 'row-actions' },
            h('button', { class: 'btn btn-mini', type: 'button', disabled: locked || index === 0, 'aria-label': `${info.name} 위로`, onclick: () => save(playlistMove(list, index, -1)) }, '↑'),
            h('button', { class: 'btn btn-mini', type: 'button', disabled: locked || index === list.length - 1, 'aria-label': `${info.name} 아래로`, onclick: () => save(playlistMove(list, index, 1)) }, '↓'),
            h('button', { class: 'btn btn-mini', type: 'button', disabled: locked, onclick: () => save(playlistRemove(list, index)) }, '삭제')));
      }))
      : h('p', { class: 'muted', text: adding ? '재생 목록이 비어 있습니다. 아래에서 애니메이션을 추가하세요.' : '재생 목록이 비어 있습니다. 애니메이션을 선택하고 「재생 목록에 추가」를 누르세요.' }),
    adding ? h('div', { class: 'row add-row' },
      h('select', { class: 'select grow', 'aria-label': '추가할 애니메이션', disabled: locked || !choices.length,
        onchange: (event) => { ui.addPick = event.target.value; } },
      choices.map((file) => h('option', { value: file.id, selected: file.id === ui.addPick }, `${file.name} · ${formatDuration(file.duration)}`))),
      h('button', { class: 'btn', type: 'button', disabled: locked || !ui.addPick || list.length >= PLAYLIST_MAX,
        onclick: () => save(playlistAdd(list, ui.addPick)) }, '추가')) : null,
    running ? h('p', { class: 'muted small', text: '재생 중에는 목록을 바꿀 수 없습니다. 재생을 멈춘 뒤 바꾸세요.' }) : null);
}
