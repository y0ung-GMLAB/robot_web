/** UI v2 · 업데이트·백업 · 이 PC 코드 · 프로젝트 · 백업 zip · 자동 백업 · 휴지통 (설계안 2026-10-09)
 *
 * 로봇 1대 = 프로젝트 1개 · 프로젝트를 고르는 것과 장비에 적용하는 것은 다르다(고른 뒤 「모터·드라이브」 에서 적용).
 * 프로젝트 지우기는 이름을 쳐야 한다(기존 화면과 같음) · 지운 것은 휴지통에서 7일.
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, promptBox, toast } from '../dialog.js';
import * as act from '../actions.js';

const ui = { busy: '', memo: null, memoFor: '' };

export async function loadBackup(state, changed) {
  const page = state.backupPage || (state.backupPage = {});
  const [update, projects, backups, trash] = await Promise.allSettled([
    api('GET', '/api/system/update'),
    api('GET', '/api/projects'),
    api('GET', '/api/project-backups'),
    api('GET', '/api/project-trash'),
  ]);
  page.update = update.status === 'fulfilled' ? update.value : { error: update.reason?.message };
  page.projects = projects.status === 'fulfilled' ? projects.value : { error: projects.reason?.message };
  page.backups = backups.status === 'fulfilled' ? backups.value : { error: backups.reason?.message };
  page.trash = trash.status === 'fulfilled' ? trash.value : { error: trash.reason?.message };
  changed();
}

async function busy(key, work, state, changed) {
  if (ui.busy) return;
  ui.busy = key;
  changed();
  try { await work(); } finally {
    ui.busy = '';
    await loadBackup(state, changed);
  }
}

function sizeText(bytes) {
  const value = Number(bytes || 0);
  return value >= 1e6 ? `${(value / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1e3))} KB`;
}

/* ---------- 업데이트 ---------- */

const UPDATE_TEXT = { idle: '지난 업데이트 없음', running: '업데이트 중', done: '완료', failed: '실패 · 이전 버전으로 되돌림' };

function updateCard(state, changed) {
  const update = state.backupPage?.update || {};
  const running = update.state === 'running';
  const start = async () => {
    const ok = await confirmBox({
      title: '이 PC 만 업데이트',
      body: '이 PC 를 최신 코드로 바꿉니다(몇 분). 그동안 재생이 멈추고 화면이 잠깐 끊깁니다. 재생 중이면 거절합니다. 실패하면 이전 버전으로 되돌아가 계속 돕니다.\n같은 그룹 PC 는 버전이 같아야 같이 돕니다 · 보통은 「매장 PC 전부」 로 하세요.',
      confirmLabel: '업데이트', tone: 'warning',
    });
    if (!ok) return;
    await busy('update', async () => {
      try {
        const result = await api('POST', '/api/system/update', { timeoutMs: 30000 });
        toast(result?.message || '업데이트를 시작했습니다 · 화면이 잠깐 끊겼다 돌아옵니다', 'ok');
      } catch (error) { toast(error.message || String(error), 'bad'); }
    }, state, changed);
  };
  const before = String(update.before_hash || '').slice(0, 7);
  const after = String(update.after_hash || update.git_hash || '').slice(0, 7);
  return h('section', { class: 'card', 'aria-label': '업데이트' },
    h('div', { class: 'card-head' }, h('h2', { text: '업데이트' })),
    h('p', {}, h('span', { text: '이 PC · ' }), h('span', { class: 'mono', text: String(update.git_hash || '-').slice(0, 7) }),
      update.state ? h('span', { class: `chip chip-${update.state === 'failed' ? 'bad' : running ? 'info' : 'idle'}`, text: ` ${UPDATE_TEXT[update.state] || update.state}${before && after && before !== after ? ` · ${before} → ${after}` : ''}` }) : null),
    update.message ? h('p', { class: update.state === 'failed' ? 'tone-text-bad small' : 'muted small', text: update.message }) : null,
    running && Array.isArray(update.tail) && update.tail.length ? h('pre', { class: 'doc-code small' }, h('code', { text: update.tail.slice(-6).join('\n') })) : null,
    h('div', { class: 'row' },
      h('a', { class: 'btn btn-primary', href: '#/store' }, '매장 PC 전부 업데이트 ›'),
      h('button', { class: 'btn', type: 'button', disabled: Boolean(ui.busy) || running, onclick: start }, '이 PC 만…')),
    h('p', { class: 'muted small', text: '새 시스템 패키지가 필요한 업데이트는 그 PC 터미널에서 bash scripts/install.sh' }));
}

/* ---------- 프로젝트 ---------- */

