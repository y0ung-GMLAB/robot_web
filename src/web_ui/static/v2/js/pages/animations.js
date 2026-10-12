/** UI v2 · 애니메이션 · 「올리고 · 검사 결과 보고 · 재생 목록에 넣는다」 (설계안 2026-10-09)
 *
 * 올리면 서버가 형식을 검사하고, 3D 계산(MuJoCo)이 설정돼 있으면 바로 계산을 건다(기존 화면과 같음).
 * 범위 넘음은 이 PC 조인트 매핑과 비교 · 재생은 범위로 잘라서 돈다.
 */
import { h, dot } from '../dom.js';
import { checkState, factLine, fileRows, mappedCount, mujocoState, rangeIssues, seriesGeometry } from '../anim_model.js';
import { PLAYLIST_MAX, isRunning, playlistAdd, registeredPlaylist, runStatus, signedDeg } from '../play_model.js';
import { loadPlay } from './play.js';
import { api } from '../net.js';
import { toast } from '../dialog.js';
import * as act from '../actions.js';
import { playlistCard } from './playlist_card.js';

const ui = { selected: '', detail: null, detailFor: '', busy: '', upload: '' };
let current = { state: null, changed: () => {} };

export async function loadAnimations(state, changed) {
  current = { state, changed };
  await loadPlay(state, changed);
  const files = state.play?.files || [];
  if (ui.selected && !files.some((file) => String(file.id) === ui.selected)) ui.selected = '';
  if (!ui.selected && files.length) ui.selected = String(fileRows(files)[0].id);
  await loadDetail(state, changed);
}

async function loadDetail(state, changed, force = false) {
  if (!ui.selected || (!force && ui.detailFor === ui.selected && ui.detail)) return;
  const id = ui.selected;
  try {
    const data = await api('GET', `/api/motion-files/${encodeURIComponent(id)}`, { timeoutMs: 30000 });
    if (ui.selected !== id) return;
    ui.detail = data?.file || null;
    ui.detailFor = id;
  } catch (error) {
    ui.detail = { error: error.message || String(error) };
    ui.detailFor = id;
  }
  changed();
}

/* ---------- 올리기 ---------- */

async function upload(fileList) {
  const { state, changed } = current;
  const picked = [...(fileList || [])];
  if (!picked.length || ui.busy) return;
  const wrong = picked.find((file) => !/\.json$/i.test(file.name || ''));
  if (wrong) {
    toast(`애니메이션은 .json 파일만 업로드할 수 있습니다: ${wrong.name}`, 'warn');
    return;
  }
  ui.busy = 'upload';
  const done = [];
  try {
    if (!state.play?.projectId) await loadPlay(state, changed);
    const projectId = state.play?.projectId;
    if (!projectId) throw new Error('선택된 프로젝트가 없습니다');
    for (const [index, file] of picked.entries()) {
      ui.upload = `업로드 중 ${index + 1}/${picked.length} · ${file.name} (${(file.size / 1e6).toFixed(1)} MB) · 서버에서 검사하는 중`;
      changed();
      try {
        await act.uploadAnimation(projectId, file.name, await file.text());
        done.push(file.name);
      } catch (error) {
        // 하나 실패하면 멈춘다 · 이유(이름 겹침 · 매핑 없음 · 형식)가 다음 성공에 덮이지 않게
        toast(`${file.name} 업로드 실패 · ${error.message || error}${done.length ? ` · 앞의 ${done.length}개는 업로드됨` : ''}`, 'bad');
        break;
      }
    }
    if (done.length) {
      ui.upload = `${done.length}개 업로드 완료 · 목록을 새로 고치는 중`;
      changed();
      await loadPlay(state, changed);
      const toCompute = (state.play?.files || []).filter((file) => done.includes(String(file.id)) && mujocoState(file).state === 'missing');
      for (const file of toCompute) {
        await api('POST', `/api/motion-files/${encodeURIComponent(file.id)}/preview-precompute`).catch(() => null);
      }
      toast(`${done.length}개 업로드 완료${toCompute.length ? ` · 3D 계산 ${toCompute.length}개 시작` : ''}`, 'ok');
      ui.selected = done[done.length - 1];
      ui.detail = null;
      await loadAnimations(state, changed);
    }
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = '';
    ui.upload = '';
    changed();
  }
}

