/** UI v2 · 모터·드라이브 · 지금 상태 · 설정 고치기 · 드라이브 정비 · 앱솔루트 (설계안 2026-10-09)
 *
 * 저장은 파일만 · 드라이브에 들어가는 것은 「장비에 적용 · 모터 재시작」 뒤(§6-221) · 저장 버튼은 늘 눌린다(§6-203).
 * 서보 켜기/끄기 · 알람 리셋은 운전 모드와 무관(서버 run_mode_gate) · 끄기·재부팅·정비는 확인 창.
 * 「…」 이 붙은 버튼은 확인 창이 뜬다 · 빨간 글은 위치 기준이 바뀌는 일.
 * 모터 검색 · 결과로 만든 목록은 서버가 제안한다(수정 목록 100 · scan_proposal.py) · 화면은 받아서 초안으로 ·
 * 검색한 통로만 바뀌고 · 짝지은 모터는 이름·드라이브 값을 지킨다 · 뺀 모터·바뀐 번호는 알림으로 · 저장해야 남는다.
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import * as act from '../actions.js';
import { isRevisionConflict } from '../mapping_model.js';
import { threeWayMerge } from '../merge_model.js';
import { confirmConflicts } from '../conflict_dialog.js';
import { EDIT_FIELDS, absoluteJobText, absoluteSummary, gainText, gainWarnings, getField, motorChanges, motorProblems, motorRows, setField } from '../motors_model.js';
import { signedDeg } from '../play_model.js';
import { minasBaseCard } from './minas_base.js';
import { autoTuneAll, gainField, saveAll } from './drive_gains.js';

const ui = { revision: '', saved: null, draft: null, selected: null, job: null, busy: '', error: '', scan: null };
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
      // 원본 파일 그대로 · 소프트 리밋(lower/upper) 등 화면 칸에 없는 값도 보이게 · 사용자 2026-10-13
      ui.content = String(data?.content || '');
      ui.configFile = String(data?.config_file || '');
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
      if (ui.job?.state !== 'running' || !/^#\/(maintain-motors|mapping)/.test(location.hash)) { clearInterval(jobTimer); jobTimer = null; }
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

async function servoAll(rows, action, state, changed) {
  if (ui.busy) return;
  ui.busy = action === 'on' ? '모든 서보 켜기' : '모든 서보 끄기';
  changed();
  try { await act.servoAll(rows, action); } finally {
    ui.busy = '';
    await loadMotors(state, changed);
  }
}

/** 서보 한 줄 · 「켜짐 3/5」 + 모두 켜기·끄기 (사용자 2026-10-12) */
function servoAllBar(rows, state, changed) {
  const detected = rows.filter((r) => r.detected);
  if (!detected.length) return null;
  const on = detected.filter((r) => r.servoOn).length;
  const tone = on === detected.length ? 'ok' : on === 0 ? 'warn' : 'info';
  return h('div', { class: `blocker ${tone === 'ok' ? 'ok' : ''}` }, dot(tone),
    h('span', { class: 'grow', text: `서보 켜짐 ${on}/${detected.length}${on < detected.length ? ' · 꺼진 모터는 재생·수동 조작이 안 됩니다' : ''}` }),
    h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy) || on === detected.length,
      title: '감지된 모든 모터의 서보를 켭니다 · 알람이 있는 모터는 먼저 오류 초기화', onclick: () => servoAll(rows, 'on', state, changed) }, '모든 서보 켜기'),
    h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy) || on === 0,
      title: '감지된 모든 모터의 서보를 끕니다 · 브레이크 없는 모터는 처질 수 있습니다', onclick: () => servoAll(rows, 'off', state, changed) }, '모든 서보 끄기'));
}

