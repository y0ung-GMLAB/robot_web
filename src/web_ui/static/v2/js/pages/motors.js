/** UI v2 · 모터·드라이브 · 지금 상태 · 설정 고치기 · 드라이브 정비 · 앱솔루트 (설계안 2026-10-09)
 *
 * 저장은 파일만 · 드라이브에 들어가는 것은 「장비에 적용 · 모터 재시작」 뒤(§6-221) · 저장 버튼은 늘 눌린다(§6-203).
 * 서보 켜기/끄기 · 알람 리셋은 운전 모드와 무관(서버 run_mode_gate) · 끄기·재부팅·정비는 확인 창.
 * 「…」 이 붙은 버튼은 확인 창이 뜬다 · 빨간 글은 위치 기준이 바뀌는 일.
 * 모터 검색은 지금 기존 화면에서(검색 결과를 설정으로 옮기는 일이 커서 다음 단계).
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import * as act from '../actions.js';
import { EDIT_FIELDS, absoluteJobText, absoluteSummary, getField, motorChanges, motorProblems, motorRows, setField } from '../motors_model.js';
import { signedDeg } from '../play_model.js';

const ui = { revision: '', saved: null, draft: null, selected: null, job: null, busy: '', error: '' };
let jobTimer = null;

function clone(motors) {
  return (motors || []).map((m) => ({ ...m, config: { ...(m.config || {}) } }));
}

function dirty() {
  return ui.draft ? motorChanges(ui.saved, ui.draft.motors).length > 0 : false;
}

export async function loadMotors(state, changed, { force = false } = {}) {
  try {
    if (!dirty() || force) {
      const data = await api('GET', '/api/motor-config');
      const registry = data?.registry || { motors: [] };
      ui.revision = String(data?.config_revision || '');
      ui.saved = clone(registry.motors);
      ui.draft = { ...registry, motors: clone(registry.motors) };
      ui.message = data?.saved === false ? String(data?.message || '') : '';
    }
    ui.job = await api('GET', '/api/motor-config/absolute-setup').catch(() => ui.job);
    ui.error = '';
  } catch (error) {
    ui.error = error.message || String(error);
  }
  if (ui.selected === null && ui.draft?.motors?.length) ui.selected = Number(ui.draft.motors[0].axis);
  watchJob(state, changed);
  changed();
}

function watchJob(state, changed) {
  if (ui.job?.state === 'running' && !jobTimer) {
    jobTimer = setInterval(async () => {
      try { ui.job = await api('GET', '/api/motor-config/absolute-setup', { timeoutMs: 3000 }); } catch { /* 다음에 */ }
      if (ui.job?.state !== 'running' || !location.hash.startsWith('#/maintain-motors')) { clearInterval(jobTimer); jobTimer = null; }
      changed();
    }, 1000);
  }
}

/* ---------- 버튼이 하는 일 ---------- */

async function run(label, work, state, changed) {
  if (ui.busy) return null;
  ui.busy = label;
  changed();
  try {
    const result = await work();
    if (result?.message) toast(result.message, 'ok');
    return result;
  } catch (error) {
    toast(error.message || String(error), 'bad');
    return null;
  } finally {
    ui.busy = '';
    await loadMotors(state, changed);
  }
}

async function servo(row, action, state, changed) {
  if (ui.busy) return;
  ui.busy = `${row.axis}번`;
  changed();
  try { await act.servoControl(row, action); } finally {
    ui.busy = '';
    await loadMotors(state, changed);
  }
}

async function maintenance(row, action, state, changed) {
  const texts = {
    eeprom_save: { title: `${row.axis}번 드라이브에 저장 (EEPROM)`, body: '드라이브의 지금 값을 전원을 꺼도 남게 저장합니다. Motor Manager 를 잠시 멈췄다가 다시 띄웁니다(몇 초) · 그동안 모터는 서보가 풀릴 수 있습니다.\n저장 중(최대 10초) 드라이브 전원을 끄지 마세요.', tone: 'warning', label: '저장' },
    absolute_clear: { title: `${row.axis}번 다회전 클리어`, body: '엔코더의 회전 수 기록을 0 으로 지웁니다 · 위치 기준이 바뀝니다.\n서보가 꺼져 있어야 합니다 · 끝나면 드라이브 전원을 껐다 켜세요 · 위치 숫자가 바뀌어 기준점을 다시 캡처해야 합니다. 그 전에는 재생하지 마세요.', tone: 'danger', label: '클리어' },
  }[action];
  if (action === 'absolute_clear' && row.servoOn) { toast('서보를 먼저 끄세요 · 다회전 클리어는 서보가 꺼져 있어야 합니다', 'warn'); return; }
  const ok = await confirmBox({ ...texts, confirmLabel: texts.label });
  if (!ok) return;
  const result = await run(`${row.axis}번 정비`, () => api('POST', '/api/motor-config/drive-maintenance', {
    body: { action, axis: row.axis, confirmed: true }, timeoutMs: 60000,
  }), state, changed);
  if (result?.power_cycle_required) {
    await confirmBox({ title: '드라이브 전원 재투입 필요', body: '드라이브 전원을 껐다 켜야 바뀐 값이 들어갑니다. 켠 뒤 기준점을 다시 캡처하세요.', confirmLabel: '알겠습니다' });
  }
}