function projectCard(state, changed) {
  const data = state.backupPage?.projects || {};
  const projects = Array.isArray(data.projects) ? data.projects : [];
  const selectedId = String(data.selected_project_id || '');
  const current = projects.find((p) => p.project_id === selectedId);
  const scope = state.snap?.project_scope || {};
  if (current && ui.memoFor !== selectedId) { ui.memo = String(current.memo || ''); ui.memoFor = selectedId; }
  const others = projects.filter((p) => p.project_id !== selectedId);
  const pick = async (project) => {
    const ok = await confirmBox({
      title: '프로젝트 바꾸기',
      body: `「${project.name || project.project_id}」 로 바꿉니다.\n화면의 매핑·애니메이션·스케줄이 그 프로젝트 것으로 바뀝니다. 장비(모터)에는 아직 적용되지 않습니다 · 바꾼 뒤 「모터·드라이브」 에서 「장비에 적용」.`,
      confirmLabel: '바꾸기', tone: 'warning',
    });
    if (!ok) return;
    await busy('select', async () => {
      try {
        await api('POST', `/api/projects/${encodeURIComponent(project.project_id)}/select`);
        toast('프로젝트를 바꿨습니다 · 장비에는 아직 적용되지 않았습니다', 'warn');
      } catch (error) { toast(error.message || String(error), 'bad'); }
    }, state, changed);
  };
  const create = async () => {
    const name = await promptBox({ title: '새 프로젝트', label: '이름 · 예 floating4_1800', confirmLabel: '만들기' });
    if (!name) return;
    await busy('create', async () => {
      try {
        await api('POST', '/api/projects', { body: { name } });
        toast(`「${name}」 를 만들었습니다 · 고르려면 목록에서 「고르기」`, 'ok');
      } catch (error) { toast(error.message || String(error), 'bad'); }
    }, state, changed);
  };
  const remove = async (project) => {
    const name = String(project.name || project.project_id);
    const typed = await promptBox({
      title: '프로젝트 지우기', body: `「${name}」 를 지웁니다. 휴지통에 7일 남습니다.`,
      label: `지우려면 이름을 그대로 치세요 · ${name}`, must: name, confirmLabel: '지우기', tone: 'danger',
    });
    if (typed === null) return;
    await busy('delete', async () => {
      try {
        await api('DELETE', `/api/projects/${encodeURIComponent(project.project_id)}`);
        toast('지웠습니다 · 휴지통에서 7일 안에 되살릴 수 있습니다', 'ok');
      } catch (error) { toast(error.message || String(error), 'bad'); }
    }, state, changed);
  };
  const saveMemo = () => busy('memo', async () => {
    try {
      await api('PATCH', `/api/projects/${encodeURIComponent(selectedId)}`, { body: { memo: ui.memo } });
      toast('메모를 저장했습니다', 'ok');
      ui.memoFor = '';
    } catch (error) { toast(error.message || String(error), 'bad'); }
  }, state, changed);
  return h('section', { class: 'card', 'aria-label': '프로젝트' },
    h('div', { class: 'card-head' }, h('h2', { text: '프로젝트 · 로봇 1대 = 프로젝트 1개' }),
      h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy), onclick: create }, '새로 만들기…')),
    data.error ? h('p', { class: 'tone-text-bad small', text: data.error }) : null,
    current ? [
      h('p', {}, h('strong', { text: current.name || current.project_id }), ' ',
        scope.runtime_matches_selected && scope.motor_config_applied
          ? h('span', { class: 'chip chip-ok', text: '장비에 적용됨' })
          : h('span', { class: 'chip chip-warn', text: '장비에 아직 적용 안 됨' }),
        h('span', { class: 'muted small mono', text: ` · 애니메이션 ${current.counts?.motions ?? '-'} · 매핑 ${current.counts?.motion_axis_matching ?? '-'}` })),
      h('label', { class: 'field' }, h('span', { class: 'field-label', text: '메모 (다음 사람이 볼 것)' }),
        h('textarea', { class: 'input memo', rows: '2', oninput: (e) => { ui.memo = e.target.value; } }, ui.memo ?? '')),
      h('div', { class: 'row end' }, h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy), onclick: saveMemo }, '메모 저장')),
    ] : h('p', { class: 'muted', text: projects.length ? '고른 프로젝트가 없습니다' : '프로젝트가 없습니다 · 새로 만드세요' }),
    others.length ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: `다른 프로젝트 · ${others.length}` }),
      h('ul', { class: 'list' }, others.map((project) => h('li', { class: 'list-row' },
        h('span', { class: 'grow', text: project.name || project.project_id }),
        h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy), onclick: () => pick(project) }, '고르기…'),
        h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy), onclick: () => remove(project) }, '지우기…'))))) : null);
}

/* ---------- 백업 ---------- */