async function maintenance(row, action, state, changed) {
  const texts = {
    eeprom_save: { title: `${row.axis}번 드라이브에 저장 (EEPROM)`, body: '드라이브의 현재 설정값을 전원을 꺼도 유지되도록 저장합니다. 모터 프로그램을 잠시 정지했다가 다시 시작하며(몇 초), 그동안 서보 토크가 해제됩니다. 브레이크가 없는 모터는 처질 수 있습니다.\n저장하는 동안(최대 10초) 드라이브 전원을 끄지 마세요.', tone: 'warning', label: '저장' },
    absolute_clear: { title: `${row.axis}번 다회전 클리어`, body: '엔코더의 회전 수 기록을 0으로 초기화합니다. 위치 기준이 바뀝니다.\n서보가 꺼져 있어야 합니다. 끝나면 드라이브 전원을 껐다 켜세요. 위치 값이 바뀌므로 기준점을 다시 캡처해야 하며, 그 전에는 재생하지 마세요.', tone: 'danger', label: '클리어' },
  }[action];
  if (action === 'absolute_clear' && row.servoOn) { toast('서보를 먼저 끄세요. 다회전 클리어는 서보가 꺼진 상태에서만 할 수 있습니다.', 'warn'); return; }
  const ok = await confirmBox({ ...texts, confirmLabel: texts.label });
  if (!ok) return;
  const result = await run(`${row.axis}번 드라이브 관리`, () => api('POST', '/api/motor-config/drive-maintenance', {
    body: { action, axis: row.axis, confirmed: true }, timeoutMs: 60000,
  }), state, changed);
  if (result?.power_cycle_required) {
    await confirmBox({ title: '드라이브 전원을 껐다 켜야 합니다', body: '드라이브 전원을 껐다 켜야 바뀐 값이 적용됩니다. 전원을 켠 뒤 기준점을 다시 캡처하세요.', confirmLabel: '확인' });
  }
}

/** EEPROM Alias 쓰기 · 드라이브가 같은 Alias 를 쓰면 어느 드라이브인지 가릴 수 없어 저장이 거절된다 (2026-10-12)
 *  서버 /api/motors/ethercat-alias 가 검색 때 본 값(Vendor · Product · Serial · 지금 Alias)과 실제가 같을 때만 쓴다 */
async function writeAlias(row, motor, state, changed) {
  const identity = motor.identity || {};
  const current = identity.ethercat_alias;
  const input = document.getElementById(`alias-${row.axis}`);
  const next = Number(input?.value);
  if (!Number.isInteger(next) || next < 0 || next > 65535) { toast('Alias 는 0~65535 사이의 정수여야 합니다', 'bad'); return; }
  if (identity.serial_number === undefined || identity.vendor_id === undefined) { toast('검색 정보가 없습니다. 「전체 검색」을 먼저 하세요', 'bad'); return; }
  const ok = await confirmBox({
    title: `${row.axis}번 드라이브 EEPROM Alias 쓰기`,
    body: `Master ${row.masterIndex} · Slave ${row.slavePosition} · 지금 Alias ${current ?? '-'} → ${next}\n`
      + '드라이브 EEPROM 에 저장됩니다. 다른 드라이브와 같은 값은 쓸 수 없습니다(0 은 케이블 순서로 찾습니다).\n'
      + '쓴 뒤 「전체 검색」으로 새 값이 보이는지 확인하고 「저장 후 장비에 적용」을 하세요. 예전 값 그대로면 드라이브 제어 전원을 껐다 켠 뒤 다시 검색하세요.',
    confirmLabel: '쓰기', tone: 'warning',
  });
  if (!ok) return;
  await run(`${row.axis}번 Alias 쓰기`, () => api('POST', '/api/motors/ethercat-alias', {
    body: {
      confirmed: true, master_index: row.masterIndex, slave_position: row.slavePosition, new_alias: next,
      expected: { ethercat_alias: current, vendor_id: identity.vendor_id, product_code: identity.product_code ?? identity.product_id, serial_number: identity.serial_number },
    },
    timeoutMs: 15000,
  }), state, changed);
}

/** 그 모터 설정 칸을 열고 그 자리로 내려간다 */
/** 줄을 누르면 그 모터 설정이 표 아래에 열린다 · 화면은 그 자리 그대로(자동으로 내려가지 않음 · 사용자 2026-10-13) */
function openDetail(axis, changed) {
  ui.selected = axis;
  changed();
}