async function absoluteSetup(scope, row, state, changed) {
  const body = scope === 'all' ? { scope: 'all' } : { scope: 'one', master_index: row.masterIndex, slave_position: row.slavePosition };
  let preview;
  try {
    preview = await api('POST', '/api/motor-config/absolute-setup/preview', { body });
  } catch (error) { toast(error.message || String(error), 'bad'); return; }
  const targets = (preview?.targets || []).map((t) => `· ${t.label || t.axis}${t.problem ? ` (${t.problem})` : ''}`);
  const skipped = (preview?.skipped || []).map((t) => `· ${t.label || t.axis} · ${t.reason || '이미 정상'}`);
  if (!targets.length) { toast(preview?.message || '할 것이 없습니다 · 이미 앱솔루트 정상', 'ok'); return; }
  const ok = await confirmBox({
    title: '앱솔루트 설정',
    body: `대상\n${targets.join('\n')}${skipped.length ? `\n\n건너뜀(이미 정상 · 다시 하면 기준점이 사라짐)\n${skipped.join('\n')}` : ''}\n\n${(preview?.steps || []).map((s, i) => `${i + 1}. ${s.label || s}`).join('\n')}\n\n대상 축 서보를 끄고 Motor Manager 를 두 번 잠시 멈춥니다. 중간에 드라이브 전원을 두 번 껐다 켜야 합니다(화면이 알려 줍니다). 끝나면 위치 숫자가 바뀌어 기준점을 다시 캡처해야 합니다.`,
    confirmLabel: '시작', tone: 'danger',
  });
  if (!ok) return;
  await run('앱솔루트 설정', () => api('POST', '/api/motor-config/absolute-setup', { body: { ...body, confirmed: true }, timeoutMs: 20000 }), state, changed);
}

async function save(state, changed, { apply = false } = {}) {
  const problems = motorProblems(ui.draft?.motors);
  if (problems.length) { toast(problems[0], 'bad'); return; }
  if (apply && !(await act.confirmApplyMotorConfig(dirty() ? '모터 설정을 저장한 뒤 바로 장비에 적용합니다.' : '저장된 모터 설정을 장비에 적용합니다.'))) return;
  ui.busy = '저장 중';
  changed();
  try {
    const result = await api('PUT', '/api/motor-config', { body: { registry: ui.draft, base_revision: ui.revision }, timeoutMs: 20000 });
    // 바꾼 것이 없어도 저장은 된다 · 결과는 늘 보이게(§6-203)
    await confirmBox({ title: '저장했습니다', body: `${result?.message || '모터 설정 파일을 저장했습니다'}\n\n드라이브에 넣으려면 「장비에 적용 · 모터 재시작」.`, confirmLabel: '확인' });
    await loadMotors(state, changed, { force: true });
    if (apply) await act.applyMotorConfig();
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = '';
    changed();
  }
}

/* ---------- 그리기 ---------- */

function stepsStrip(state, rows) {
  const scope = state.snap?.project_scope || {};
  const applied = scope.runtime_matches_selected === true && scope.motor_config_applied === true;
  const detected = rows.filter((r) => r.detected).length;
  const steps = [
    [rows.length > 0 && detected === rows.length, `모터 찾기 · ${detected}/${rows.length}대`],
    [rows.length > 0 && rows.every((r) => r.name), '이름·설정'],
    [null, '조인트 매핑'],
    [applied && !dirty(), applied ? (dirty() ? '장비에 적용 · 저장부터' : '장비에 적용됨') : '장비에 적용 필요'],
  ];
  return h('ol', { class: 'steps', 'aria-label': '순서' }, steps.map(([done, label], i) => h('li', { class: `step ${done === true ? 'step-done' : done === false ? 'step-now' : ''}` },
    i === 2 ? h('a', { href: '#/mapping', text: `${i + 1} · ${label}` }) : `${done ? '✓ ' : ''}${i + 1} · ${label}`)));
}