/** 화면 어디에 놓아도 · 애니메이션 화면일 때만 */
function onDrag(event) {
  if (!location.hash.startsWith('#/animations')) return;
  if (![...(event.dataTransfer?.types || [])].includes('Files')) return;
  event.preventDefault();
  document.body.classList.toggle('drop-active', event.type !== 'dragleave' || event.relatedTarget !== null);
  if (event.type === 'drop') {
    document.body.classList.remove('drop-active');
    upload(event.dataTransfer.files);
  }
}
['dragenter', 'dragover', 'dragleave', 'drop'].forEach((kind) => document.addEventListener(kind, onDrag));

/* ---------- 목록 ---------- */

function listCard(state, changed) {
  const play = state.play || {};
  const playlist = registeredPlaylist(play.mapping);
  const rows = fileRows(play.files, { playlist, mapping: play.mapping });
  const picker = h('input', { type: 'file', accept: '.json,application/json', multiple: true, hidden: true,
    onchange: (event) => upload(event.target.files) });
  return h('section', { class: 'card', 'aria-label': '애니메이션 목록' },
    h('div', { class: 'card-head' },
      h('h2', { text: `업로드된 애니메이션 · ${rows.length}개` }),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: Boolean(ui.busy), onclick: () => picker.click() }, '업로드'),
      picker),
    h('p', { class: 'muted small', text: '여기에 .json 파일을 끌어다 놓아도 업로드됩니다. 업로드하면 검사 후 3D 계산을 시작합니다.' }),
    ui.upload ? h('div', { class: 'busy-line', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), ui.upload) : null,
    play.error ? h('p', { class: 'tone-text-bad', text: play.error }) : null,
    rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table files-table' },
      h('thead', {}, h('tr', {}, ['이름', '길이', '검사', '3D 계산', '재생 목록', '업로드 날짜'].map((text) => h('th', { scope: 'col', text })))),
      h('tbody', {}, rows.map((row) => h('tr', { class: row.id === ui.selected ? 'selected' : '' },
        h('td', { class: 'name-cell' }, h('button', { class: 'link-button', type: 'button', title: row.name, 'aria-pressed': String(row.id === ui.selected),
          onclick: () => { ui.selected = row.id; ui.detail = null; changed(); loadDetail(state, changed); } }, row.name)),
        h('td', { class: 'mono', text: row.duration }),
        h('td', {}, h('span', { class: `chip chip-${row.check.tone}`, title: row.check.text, text: row.check.text })),
        h('td', {}, h('span', { class: `chip chip-${row.mujoco.tone}`, title: row.mujoco.message, text: row.mujoco.text })),
        h('td', { class: 'mono muted', text: row.slots }),
        h('td', { class: 'mono muted', text: row.date }))))))
      : h('p', { class: 'muted', text: ui.busy ? '' : '아직 애니메이션이 없습니다. Blender에서 내보낸 .json 파일을 업로드하세요.' }));
}

/* ---------- 상세 ---------- */

function chart(series, mappingRow) {
  const lower = mappingRow ? Number(mappingRow.motion_lower_rad) * 180 / Math.PI : null;
  const upper = mappingRow ? Number(mappingRow.motion_upper_rad) * 180 / Math.PI : null;
  const geo = seriesGeometry(series.points, { width: 300, height: 80, lower, upper });
  if (!geo) return null;
  const over = mappingRow && (geo.min < lower - 1e-3 || geo.max > upper + 1e-3);
  return h('figure', { class: `chart${over ? ' over' : ''}` },
    h('figcaption', {},
      h('span', { class: 'mono', text: series.motion_id }),
      h('span', { class: 'mono muted small', text: `${signedDeg(geo.min)} ~ ${signedDeg(geo.max)}°` }),
      mappingRow ? null : h('span', { class: 'muted small', text: '매핑에 없음' })),
    svg('svg', { viewBox: '0 0 300 80', preserveAspectRatio: 'none', role: 'img', 'aria-label': `${series.motion_id} 그래프` },
      geo.upperY !== null ? svg('line', { x1: 0, x2: 300, y1: geo.upperY, y2: geo.upperY, class: 'limit' }) : null,
      geo.lowerY !== null ? svg('line', { x1: 0, x2: 300, y1: geo.lowerY, y2: geo.lowerY, class: 'limit' }) : null,
      svg('path', { d: geo.line, class: 'trace' })));
}

function svg(tag, attrs, ...children) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value));
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