async function absoluteSetup(scope, row, state, changed) {
  const body = scope === 'all' ? { scope: 'all' } : { scope: 'one', master_index: row.masterIndex, slave_position: row.slavePosition };
  let preview;
  try {
    preview = await api('POST', '/api/motor-config/absolute-setup/preview', { body });
  } catch (error) { toast(error.message || String(error), 'bad'); return; }
  const targets = (preview?.targets || []).map((t) => `· ${t.label || t.axis}${t.problem ? ` (${t.problem})` : ''}`);
  const skipped = (preview?.skipped || []).map((t) => `· ${t.label || t.axis} · ${t.reason || '이미 정상'}`);
  if (!targets.length) { toast(preview?.message || '설정할 모터가 없습니다. 모두 이미 앱솔루트 방식입니다.', 'ok'); return; }
  const ok = await confirmBox({
    title: '앱솔루트 설정',
    body: `대상\n${targets.join('\n')}${skipped.length ? `\n\n건너뜀(이미 정상 · 다시 하면 기준점이 사라짐)\n${skipped.join('\n')}` : ''}\n\n${(preview?.steps || []).map((s, i) => `${i + 1}. ${s.label || s}`).join('\n')}\n\n대상 모터의 서보를 끄고 모터 프로그램을 두 번 잠시 정지합니다. 중간에 드라이브 전원을 두 번 껐다 켜야 합니다(화면에 안내가 나옵니다). 끝나면 위치 값이 바뀌므로 기준점을 다시 캡처해야 합니다.`,
    confirmLabel: '시작', tone: 'danger',
  });
  if (!ok) return;
  await run('앱솔루트 설정', () => api('POST', '/api/motor-config/absolute-setup', { body: { ...body, confirmed: true }, timeoutMs: 20000 }), state, changed);
}

/* ---------- 모터 검색 · 서버 제안 · 수정 목록 100 ---------- */

const SCAN_KINDS = {
  all: { label: '전체', path: '/api/motors/scan' },
  ac: { label: 'AC 서보', path: '/api/motors/scan/ac-servo' },
  dxl: { label: '다이나믹셀', path: '/api/motors/scan/dynamixel' },
};

async function scan(kind, state, changed) {
  const spec = SCAN_KINDS[kind];
  const ok = await confirmBox({
    title: `모터 검색 · ${spec.label}`,
    body: `${kind === 'dxl' ? '다이나믹셀' : kind === 'ac' ? 'AC 서보(EtherCAT)' : 'AC 서보와 다이나믹셀'} 모터를 검색합니다(수십 초 걸리며, 실패하면 몇 번 다시 시도합니다).\n`
      + '검색하는 동안 모터 프로그램이 잠시 정지했다가 다시 시작됩니다. 그동안 서보 토크가 해제됩니다. 브레이크 보드가 연결된 모터는 브레이크가 잡아 주지만, 브레이크가 없는 모터는 처질 수 있으니 기구를 받치고, 움직이는 모터가 없을 때 진행하세요.\n\n'
      + `검색 결과는 저장하기 전까지 화면에만 표시됩니다. ${kind === 'all' ? '' : '검색하지 않은 종류의 모터는 그대로 둡니다. '}모터 이름과 드라이브 설정값은 유지됩니다.`
      + (dirty() ? '\n\n저장하지 않은 변경 내용은 검색 결과로 대체됩니다.' : ''),
    confirmLabel: '검색', tone: 'warning',
  });
  if (!ok) return;
  ui.busy = 'scan';
  ui.scan = { kind, running: true, step: '검색 시작', notes: [], message: '' };
  changed();
  const poll = setInterval(async () => {
    try {
      const progress = (await api('GET', '/api/motors/scan/progress', { timeoutMs: 3000 }))?.progress || {};
      const last = (progress.events || []).slice(-1)[0];
      if (last?.message && ui.scan) { ui.scan.step = String(last.message); changed(); }
    } catch { /* 다음에 */ }
  }, 1000);
  try {
    const result = await fetch(spec.path, { method: 'POST', headers: { Accept: 'application/json' } }).then((r) => r.json());
    const proposal = result?.scan?.proposed_registry;
    ui.scan = {
      kind, running: false, success: result?.success === true, partial: result?.partial === true,
      message: String(result?.message || ''), notes: Array.isArray(proposal?.notes) ? proposal.notes : [],
      summary: proposal?.summary || null,
    };
    if (proposal && Array.isArray(proposal.registry?.motors)) {
      // 제안을 초안으로 · 저장해야 파일에 남는다
      ui.draft = { ...(ui.draft || {}), motors: clone(proposal.registry.motors) };
      if (!ui.draft.motors.some((m) => Number(m.axis) === ui.selected)) ui.selected = ui.draft.motors[0] ? Number(ui.draft.motors[0].axis) : null;
    }
  } catch (error) {
    ui.scan = { kind, running: false, success: false, message: error.message || String(error), notes: [] };
  } finally {
    clearInterval(poll);
    ui.busy = '';
    changed();
  }
}