function detailCard(state, changed, row) {
  const motor = ui.draft?.motors?.find((m) => Number(m.axis) === row.axis);
  if (!motor) return null;
  const busy = Boolean(ui.busy);
  const input = (field) => {
    if (field.ac && !row.ac) return null;
    const value = getField(motor, field.key);
    return h('label', { class: 'field' }, h('span', { class: 'field-label', text: `${field.label}${field.unit ? ` (${field.unit})` : ''}` }),
      h('input', { class: `input${field.top ? '' : ' mono'}`, type: field.top ? 'text' : 'number', step: 'any', value: value ?? '',
        placeholder: field.top ? '' : '드라이브 값 그대로',
        oninput: (e) => setField(motor, field.key, field.top ? e.target.value : (e.target.value === '' ? null : Number(e.target.value))),
        onchange: () => changed() }));
  };
  return h('section', { class: 'card', 'aria-label': `${row.axis}번 자세히` },
    h('div', { class: 'card-head' }, h('h2', { text: `${row.axis}번 · ${row.name || '-'}` }), h('span', { class: 'muted small mono', text: row.id })),
    h('div', { class: 'row form-row' }, EDIT_FIELDS.map(input)),
    row.ac ? h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: Number(motor.config?.overload_monitor) === 1,
      onchange: (e) => { setField(motor, 'overload_monitor', e.target.checked ? 1 : 0); changed(); } }),
    '과부하율 받기 (드라이브 소프트웨어 Ver1.03 이상만 · 아니면 Motor Manager 가 안 뜸)') : null,
    h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: motor.config?.schedule_end_servo_off === true,
      onchange: (e) => { setField(motor, 'schedule_end_servo_off', e.target.checked); changed(); } }), '운영 시간이 끝나면 서보 끄기'),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '드라이브 정비' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn btn-mini', type: 'button', disabled: busy, onclick: () => servo(row, 'reset', state, changed) }, row.ac ? `오류 초기화${row.fault ? '' : ' (알람 없음)'}` : '재부팅…'),
        row.servoOn
          ? h('button', { class: 'btn btn-mini', type: 'button', disabled: busy, onclick: () => servo(row, 'off', state, changed) }, row.ac ? '서보 끄기…' : '토크 끄기…')
          : h('button', { class: 'btn btn-mini', type: 'button', disabled: busy || row.fault || !row.detected, onclick: () => servo(row, 'on', state, changed) }, row.ac ? '서보 켜기' : '토크 켜기'),
        row.ac ? h('button', { class: 'btn btn-mini', type: 'button', disabled: busy, onclick: () => maintenance(row, 'eeprom_save', state, changed) }, '드라이브에 저장 (EEPROM)…') : null,
        row.ac ? h('button', { class: 'btn btn-mini', type: 'button', disabled: busy || row.absolute === '정상', title: row.absolute === '정상' ? '이미 앱솔루트 정상 · 다시 하면 기준점이 사라집니다' : '',
          onclick: () => absoluteSetup('one', row, state, changed) }, row.absolute === '정상' ? '앱솔루트 정상' : '앱솔루트 설정…') : null,
        row.ac ? h('button', { class: 'btn btn-mini danger-text', type: 'button', disabled: busy, onclick: () => maintenance(row, 'absolute_clear', state, changed) }, '다회전 클리어…') : null),
      h('p', { class: 'muted small', text: '「…」 은 확인 창이 뜨는 일 · 빨간 글은 위치 기준이 바뀌는 일' })),
    h('details', { class: 'raw' }, h('summary', { text: '원본 (드라이브 정보)' }),
      h('pre', { class: 'doc-code small' }, h('code', { text: JSON.stringify({ identity: motor.identity, profile: motor.profile, config: motor.config }, null, 2) }))));
}