function detailCard(state, changed, navigate) {
  const play = state.play || {};
  const file = (play.files || []).find((item) => String(item.id) === ui.selected);
  if (!file) return null;
  const detail = ui.detailFor === ui.selected ? ui.detail : null;
  const analysis = detail?.analysis || file.analysis || {};
  const playlist = registeredPlaylist(play.mapping);
  const inPlaylist = playlist.includes(ui.selected);
  const running = isRunning(runStatus(state.snap));
  const issues = rangeIssues(analysis, play.mapping);
  const counts = mappedCount(analysis, play.mapping);
  const check = checkState(file, play.mapping);
  const mujoco = mujocoState(file);
  const rows = new Map((play.mapping?.mappings || []).map((row) => [String(row.motion_id), row]));
  const series = analysis.graph_series || detail?.graph_series || [];
  const downloadUrl = play.projectId
    ? `/api/projects/${encodeURIComponent(play.projectId)}/files/motions/${encodeURIComponent(ui.selected)}/download` : '';
  const addToPlaylist = async () => {
    if (await act.savePlaylist(play.mappingId, playlistAdd(playlist, ui.selected))) {
      await loadPlay(state, changed);
      toast('재생 목록 끝에 추가했습니다. 순서는 재생 화면에서 바꿀 수 있습니다.', 'ok');
    }
  };
  return h('section', { class: 'card detail-card', 'aria-label': '애니메이션 상세' },
    h('div', { class: 'card-head' }, h('h2', { class: 'detail-name', text: ui.selected })),
    h('p', { class: 'muted' },
      factLine(analysis),
      ` · 조인트 ${counts.total}개 · 매핑에 있음 ${counts.mapped}개`,
      analysis.value_unit ? ` · 단위 ${analysis.value_unit}` : ''),
    check.tone === 'bad' ? h('div', { class: 'blocker bad' }, dot('bad'), h('span', { class: 'grow', text: `${check.text} · 이 파일은 재생할 수 없습니다. Blender에서 다시 내보내세요.` })) : null,
    issues.length ? h('div', { class: 'blocker' }, dot('warn'),
      h('span', { class: 'grow', text: `범위 초과 조인트 ${issues.length}개 · ${issues.slice(0, 3).map((i) => `${i.id} ${signedDeg(i.min)} ~ ${signedDeg(i.max)}° (범위 ${signedDeg(i.lower)} ~ ${signedDeg(i.upper)}°)`).join(' · ')} · 범위를 넘는 값은 잘라서 재생합니다 · 고치려면 Blender에서 다시 내보내세요` })) : null,
    detail?.error ? h('p', { class: 'tone-text-bad small', text: detail.error }) : null,
    series.length
      ? h('div', { class: 'charts' }, series.map((item) => chart(item, rows.get(String(item.motion_id)))))
      : h('p', { class: 'muted small', text: detail ? '그래프 없음' : '그래프 불러오는 중…' }),
    h('div', { class: 'row' },
      h('button', { class: 'btn btn-primary', type: 'button',
        disabled: running || check.tone === 'bad' || !play.mappingId || playlist.length >= PLAYLIST_MAX,
        title: running ? '재생 중에는 목록을 바꿀 수 없습니다' : '', onclick: addToPlaylist }, inPlaylist ? '재생 목록에 한 번 더 추가' : '재생 목록에 추가'),
      ['missing', 'stale', 'failed'].includes(mujoco.state)
        ? h('button', { class: 'btn', type: 'button', onclick: async () => { await act.precompute(ui.selected); await loadPlay(state, changed); } },
          mujoco.state === 'missing' ? '3D 계산 시작' : '3D 다시 계산')
        : h('span', { class: `chip chip-${mujoco.tone}`, text: `3D · ${mujoco.text}` }),
      downloadUrl ? h('a', { class: 'btn', href: downloadUrl, download: ui.selected }, '다운로드') : null,
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn', type: 'button', disabled: inPlaylist || running,
        title: inPlaylist ? '재생 목록에 들어 있습니다. 먼저 재생 목록에서 빼세요.' : '',
        onclick: async () => {
          if (await act.deleteAnimation(ui.selected)) {
            ui.selected = '';
            ui.detail = null;
            await loadAnimations(state, changed);
          }
        } }, '삭제')),
    inPlaylist ? h('p', { class: 'muted small', text: '재생 목록에 들어 있어 삭제할 수 없습니다. 먼저 재생 목록에서 빼세요.' }) : null);
}

export function renderAnimations(state, { navigate, changed }) {
  current = { state, changed };
  return [
    h('div', { class: 'page-head' }, h('h1', { text: '애니메이션' })),
    h('div', { class: 'anim-grid' },
      listCard(state, changed),
      playlistCard(state, changed, {
        link: ['#/play', '재생 화면'],
        adding: false,
        selected: ui.selected,
        onPick: (id) => { ui.selected = id; ui.detail = null; changed(); loadDetail(state, changed); },
        reload: loadPlay,
      })),
    detailCard(state, changed, navigate),
  ];
}