async function cancelScan(changed) {
  try { toast((await api('POST', '/api/motors/scan/cancel'))?.message || '다음 종류의 모터를 검색하기 전에 중지합니다', 'ok'); } catch (error) { toast(error.message || String(error), 'bad'); }
  changed();
}

function scanBox(changed) {
  const s = ui.scan;
  if (!s) return null;
  if (s.running) {
    return h('div', { class: 'busy-line', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }),
      h('span', { class: 'grow', text: `모터 검색 중 · ${SCAN_KINDS[s.kind].label} · ${s.step}` }),
      h('button', { class: 'btn btn-mini', type: 'button', onclick: () => cancelScan(changed) }, '중지'));
  }
  const tone = s.success ? 'ok' : s.partial ? 'warn' : 'bad';
  const sum = s.summary;
  return h('div', { class: `blocker ${tone === 'ok' ? 'ok' : tone === 'bad' ? 'bad' : ''}` }, dot(tone),
    h('div', { class: 'grow' },
      h('strong', { text: `검색 ${s.success ? '완료' : s.partial ? '일부 완료' : '실패'} · ${SCAN_KINDS[s.kind].label}${sum ? ` · 일치 ${sum.matched} · 추가 ${sum.added} · 삭제 ${sum.removed}${sum.kept ? ` · 유지 ${sum.kept}` : ''}` : ''}` }),
      s.message ? h('p', { class: 'small', text: s.message }) : null,
      s.notes.length ? h('ul', { class: 'list small' }, s.notes.map((note) => h('li', { text: note }))) : null,
      sum ? h('p', { class: 'small muted', text: '아직 저장하지 않았습니다. 이름을 확인한 뒤 아래 「저장 후 장비에 적용」을 누르세요.' }) : null),
    h('button', { class: 'btn btn-mini', type: 'button', onclick: () => { ui.scan = null; changed(); } }, '닫기'));
}

/** 모터 설정 파일만 저장 · 검사·확인창·장비 적용은 motor_setup.js 가 한 번에 · 실패는 throw */
export async function saveMotors(state, changed) {
  ui.busy = '저장 중';
  changed();
  try {
    const put = () => api('PUT', '/api/motor-config', { body: { registry: ui.draft, base_revision: ui.revision }, timeoutMs: 20000 });
    let result;
    try {
      result = await put();
    } catch (error) {
      // 「화면을 불러온 뒤 변경됐습니다」 · 최신 파일을 다시 받아 이 화면에서 고친 칸만 얹고 저장한다(사용자 2026-10-12) ·
      // 운전 한계(하한·상한)는 서버가 저장할 때마다 조인트 매핑에서 다시 계산하므로 여기서 다루지 않는다 ·
      // 다른 곳도 같은 칸을 다르게 바꿨을 때만 묻는다
      if (!isRevisionConflict(error.message)) throw error;
      const latest = await api('GET', '/api/motor-config');
      const registry = latest?.registry || { motors: [] };
      const merged = threeWayMerge(ui.saved, ui.draft.motors, registry.motors || [], (m) => m.id);
      if (merged.conflicts.length && !(await confirmConflicts(merged.conflicts, (key) => {
        const m = (ui.draft.motors || []).find((row) => row.id === key);
        return m ? `${m.axis}번 ${m.name || ''}`.trim() : key;
      }))) return null;
      ui.draft = { ...registry, motors: merged.records };
      ui.revision = String(latest?.config_revision || '');
      result = await put();
    }
    await loadMotors(state, changed, { force: true });
    return String(result?.message || '모터 설정을 저장했습니다');
  } finally {
    ui.busy = '';
    changed();
  }
}

export function motorsDraft() {
  if (!ui.draft) return { ready: false, changes: [], problems: [], busy: ui.busy };
  return { ready: true, changes: motorChanges(ui.saved, ui.draft.motors), problems: motorProblems(ui.draft.motors), busy: ui.busy };
}

export function revertMotors() {
  if (ui.draft) ui.draft = { ...ui.draft, motors: clone(ui.saved) };
}

/* ---------- 그리기 ---------- */