export function renderMotors(state, { changed }) {
  if (!ui.draft) {
    return [h('div', { class: 'page-head' }, h('h1', { text: '모터·드라이브' })),
      h('p', { class: ui.error ? 'tone-text-bad' : 'muted', text: ui.error || '불러오는 중…' })];
  }
  const rows = motorRows(ui.draft, state.snap);
  const abs = absoluteSummary(rows);
  const faults = rows.filter((r) => r.fault);
  const changes = motorChanges(ui.saved, ui.draft.motors);
  const problems = motorProblems(ui.draft.motors);
  const selected = rows.find((r) => r.axis === ui.selected) || rows[0];
  const jobText = absoluteJobText(ui.job);
  const runtime = state.snap?.service_management?.runtime || {};
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '모터·드라이브' }),
      h('span', { class: 'spacer' }),
      h('a', { class: 'btn', href: '/', title: '검색 결과를 설정으로 옮기는 일은 지금 기존 화면에서 · 저장하면 여기에도 보입니다' }, '모터 다시 검색 (기존 화면) ↗')),
    stepsStrip(state, rows),
    ui.message ? h('p', { class: 'muted', text: ui.message }) : null,
    runtime.motor_manager_start_block_reason || (runtime.phase && runtime.phase !== 'ready')
      ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: `모터 프로그램 · ${runtime.motor_manager_start_block_reason || runtime.message || runtime.phase}` })) : null,
    h('div', { class: `blocker ${abs.allOk ? 'ok' : ''}` }, dot(abs.allOk ? 'ok' : 'warn'),
      h('span', { class: 'grow', text: abs.total ? `앱솔루트 ${abs.ok}/${abs.total} 정상${abs.allOk ? ' · 껐다 켜도 위치가 남습니다' : ' · 정상이 아니면 모든 모터 동작이 막힙니다(수정 목록 62)'}` : 'AC 서보 없음' }),
      !abs.allOk && abs.total ? h('button', { class: 'btn btn-warn', type: 'button', disabled: Boolean(ui.busy) || ui.job?.state === 'running', onclick: () => absoluteSetup('all', null, state, changed) }, '앱솔루트 설정 (전체)…') : null),
    jobText ? h('div', { class: `blocker ${ui.job.state === 'failed' ? 'bad' : ''}` }, dot(ui.job.state === 'failed' ? 'bad' : 'info'),
      h('span', { class: 'grow', text: jobText }),
      ui.job.state === 'running' ? h('button', { class: 'btn', type: 'button', onclick: () => run('취소', () => api('POST', '/api/motor-config/absolute-setup/cancel'), state, changed) }, '취소') : null) : null,
    faults.map((row) => h('div', { class: 'issue issue-bad' }, dot('bad'),
      h('div', { class: 'issue-text' }, h('strong', { text: `${row.axis}번 · ${row.name} · ${row.error || '알람'}` }),
        h('span', { text: '걸린 것이 없는지 보고 오류 초기화 → 서보 켜기' })),
      h('button', { class: 'btn btn-danger-soft', type: 'button', disabled: Boolean(ui.busy), onclick: () => servo(row, 'reset', state, changed) }, row.ac ? '오류 초기화' : '재부팅…'))),
    h('section', { class: 'card', 'aria-label': '모터' },
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table files-table' },
        h('thead', {}, h('tr', {}, ['번호', '이름', '종류 · 모델', '서보', '위치 (모터°)', '과부하율', '앱솔루트', '통신', ''].map((text) => h('th', { scope: 'col', text })))),
        h('tbody', {}, rows.map((row) => h('tr', { class: row.axis === selected?.axis ? 'selected' : '' },
          h('td', { class: 'mono', text: String(row.axis) }),
          h('td', { text: row.name || '-' }),
          h('td', { class: 'muted', text: row.kind }),
          h('td', {}, h('span', { class: `chip chip-${row.servoTone}`, text: row.servo })),
          h('td', { class: 'mono', text: row.position === null ? '-' : signedDeg(row.position, 2) }),
          h('td', { class: `mono ${row.load !== null && row.load >= 100 ? 'tone-text-bad' : ''}`, text: row.load === null ? '-' : `${Math.round(row.load)}%` }),
          h('td', {}, h('span', { class: `chip chip-${row.absoluteTone}`, title: row.absoluteProblem, text: row.absolute })),
          h('td', { class: 'muted', text: row.comm }),
          h('td', {}, h('button', { class: 'btn btn-mini', type: 'button', 'aria-label': `${row.axis}번 자세히`, onclick: () => { ui.selected = row.axis; changed(); } }, '⋯')))))))
        : h('p', { class: 'muted', text: '설정된 모터가 없습니다 · 「모터 다시 검색」 으로 찾으세요' })),
    selected ? detailCard(state, changed, selected) : null,
    h('div', { class: 'apply-bar' },
      h('div', { class: 'grow' },
        h('span', { text: changes.length ? `저장 안 한 변경 ${changes.length} · ${changes.slice(0, 3).join(' · ')}${changes.length > 3 ? ' …' : ''}` : '저장됨' }),
        problems.length ? h('p', { class: 'tone-text-warn small', text: problems[0] }) : null),
      h('button', { class: 'btn', type: 'button', disabled: Boolean(ui.busy) || !changes.length, onclick: () => { ui.draft = { ...ui.draft, motors: clone(ui.saved) }; changed(); } }, '되돌리기'),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: Boolean(ui.busy), onclick: () => save(state, changed) }, ui.busy === '저장 중' ? '저장 중…' : '저장'),
      h('button', { class: 'btn btn-warn', type: 'button', disabled: Boolean(ui.busy), onclick: () => save(state, changed, { apply: true }) }, '저장 · 장비에 적용 · 모터 재시작…')),
  ];
}
