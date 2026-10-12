/** UI v2 · 로봇 팩·3D · 로봇 모양(MuJoCo 모델·메쉬) · 조인트 기본값 · Blender 장면 (설계안 2026-10-09)
 *
 * 올리면 서버가 끝까지 검사한다(모델 로드까지 · 수십 초) · 하나라도 못 넘으면 지금 팩을 그대로 둔다.
 * 팩의 조인트 값은 기본값일 뿐 · 실제 값은 이 PC 조인트 매핑이 정한다(여기서는 비교만).
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import { filesFromDrop, zipFiles } from '../zip_store.js';
import { mujocoState } from '../anim_model.js';

const ui = { busy: '', result: null };
let current = { state: null, changed: () => {} };

export async function loadPack(state, changed) {
  current = { state, changed };
  const page = state.packPage || (state.packPage = {});
  const [pack, diff, scene, files] = await Promise.allSettled([
    api('GET', '/api/robot-pack'),
    api('GET', '/api/robot-pack/mapping-diff'),
    api('GET', '/api/preview/scene'),
    api('GET', '/api/motion-files'),
  ]);
  page.pack = pack.status === 'fulfilled' ? pack.value : { error: pack.reason?.message };
  page.diff = diff.status === 'fulfilled' ? diff.value : null;
  page.scene = scene.status === 'fulfilled' ? scene.value : null;
  page.files = files.status === 'fulfilled' ? (files.value?.files || []) : [];
  changed();
}

function when(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

async function upload(blob, label) {
  const { state, changed } = current;
  const limit = Number(state.packPage?.pack?.limits?.max_zip_bytes || 52428800);
  if (blob.size > limit) {
    toast(`팩이 너무 큽니다 · ${(blob.size / 1e6).toFixed(1)} MB (최대 ${(limit / 1e6).toFixed(0)} MB)`, 'bad');
    return;
  }
  if (ui.busy) return;
  ui.busy = `검사 중 · ${label} (${(blob.size / 1e6).toFixed(1)} MB) · 모델 로드 검사까지 수십 초 걸릴 수 있습니다`;
  ui.result = null;
  changed();
  try {
    const result = await api('PUT', '/api/robot-pack', { raw: blob, contentType: 'application/zip', timeoutMs: 240000 });
    ui.result = { ok: true, message: result?.message || '로봇 팩을 바꿨습니다', items: (result?.warnings || []).map((w) => `경고 · ${w}`) };
  } catch (error) {
    ui.result = { ok: false, message: error.message || String(error), items: [...(error.data?.errors || []), ...(error.data?.warnings || []).map((w) => `경고 · ${w}`)] };
  } finally {
    ui.busy = '';
    await loadPack(state, changed);
  }
}

async function uploadFolder(items, label) {
  try {
    ui.busy = `묶는 중 · ${label}`;
    current.changed();
    const blob = await zipFiles(items);
    ui.busy = '';
    await upload(blob, label);
  } catch (error) {
    ui.busy = '';
    toast(error.message || String(error), 'bad');
    current.changed();
  }
}

function onDrag(event) {
  if (!location.hash.startsWith('#/pack')) return;
  if (![...(event.dataTransfer?.types || [])].includes('Files')) return;
  event.preventDefault();
  document.body.classList.toggle('drop-active', event.type !== 'dragleave' || event.relatedTarget !== null);
  if (event.type !== 'drop') return;
  document.body.classList.remove('drop-active');
  const file = event.dataTransfer.files?.[0];
  const entry = event.dataTransfer.items?.[0]?.webkitGetAsEntry?.();
  if (entry?.isDirectory) {
    filesFromDrop(event.dataTransfer).then((items) => uploadFolder(items, `${entry.name}/`));
  } else if (file && /\.zip$/i.test(file.name)) {
    upload(file, file.name);
  } else {
    toast('팩은 .zip 이나 팩 폴더를 놓으세요', 'warn');
  }
}
['dragenter', 'dragover', 'dragleave', 'drop'].forEach((kind) => document.addEventListener(kind, onDrag));

function packCard(state, changed) {
  const page = state.packPage || {};
  const packData = page.pack || {};
  const pack = packData.current;
  const previous = packData.previous;
  const blender = page.scene?.blender || {};
  const zipPicker = h('input', { type: 'file', accept: '.zip,application/zip', hidden: true, onchange: (e) => { const f = e.target.files?.[0]; if (f) upload(f, f.name); } });
  const dirPicker = h('input', { type: 'file', hidden: true, webkitdirectory: true, multiple: true,
    onchange: (e) => {
      const files = [...(e.target.files || [])];
      if (!files.length) return;
      const items = files.map((file) => ({ path: file.webkitRelativePath || file.name, file }));
      uploadFolder(items, `${items[0].path.split('/')[0]}/`);
    } });
  const rollback = async () => {
    const ok = await confirmBox({ title: '이전 팩으로 되돌리기', body: `이전 로봇 팩(${previous?.name || ''} ${previous?.version || ''})으로 되돌립니다 · 지금 팩은 이전 팩 자리로 갑니다.\n3D 계산 결과는 다시 계산이 필요해집니다.`, confirmLabel: '되돌리기', tone: 'warning' });
    if (!ok) return;
    ui.busy = '되돌리는 중';
    changed();
    try {
      const result = await api('POST', '/api/robot-pack/rollback', { timeoutMs: 60000 });
      toast(result?.message || '되돌렸습니다', 'ok');
    } catch (error) { toast(error.message || String(error), 'bad'); }
    finally { ui.busy = ''; await loadPack(state, changed); }
  };
  return h('section', { class: 'card', 'aria-label': '지금 쓰는 팩' },
    h('div', { class: 'card-head' }, h('h2', { text: '지금 쓰는 팩' })),
    packData.error ? h('p', { class: 'tone-text-bad small', text: packData.error }) : null,
    pack ? [
      h('p', {}, h('strong', { class: 'pack-name', text: pack.name || '-' }), ' ', h('span', { class: 'mono', text: pack.version || '' }),
        h('span', { class: 'muted small', text: ` · ${when(pack.uploaded_at)} 올림` })),
      h('p', { class: 'muted small', text: `Blender 장면 ${blender.available ? `있음${(blender.animations || []).length ? ` (${blender.animations.join(', ')})` : ''}` : '없음'}` }),
      (pack.warnings || []).length ? h('ul', { class: 'list small' }, pack.warnings.map((w) => h('li', { class: 'tone-text-warn', text: `경고 · ${w}` }))) : null,
    ] : h('p', { class: 'muted', text: '팩이 없습니다 · 3D 와 3D 계산이 꺼져 있습니다' }),
    previous ? h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', disabled: Boolean(ui.busy), onclick: rollback }, `이전 팩(${previous.version || previous.name})으로 되돌리기…`)) : null,
    h('div', { class: 'drop-zone' },
      h('strong', { text: '새 팩 올리기' }),
      h('span', { class: 'muted small', text: 'zip 이나 팩 폴더를 이 화면에 끌어 놓기 · 폴더는 브라우저가 묶어서 올림' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn btn-primary', type: 'button', disabled: Boolean(ui.busy), onclick: () => zipPicker.click() }, 'zip 고르기'),
        h('button', { class: 'btn', type: 'button', disabled: Boolean(ui.busy), onclick: () => dirPicker.click() }, '폴더 고르기'),
        zipPicker, dirPicker)),
    ui.busy ? h('div', { class: 'busy-line', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), ui.busy) : null,
    ui.result ? h('div', { class: `blocker${ui.result.ok ? ' ok' : ' bad'}` }, dot(ui.result.ok ? 'ok' : 'bad'),
      h('div', { class: 'grow' }, h('strong', { text: ui.result.message }),
        ui.result.items.length ? h('ul', { class: 'list small' }, ui.result.items.map((item) => h('li', { text: item }))) : null)) : null);
}

function diffCard(state) {
  const diff = state.packPage?.diff;
  const rows = (diff?.rows || []).filter((row) => (row.differences || []).length);
  const fmtRange = (range) => (Array.isArray(range) ? `${Number(range[0]).toFixed(1)} ~ ${Number(range[1]).toFixed(1)}°` : '-');
  return h('section', { class: 'card', 'aria-label': '매핑과 다른 칸' },
    h('div', { class: 'card-head' }, h('h2', { text: `이 PC 조인트 매핑과 다른 칸 · ${rows.length}` }), h('a', { href: '#/mapping', text: '조인트 매핑' })),
    h('p', { class: 'muted small', text: '팩은 기본값 · 실제 값은 이 PC 매핑이 정합니다 · 다르면 일부러 바꾼 것인지 확인하세요' }),
    !diff || diff.available === false ? h('p', { class: 'muted', text: diff?.message || '비교할 팩이나 매핑이 없습니다' })
      : rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, ['조인트', '다른 칸', '팩', '이 PC'].map((text) => h('th', { scope: 'col', text })))),
        h('tbody', {}, rows.map((row) => h('tr', {},
          h('td', { class: 'mono', text: row.motion_id || row.joint }),
          h('td', { text: row.differences.join(' · ') }),
          h('td', { class: 'mono', text: `${row.pack_ratio ?? '-'} · ${fmtRange(row.pack_range)}` }),
          h('td', { class: 'mono', text: `${row.mapping_ratio ?? '-'} · ${fmtRange(row.mapping_range)}` }))))))
        : h('p', { class: 'muted', text: '다른 칸 없음' }));
}

const SCENE_TEXT = { ready: ['준비됨', 'ok'], computing: ['만드는 중', 'info'], failed: ['실패', 'bad'], missing: ['아직 없음', 'idle'], unavailable: ['팩 없음', 'idle'] };

function sceneCard(state, changed) {
  const page = state.packPage || {};
  const scene = page.scene || {};
  const [text, tone] = SCENE_TEXT[scene.state] || ['-', 'idle'];
  const counts = {};
  for (const file of page.files || []) {
    const { text: label } = mujocoState(file);
    counts[label] = (counts[label] || 0) + 1;
  }
  const rebuild = async () => {
    try {
      const result = await api('POST', '/api/preview/scene/export');
      toast(result?.message || '3D 장면을 다시 만듭니다 · 몇 초', 'ok');
    } catch (error) { toast(error.message || String(error), 'bad'); }
    await loadPack(state, changed);
  };
  return h('section', { class: 'card', 'aria-label': '3D' },
    h('div', { class: 'card-head' }, h('h2', { text: '3D' })),
    h('div', { class: 'list-row' }, h('span', { class: 'grow', text: '3D 장면' }), h('span', { class: `chip chip-${tone}`, text: text }),
      h('button', { class: 'btn btn-mini', type: 'button', disabled: scene.state === 'computing' || scene.state === 'unavailable', onclick: rebuild }, '다시 만들기')),
    scene.message ? h('p', { class: 'muted small', text: scene.message }) : h('p', { class: 'muted small', text: '팩을 바꾸면 처음 볼 때 저절로 다시 만듭니다(몇 초)' }),
    h('div', { class: 'list-row' }, h('span', { class: 'grow', text: `애니메이션 3D 계산 · ${(page.files || []).length}` }),
      h('span', { class: 'muted small', text: Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(' · ') || '-' }),
      h('a', { href: '#/animations', text: '애니메이션에서 보기 ›' })),
    h('p', { class: 'muted small', text: '계산은 프로그램과 따로 돌아 다시 시작해도 이어집니다' }));
}

export function renderPack(state, { changed }) {
  current = { state, changed };
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '로봇 팩·3D' }),
      h('p', { class: 'muted small', text: '로봇 모양(MuJoCo 모델 · 메쉬) · 조인트 기본값 · Blender 장면' })),
    h('div', { class: 'grid-2' }, packCard(state, changed), h('div', { class: 'stack' }, sceneCard(state, changed), diffCard(state))),
  ];
}