function detailCard(state, changed, row) {
  const motor = ui.draft?.motors?.find((m) => Number(m.axis) === row.axis);
  if (!motor) return null;
  const busy = Boolean(ui.busy);
  const input = (field) => {
    if (field.ac && !row.ac) return null;
    const value = getField(motor, field.key);
    return h('label', { class: 'field' }, h('span', { class: 'field-label', text: `${field.label}${field.unit ? ` (${field.unit})` : ''}` }),
      h('input', { class: `input${field.top ? '' : ' mono'}`, type: field.top ? 'text' : 'number', step: 'any', value: value ?? '',
        placeholder: field.top ? '' : (field.blank || '비워 두면 드라이브 값 유지'),
        oninput: (e) => setField(motor, field.key, field.top ? e.target.value : (e.target.value === '' ? null : Number(e.target.value))),
        onchange: () => changed() }));
  };
  return h('section', { class: 'card', id: 'motor-detail', 'aria-label': `${row.axis}번 설정` },
    h('div', { class: 'card-head' }, h('h2', { text: `${row.axis}번 · ${row.name || '-'}` }), h('span', { class: 'muted small mono wrap-text', text: row.id })),
    h('div', { class: 'row form-row' }, EDIT_FIELDS.map(input)),
    row.ac ? h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: Number(motor.config?.overload_monitor) === 1,
      onchange: (e) => { setField(motor, 'overload_monitor', e.target.checked ? 1 : 0); changed(); } }),
    '과부하율 읽기 (드라이브 소프트웨어 Ver1.03 이상 필요 · 낮은 버전에서 켜면 모터 프로그램이 시작되지 않음)') : null,
    h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: motor.config?.schedule_end_servo_off === true,
      onchange: (e) => { setField(motor, 'schedule_end_servo_off', e.target.checked); changed(); } }), '운영 시간이 끝나면 서보 끄기'),
    // 드라이브 게인 · 잠금 · 재시작 없이 쓰기 · 수정 목록 108 (다)
    gainField(row, changed, () => loadMotors(state, changed, { force: true })),
    h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '드라이브 관리' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn btn-mini', type: 'button', disabled: busy, onclick: () => servo(row, 'reset', state, changed) }, row.ac ? `오류 초기화${row.fault ? '' : ' (알람 없음)'}` : '재부팅'),
        row.servoOn
          ? h('button', { class: 'btn btn-mini', type: 'button', disabled: busy, onclick: () => servo(row, 'off', state, changed) }, row.ac ? '서보 끄기' : '토크 끄기')
          : h('button', { class: 'btn btn-mini', type: 'button', disabled: busy || row.fault || !row.detected, onclick: () => servo(row, 'on', state, changed) }, row.ac ? '서보 켜기' : '토크 켜기'),
        row.ac ? h('button', { class: 'btn btn-mini', type: 'button', disabled: busy, onclick: () => maintenance(row, 'eeprom_save', state, changed) }, '드라이브에 저장 (EEPROM)') : null,
        row.ac ? h('button', { class: 'btn btn-mini', type: 'button', disabled: busy || row.absolute === '정상', title: row.absolute === '정상' ? '이미 앱솔루트 방식입니다. 다시 설정하면 기준점이 사라집니다.' : '',
          onclick: () => absoluteSetup('one', row, state, changed) }, row.absolute === '정상' ? '앱솔루트 정상' : '앱솔루트 설정') : null,
        row.ac ? h('button', { class: 'btn btn-mini danger-text', type: 'button', disabled: busy, onclick: () => maintenance(row, 'absolute_clear', state, changed) }, '다회전 클리어') : null),
      h('p', { class: 'muted small', text: '빨간 글씨 버튼은 위치 기준을 바꿉니다. 누르면 확인 창이 먼저 뜹니다.' })),
    row.ac ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: `EtherCAT Alias · 지금 ${motor.identity?.ethercat_alias ?? '-'} · Slave ${Number.isFinite(row.slavePosition) ? row.slavePosition : '-'}` }),
      h('div', { class: 'row' },
        h('input', { id: `alias-${row.axis}`, class: 'input mono num-input', type: 'number', min: '0', max: '65535', step: '1',
          value: String(motor.identity?.ethercat_alias ?? ''), 'aria-label': `${row.axis}번 새 Alias` }),
        h('button', { class: 'btn btn-mini', type: 'button', disabled: busy, onclick: () => writeAlias(row, motor, state, changed) }, 'Alias 쓰기')),
      h('p', { class: 'muted small', text: '드라이브마다 다른 값이어야 합니다(0은 겹쳐도 되고 케이블 순서로 찾습니다). 쓴 뒤 「전체 검색」으로 새 값이 보이는지 확인하세요. 예전 값 그대로면 드라이브 제어 전원을 껐다 켠 뒤 다시 검색하세요.' })) : null,
    h('details', { class: 'raw' }, h('summary', { text: '원본 (드라이브 정보)' }),
      h('pre', { class: 'doc-code small' }, h('code', { text: JSON.stringify({ identity: motor.identity, profile: motor.profile, config: motor.config }, null, 2) }))));
}