function backupCard(state, changed) {
  const data = state.backupPage || {};
  const selectedId = String(data.projects?.selected_project_id || '');
  const days = Array.isArray(data.backups?.days) ? data.backups.days : [];
  const trash = Array.isArray(data.trash?.entries) ? data.trash.entries : [];
  const picker = h('input', { type: 'file', accept: '.zip,application/zip', hidden: true, onchange: (e) => restore(e.target.files?.[0]) });
  async function restore(file) {
    if (!file) return;
    const ok = await confirmBox({ title: 'zip 으로 복원', body: `「${file.name}」 (${sizeText(file.size)}) 를 프로젝트로 들여옵니다. 같은 이름이 있으면 한 번 더 묻습니다.`, confirmLabel: '들여오기' });
    if (!ok) return;
    await busy('import', async () => {
      const send = (overwrite) => api('POST', `/api/project-import${overwrite ? '?overwrite=true' : ''}`, { raw: file, contentType: 'application/zip', timeoutMs: 120000 });
      try {
        const result = await send(false);
        toast(result?.message || '들여왔습니다 · 고른 뒤 「장비에 적용」', 'ok');
      } catch (error) {
        if (error.data?.exists) {
          const again = await confirmBox({ title: '같은 프로젝트가 있습니다', body: `${error.data.project_id} 가 이미 있습니다. 덮어쓸까요? 지금 것은 휴지통으로 갑니다(7일).`, confirmLabel: '덮어쓰기', tone: 'danger' });
          if (again) {
            try { toast((await send(true))?.message || '덮어썼습니다', 'ok'); } catch (e2) { toast(e2.message || String(e2), 'bad'); }
          }
        } else {
          toast(error.message || String(error), 'bad');
        }
      }
    }, state, changed);
  }
  const revive = (entry) => busy('restore', async () => {
    try {
      const result = await api('POST', `/api/project-trash/${encodeURIComponent(entry.entry)}/restore`);
      toast(result?.message || '되살렸습니다', 'ok');
    } catch (error) { toast(error.message || String(error), 'bad'); }
  }, state, changed);
  return h('section', { class: 'card', 'aria-label': '백업' },
    h('div', { class: 'card-head' }, h('h2', { text: '백업' })),
    h('p', { class: 'muted small', text: '매핑 · 모터 설정 · 애니메이션 · 스케줄을 zip 하나로' }),
    h('div', { class: 'row' },
      selectedId ? h('a', { class: 'btn btn-primary', href: `/api/projects/${encodeURIComponent(selectedId)}/export`, download: '' }, '지금 zip 내려받기') : null,
      h('button', { class: 'btn', type: 'button', disabled: Boolean(ui.busy), onclick: () => picker.click() }, ui.busy === 'import' ? '들여오는 중…' : 'zip 올려 복원…'),
      picker),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: `자동 백업 · 매일 · ${data.backups?.keep_days ?? 14}일` }),
      days.length ? h('ul', { class: 'list' }, days.slice(0, 7).map((day) => h('li', { class: 'list-row' },
        h('span', { class: 'mono grow', text: day.day }),
        (day.projects || []).map((project) => h('a', { class: 'btn btn-mini', download: '',
          href: `/api/project-backups/${encodeURIComponent(day.day)}/${encodeURIComponent(project.project_id)}` },
        `${project.project_id} · ${sizeText(project.size_bytes)}`)))))
        : h('p', { class: 'muted small', text: data.backups?.error || '아직 없음' })),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: `휴지통 · ${data.trash?.keep_days ?? 7}일 뒤 지워짐` }),
      trash.length ? h('ul', { class: 'list' }, trash.map((entry) => h('li', { class: 'list-row' },
        h('span', { class: 'grow', text: entry.name || entry.project_id }),
        h('span', { class: 'mono muted small', text: String(entry.deleted_at || '').slice(0, 16).replace('T', ' ') }),
        h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy), onclick: () => revive(entry) }, '되살리기'))))
        : h('p', { class: 'muted small', text: data.trash?.error || '비었음' })));
}

export function renderBackup(state, { changed }) {
  const running = state.backupPage?.update?.state === 'running';
  return [
    h('div', { class: 'page-head' }, h('h1', { text: '업데이트·백업' })),
    running ? h('div', { class: 'blocker' }, dot('info'), h('span', { class: 'grow', text: '업데이트 중 · 끝나면 화면이 잠깐 끊겼다 다시 붙습니다' })) : null,
    h('div', { class: 'grid-2' }, updateCard(state, changed), projectCard(state, changed)),
    backupCard(state, changed),
    h('p', { class: 'muted small' }, '프로그램만 다시 띄우려면 ', h('button', { class: 'link-button inline-link', type: 'button', onclick: act.restartProgram }, '프로그램 다시 시작…'), ' (모터·서보는 그대로)'),
  ];
}