/** ① 구획 머리 오른쪽 · 다시 검색 */
export function motorsActions(state, changed) {
  return h('div', { class: 'segmented', role: 'group', 'aria-label': '모터 검색' },
    Object.entries(SCAN_KINDS).map(([kind, spec]) => h('button', { class: 'seg', type: 'button', disabled: Boolean(ui.busy),
      title: `${spec.label} 다시 검색 · 결과는 저장하기 전까지 화면에만 표시됩니다`, onclick: () => scan(kind, state, changed) }, `${spec.label} 검색`)));
}

/** ① 모터·드라이브 구획 본문 · 머리와 저장 칸은 motor_setup.js */
export function motorsBody(state, changed) {
  if (!ui.draft) return h('p', { class: ui.error ? 'tone-text-bad' : 'muted', text: ui.error || '불러오는 중…' });
  const rows = motorRows(ui.draft, state.snap);
  const abs = absoluteSummary(rows);
  const faults = rows.filter((r) => r.fault);
  const selected = rows.find((r) => r.axis === ui.selected) || rows[0];
  const jobText = absoluteJobText(ui.job);
  const runtime = state.snap?.service_management?.runtime || {};
  return [
    scanBox(changed),
    ui.message ? h('p', { class: 'muted', text: ui.message }) : null,
    runtime.motor_manager_start_block_reason || (runtime.phase && runtime.phase !== 'ready')
      ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: `모터 프로그램 · ${runtime.motor_manager_start_block_reason || runtime.message || runtime.phase}` })) : null,
    h('div', { class: `blocker ${abs.allOk ? 'ok' : ''}` }, dot(abs.allOk ? 'ok' : 'warn'),
      h('span', { class: 'grow', text: !abs.total ? 'AC 서보 없음'
        : abs.allOk ? `앱솔루트 ${abs.ok}/${abs.total} 정상 · 전원을 껐다 켜도 위치가 유지됩니다`
          : !abs.needsSetup ? `앱솔루트 ${abs.ok}/${abs.total} 정상 · ${abs.waiting ? '드라이브 응답을 기다리며 다시 읽는 중' : '확인 중'} · 끝날 때까지 모터 동작이 차단됩니다 (앱솔루트 설정은 필요 없음)`
            : `앱솔루트 ${abs.ok}/${abs.total} 정상 · 정상이 아니면 모든 모터 동작이 차단됩니다` }),
      abs.needsSetup ? h('button', { class: 'btn btn-warn', type: 'button', disabled: Boolean(ui.busy) || ui.job?.state === 'running', onclick: () => absoluteSetup('all', null, state, changed) }, '앱솔루트 설정 (전체)') : null),
    jobText ? h('div', { class: `blocker ${ui.job.state === 'failed' ? 'bad' : ''}` }, dot(ui.job.state === 'failed' ? 'bad' : 'info'),
      h('span', { class: 'grow', text: jobText }),
      ui.job.state === 'running' ? h('button', { class: 'btn', type: 'button', onclick: () => run('취소', () => api('POST', '/api/motor-config/absolute-setup/cancel'), state, changed) }, '취소') : null) : null,
    faults.map((row) => h('div', { class: 'issue issue-bad' }, dot('bad'),
      h('div', { class: 'issue-text' }, h('strong', { text: `${row.axis}번 · ${row.name} · ${row.error || '알람'}` }),
        h('span', { text: '기구에 걸린 것이 없는지 확인한 뒤 오류를 초기화하고 서보를 켜세요' })),
      h('button', { class: 'btn btn-danger-soft', type: 'button', disabled: Boolean(ui.busy), onclick: () => servo(row, 'reset', state, changed) }, row.ac ? '오류 초기화' : '재부팅'))),
    servoAllBar(rows, state, changed),
    // 게인 알림 · 막지 않음 · 108 (나) · 자동조정 꺼짐이면 「모두 켜기」 · 108 (다)
    gainWarnings(rows).map((text) => h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text }),
      text.startsWith('자동조정 꺼짐') ? h('button', { class: 'btn btn-mini', type: 'button', disabled: Boolean(ui.busy),
        onclick: () => autoTuneAll(rows, changed, () => loadMotors(state, changed, { force: true })) }, '자동조정 켜기') : null)),
    h('section', { class: 'card', 'aria-label': '모터' },
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table files-table' },
        h('thead', {}, h('tr', {}, ['번호', '이름', '종류 · 모델', '서보', '위치 (모터°)', '과부하율', '앱솔루트', '게인', '통신'].map((text) => h('th', { scope: 'col', text })))),
        // 줄 어디를 눌러도 그 모터 설정이 아래에 열린다 · 「⋯」 만으로는 무엇을 하는지 안 보였다 (2026-10-12)
        h('tbody', {}, rows.map((row) => h('tr', { class: `pick-row${row.axis === selected?.axis ? ' selected' : ''}`, title: '누르면 이 모터 설정이 아래에 열립니다', onclick: () => openDetail(row.axis, changed) },
          h('td', { class: 'mono', text: String(row.axis) }),
          h('td', { text: row.name || '-' }),
          h('td', { class: 'muted', text: row.kind }),
          h('td', {}, h('span', { class: `chip chip-${row.servoTone}`, text: row.servo })),
          h('td', { class: 'mono', text: row.position === null ? '-' : signedDeg(row.position, 2) }),
          h('td', { class: `mono ${row.load !== null && row.load >= 100 ? 'tone-text-bad' : ''}`, text: row.load === null ? '-' : `${Math.round(row.load)}%` }),
          h('td', {}, h('span', { class: `chip chip-${row.absoluteTone}`, title: row.absoluteProblem, text: row.absolute })),
          // 드라이브에 저장된 게인 · 마우스를 올리면 매뉴얼 번호와 값 · 108
          (() => { const g = row.ac ? gainText(row.gains) : null; return h('td', { class: 'small', title: g?.hint || '' },
            g ? h('span', { class: `chip chip-${g.tone}`, text: g.text }) : '-'); })(),
          h('td', { class: 'muted', text: row.comm }))))))
        : h('p', { class: 'muted', text: '설정된 모터가 없습니다. 위의 「전체 검색」으로 모터를 찾으세요.' })),
    selected ? detailCard(state, changed, selected) : null,
    // 모든 MINAS 축 공통 · 잠금 · 수정 목록 114
    minasBaseCard(changed, {
      hasAc: rows.some((r) => r.ac),
      acAxes: rows.filter((r) => r.ac && r.detected).map((r) => r.axis),
      onSaveAll: async () => {
        const axes = rows.filter((r) => r.ac && r.detected).map((r) => r.axis);
        const ok = await confirmBox({
          title: `모든 축 드라이브에 저장 (EEPROM) · ${axes.length}대`,
          body: '지금 드라이브에 들어 있는 값(공통 설정 · 게인 등)을 전원을 꺼도 남게 저장합니다.\n'
            + '모터 프로그램이 한 번 멈췄다 다시 켜지고, 그동안 서보 토크가 풀립니다. 브레이크가 없는 모터는 처질 수 있습니다.\n'
            + '저장하는 동안(최대 10초씩) 드라이브 전원을 끄지 마세요.',
          confirmLabel: '저장', tone: 'warning',
        });
        if (ok) await saveAll(axes, changed, () => loadMotors(state, changed, { force: true }));
      },
    }),
    // 모터 설정 원본 파일(저장된 것) · 이전 UI 「원본 보기」 · 소프트 리밋 lower/upper(모터 deg · 조인트 매핑에서 옴) 등 · 2026-10-13
    ui.content ? h('details', { class: 'raw card' },
      h('summary', { text: `원본 파일 · ${ui.configFile ? ui.configFile.split(/[\\/]/).pop() : '모터 설정'} (저장된 내용 · 소프트 리밋 lower/upper 포함)` }),
      h('p', { class: 'muted small', text: 'lower · upper = 드라이브 소프트 리밋(모터 deg) · 조인트 매핑의 범위를 환산해 저장 때 들어갑니다(여유 2° 는 장비에 넣을 때 더함). 읽기 전용입니다.' }),
      h('pre', { class: 'doc-code small raw-file' }, h('code', { text: ui.content }))) : null,
  ];
}
