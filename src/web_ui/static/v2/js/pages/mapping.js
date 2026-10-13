/** UI v2 · 조인트 매핑 · 애니메이션 조인트 → 이 PC 모터 (설계안 2026-10-09)
 *
 * 범위(최소·최대)가 유일한 한계다 · 저장하면 모터 설정의 운전 한계도 같이 바뀌고,
 * 드라이브 소프트 리밋은 「장비에 적용 · 모터 재시작」 뒤에 바뀐다(86b5c8e).
 * 저장은 서버 판정 그대로 · 다른 화면이 먼저 바꿨으면 한 번 묻는다(§6-243) · 읽기 실패로 초안을 덮지 않는다(§6-237).
 * 재생 목록은 공연 화면 몫 · 여기서 건드리지 않는다(§6-160).
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { toast } from '../dialog.js';
import * as act from '../actions.js';
import {
  INITIAL_MODES, changeSummary, draftProblems, draftToRow, isRevisionConflict, motorForRow, motorRefFor, motorWhere, newRow, previewRow,
  rangeConfirmed, rowToDraft, rowTarget, unconfirmedRows,
} from '../mapping_model.js';
import { signedDeg } from '../play_model.js';
import { motorsDraft } from './motors.js';
import { threeWayMerge } from '../merge_model.js';
import { confirmConflicts } from '../conflict_dialog.js';

/** 「범위 확인」 칸 옆 주의 · 숫자만 넣고 체크하지 않게 (사용자 2026-10-13) */
export const RANGE_NOTE = '범위 확인 유의 · 실제 기계 범위인지 확인한 뒤 체크';

const ui = { fileId: '', revision: '', name: '', saved: [], rows: null, selected: '', validation: null, busy: '', loadError: '', content: '' };
let keySeq = 0;

function withKeys(rows) {
  return rows.map((row) => ({ ...rowToDraft(row), _key: `k${keySeq += 1}` }));
}

function clone(rows) {
  return rows.map((row) => ({ ...row }));
}

function dirty() {
  return ui.rows ? changeSummary(ui.saved, ui.rows).length > 0 : false;
}

export async function loadMapping(state, changed, { force = false } = {}) {
  if (ui.rows && dirty() && !force) { changed(); return; }
  try {
    const list = await api('GET', '/api/motion-mappings');
    const files = Array.isArray(list?.files) ? list.files : [];
    const fileId = files.some((f) => f.id === list?.active_file_id) ? list.active_file_id : (files[0]?.id || '');
    if (!fileId) {
      Object.assign(ui, { fileId: '', revision: '', name: 'motion_axis', saved: [], rows: [], validation: null, loadError: '', content: '' });
      changed();
      return;
    }
    const data = await api('GET', `/api/motion-mappings/${encodeURIComponent(fileId)}`);
    if (!data?.mapping) throw new Error(data?.message || '매핑을 불러오지 못했습니다');
    const rows = withKeys(Array.isArray(data.mapping.mappings) ? data.mapping.mappings : []);
    Object.assign(ui, {
      fileId, revision: String(data.file?.mapping_revision || data.file?.revision || ''), name: String(data.mapping.name || fileId.replace(/\.ya?ml$/, '')),
      saved: clone(rows), rows, validation: data.validation || null, loadError: '', content: String(data.content || ''),
    });
    if (!ui.rows.some((row) => row._key === ui.selected)) ui.selected = ui.rows[0]?._key || '';
  } catch (error) {
    // 읽기 실패로 고치던 것을 덮지 않는다 · 다음 주기에 다시 (§6-237)
    ui.loadError = error.message || String(error);
  }
  changed();
}

/** 이 PC 모터 · 런타임 상태에서 · 번호 → 이름 */
function motorList(state) {
  const motors = Array.isArray(state.snap?.motion_state?.motors) ? state.snap.motion_state.motors : [];
  return motors.map((motor) => ({
    axis: Number(motor.controller_index),
    label: `${motor.controller_index}번 · ${motor.name || motor.display_name || motor.motion_id || ''}`.replace(/ · $/, ''),
    where: motorWhere(motor),
    ref: motorRefFor(motor),
    positionDeg: motor.position_rad === null || motor.position_rad === undefined ? null : Number(motor.position_rad) * 180 / Math.PI,
  }));
}

function captureAllowed(state) {
  const scope = state.snap?.project_scope || {};
  return scope.runtime_matches_selected === true && scope.motor_config_applied === true;
}

/* ---------- 저장 ---------- */

function payload() {
  return {
    file_id: ui.fileId,
    base_mapping_revision: ui.revision,
    mapping: { name: ui.name, mappings: ui.rows.map((row) => { const out = draftToRow(row); delete out._key; return out; }) },
  };
}

/** 조인트 매핑만 저장 · 저장했으면 메시지 · 검사 실패·충돌은 여기서 알리고 null · 장비 적용은 motor_setup.js
 *  충돌(화면을 연 뒤 파일이 바뀜)이면 최신 파일에 이 화면에서 고친 칸만 얹어 다시 저장 · 재생 목록은 서버가 원래 것을 지킨다 */
export async function saveMapping(state, changed, { retried = false } = {}) {
  ui.busy = '저장 중';
  changed();
  try {
    const checked = await api('POST', '/api/motion-mappings/validate', { body: payload() }).catch((error) => ({ success: false, message: error.message, validation: error.data?.validation }));
    if (checked?.validation) ui.validation = checked.validation;
    if (checked?.success === false && checked?.validation?.valid === false) {
      toast(`조인트 매핑 검사 실패 · ${(checked.validation.errors || [])[0] || checked.message}`, 'bad');
      return null;
    }
    const result = await api('POST', '/api/motion-mappings', { body: payload(), timeoutMs: 20000 });
    await loadMapping(state, changed, { force: true });
    return String(result?.message || '조인트 매핑을 저장했습니다');
  } catch (error) {
    if (isRevisionConflict(error.message) && !retried) {
      // 화면을 연 뒤 파일이 바뀌었다(다른 화면 · 수동 조작의 기준점·하한점·상한점 지정 등) · 최신 파일을 받아
      // 이 화면에서 고친 칸만 얹고 다시 저장한다 · 같은 칸을 다르게 바꿨을 때만 묻는다 (사용자 2026-10-12)
      const latest = await latestMapping();
      if (!latest) { toast('최신 조인트 매핑을 받지 못했습니다. 화면을 새로 고친 뒤 다시 저장하세요.', 'bad'); return null; }
      const keyed = latest.rows.map((row, index) => {
        const base = ui.saved.find((b) => b.motion_id && b.motion_id === row.motion_id);
        return { ...row, _key: base ? base._key : `latest-${index}` };
      });
      const merged = threeWayMerge(ui.saved, ui.rows, keyed, (row) => row._key);
      if (merged.conflicts.length && !(await confirmConflicts(merged.conflicts, (key) => {
        const row = ui.rows.find((r) => r._key === key) || keyed.find((r) => r._key === key);
        return row?.motion_id || '조인트';
      }))) return null;
      ui.rows = merged.records;
      ui.revision = latest.revision;
      ui.busy = '';
      return saveMapping(state, changed, { retried: true });
    }
    if (error.data?.validation) ui.validation = error.data.validation;
    toast(error.message || String(error), 'bad');
    return null;
  } finally {
    ui.busy = '';
    changed();
  }
}

/** 지금 파일 · 줄(화면 모양)과 버전 */
async function latestMapping() {
  try {
    const data = await api('GET', `/api/motion-mappings/${encodeURIComponent(ui.fileId)}`);
    const rows = Array.isArray(data?.mapping?.mappings) ? data.mapping.mappings.map((row) => rowToDraft(row)) : null;
    if (!rows) return null;
    return { rows, revision: String(data?.file?.mapping_revision || data?.file?.revision || '') };
  } catch {
    return null;
  }
}

export function mappingDraft() {
  if (!ui.rows) return { ready: false, changes: [], problems: [], busy: ui.busy };
  const changes = changeSummary(ui.saved, ui.rows);
  // 매핑을 고쳤을 때만 매핑 검사로 저장을 막는다 · 처음 연결(조인트 0개 · 안 고침)에도 모터 설정만 저장·적용되게 ·
  // 그래야 모터 프로그램이 켜지고 「인식 모터 자동 생성」 이 된다 · 수정 목록 118 · 고친 매핑(줄을 다 지움 등)은 그대로 막는다
  return { ready: true, changes, problems: changes.length ? draftProblems(ui.rows) : [], busy: ui.busy };
}

export function revertMapping() {
  if (ui.rows) ui.rows = clone(ui.saved);
}

/* ---------- 표 ---------- */

function numberInput(row, key, changed, attrs = {}) {
  const value = row[key];
  return h('input', {
    class: 'input input-num mono', type: 'number', step: 'any', value: value === null || value === undefined ? '' : String(value),
    'aria-label': attrs.label || key, placeholder: attrs.placeholder || '',
    oninput: (e) => { row[key] = e.target.value === '' ? null : Number(e.target.value); },
    onchange: () => { attrs.after?.(row); changed(); },
  });
}

function rowStatus(row) {
  const status = ui.validation?.rows?.[row.motion_id];
  if (!status) return { tone: 'idle', text: '-' };
  const tone = status.status === 'error' ? 'bad' : status.status === 'warning' ? 'warn' : 'ok';
  return { tone, text: (status.messages || [])[0] || (tone === 'ok' ? '정상' : status.status) };
}

function table(state, changed) {
  const motors = motorList(state);
  const canCapture = captureAllowed(state);
  const motorOptions = (row) => {
    const found = motorForRow(row, motors);
    const unknown = !found && (row.motor_ref || row.motor_axis !== null);
    return [
      h('option', { value: '', selected: !found && !unknown }, '없음'),
      unknown ? h('option', { value: 'keep', selected: true }, `${row.motor_axis !== null ? `${row.motor_axis}번` : row.motor_ref} (인식 안 됨)`) : null,
      motors.map((m) => h('option', { value: String(m.axis), selected: found === m }, `${m.label} (${m.where})`)),
    ];
  };
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table mapping-table' },
    h('thead', {}, h('tr', {}, ['사용', '조인트', '모터', '감속·기어비', '방향 반전', '기준점 (모터°)', '범위 (조인트°)', '범위 확인', '최대 속도 · 가속', '초기 위치', '상태', ''].map((text) => h('th', { scope: 'col', text })))),
    h('tbody', {}, ui.rows.map((row, index) => {
      const status = rowStatus(row);
      const motor = motorForRow(row, motors);
      return h('tr', { class: `${row._key === ui.selected ? 'selected' : ''}${row.enabled ? '' : ' muted-row'}`, onclick: (e) => {
        if (ui.selected !== row._key && !e.target.closest('input, select, button')) { ui.selected = row._key; changed(); }
      } },
      h('td', {}, h('input', { type: 'checkbox', checked: row.enabled, 'aria-label': `${index + 1}번 줄 사용`, onchange: (e) => { row.enabled = e.target.checked; changed(); } })),
      h('td', {}, h('input', { class: 'input mono name-input', value: row.motion_id, placeholder: 'Blender 본 이름', 'aria-label': `${index + 1}번 줄 조인트 이름`,
        onfocus: () => { ui.selected = row._key; },
        oninput: (e) => { row.motion_id = e.target.value; }, onchange: () => changed() })),
      h('td', {}, h('select', { class: 'select select-sm motor-select', 'aria-label': `${index + 1}번 줄 모터`, title: motor ? `${motor.label} (${motor.where})` : '',
        onchange: (e) => {
          const value = e.target.value;
          if (value === 'keep') return;
          const motor = motors.find((m) => String(m.axis) === value);
          // 번호와 고유 이름을 같이 · 번호가 바뀌어도 같은 드라이브를 가리키게
          row.motor_axis = motor ? motor.axis : null;
          row.motor_ref = motor ? motor.ref : '';
          changed();
        } }, motorOptions(row))),
      h('td', {}, numberInput(row, 'gear_ratio', changed, { label: '감속·기어비' })),
      h('td', {}, h('input', { type: 'checkbox', checked: row.invert, 'aria-label': `${index + 1}번 줄 방향 반전`, onchange: (e) => { row.invert = e.target.checked; changed(); } })),
      h('td', {}, h('div', { class: 'cell-row' },
        numberInput(row, 'reference_position_deg', changed, { label: '기준점 모터 deg' }),
        h('button', { class: 'btn btn-mini', type: 'button', disabled: !canCapture || !motor || motor.positionDeg === null,
          // 막힌 이유를 그대로 · 전에는 늘 「장비에 적용」 이라고만 해서 모터를 못 찾은 경우와 갈리지 않았다 (2026-10-12)
          title: !canCapture ? (motorsDraft().problems[0]
            ? `모터 설정을 저장할 수 없어 장비에 적용되지 않았습니다 · ${motorsDraft().problems[0]}`
            : '모터 설정이 아직 장비에 적용되지 않았습니다. 「저장 후 장비에 적용」을 먼저 하세요.')
            : !motor ? '이 줄에 연결된 모터를 찾지 못했습니다. 「모터」 칸을 확인하세요.'
              : motor.positionDeg === null ? '이 모터의 현재 위치를 아직 받지 못했습니다.'
                : '현재 모터 위치를 기준점(조인트 0°)으로 설정합니다. 저장해야 반영됩니다.',
          onclick: () => { row.reference_position_deg = Math.round(motor.positionDeg * 1e4) / 1e4; row.reference_enabled = true; changed(); } }, '캡처'))),
      h('td', {}, h('div', { class: 'cell-row' },
        numberInput(row, 'motion_lower_deg', changed, { label: '최소' }), h('span', { class: 'muted', text: '~' }),
        numberInput(row, 'motion_upper_deg', changed, { label: '최대' }))),
      // 숫자를 넣어도 저절로 체크되지 않는다 · 사람이 직접 (사용자 2026-10-13)
      h('td', { class: row.enabled && !rangeConfirmed(row) ? 'range-unconfirmed' : '' }, h('div', { class: 'cell-row' },
        h('input', { type: 'checkbox', checked: rangeConfirmed(row), 'aria-label': `${index + 1}번 줄 범위 확인`,
          title: '최소·최대가 이 로봇의 실제 기계 범위인지 확인하는 칸입니다. 확인하고 저장하기 전에는 재생, 초기 위치 이동, 수동 조작을 할 수 없습니다. 최소·최대를 입력해도 저절로 체크되지 않습니다. 직접 체크하세요.',
          onchange: (e) => { row.range_confirmed = e.target.checked; changed(); } }),
        h('span', { class: 'small tone-text-warn range-note', text: RANGE_NOTE }))),
      h('td', {}, h('div', { class: 'cell-row' },
        numberInput(row, 'max_velocity_deg_s', changed, { label: '최대 속도 deg/s', placeholder: '없음' }),
        numberInput(row, 'max_acceleration_deg_s2', changed, { label: '최대 가속 deg/s²', placeholder: '없음' }))),
      h('td', {}, h('div', { class: 'cell-row' },
        h('select', { class: 'select select-sm', 'aria-label': '초기 위치', onchange: (e) => {
          row.initial_mode = e.target.value;
          if (row.initial_mode === 'reference') row.initial_motion_position_deg = 0;
          changed();
        } }, INITIAL_MODES.map(([value, label]) => h('option', { value, selected: row.initial_mode === value }, label))),
        row.initial_mode === 'manual' ? numberInput(row, 'initial_motion_position_deg', changed, { label: '지정 값 조인트 deg' }) : null)),
      h('td', { class: 'wrap' }, h('span', { class: `chip chip-${status.tone}`, title: status.text, text: status.text })),
      h('td', {}, h('button', { class: 'btn btn-mini', type: 'button', 'aria-label': `${index + 1}번 줄 삭제`, onclick: () => {
        ui.rows = ui.rows.filter((r) => r !== row);
        if (ui.selected === row._key) ui.selected = ui.rows[0]?._key || '';
        changed();
      } }, '삭제')));
    }))));
}

function previewCard() {
  const row = ui.rows?.find((r) => r._key === ui.selected);
  if (!row) return null;
  const view = previewRow(row);
  const validation = ui.validation;
  return h('section', { class: 'card', 'aria-label': '미리보기' },
    h('div', { class: 'card-head' }, h('h2', { text: `${row.motion_id || '(이름 없음)'} · 미리보기` })),
    h('p', { class: 'mono' }, `조인트 +1° → 모터 ${signedDeg(view.perDegree, 2)}°${row.invert ? ' (반대)' : ''}`),
    h('p', { class: 'mono' }, `범위 ${signedDeg(Number(row.motion_lower_deg))} ~ ${signedDeg(Number(row.motion_upper_deg))}° → 모터 한계 ${signedDeg(view.motorMin)} ~ ${signedDeg(view.motorMax)}°`),
    h('p', { class: 'muted small', text: '저장한 뒤 장비에 적용하면 드라이브 소프트 리밋으로 설정됩니다' }),
    validation ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '검사' }),
      (validation.errors || []).length
        ? h('ul', { class: 'list small' }, validation.errors.map((e) => h('li', { class: 'tone-text-bad', text: e })))
        : h('p', { class: 'small' }, dot('ok'), ' 오류 없음'),
      (validation.warnings || []).length
        ? h('ul', { class: 'list small' }, validation.warnings.map((w) => h('li', { class: 'tone-text-warn', text: w }))) : null) : null);
}

/**
 * 「인식 모터 자동 생성」 툴팁 · 막혔으면 이유 · 수정 목록 118
 * 줄은 지금 돌고 있는 모터 프로그램이 알려 준 모터로 만든다(고유 이름이 실제 드라이브와 맞게) · 그래서 모터 프로그램이 돌아야 한다
 */
export function autoBuildReason(state, motorCount) {
  if (motorCount > 0) return `지금 인식된 모터 ${motorCount}대마다 한 줄씩 만듭니다(이미 줄이 있는 모터는 건너뜀)`;
  const scope = state.snap?.project_scope || {};
  if (!scope.runtime_matches_selected) {
    return '인식된 모터가 없습니다 · 모터 프로그램이 이 프로젝트 설정으로 돌고 있지 않습니다. ① 모터·드라이브에서 「저장 후 장비에 적용」을 먼저 누르세요(조인트 없이도 됩니다).';
  }
  return '인식된 모터가 없습니다 · 모터 프로그램이 모터 상태를 아직 보내지 않았습니다. 잠시 기다리거나 ① 모터·드라이브에서 통신 상태를 확인하세요.';
}

/** ② 구획 머리 오른쪽 · 모터로 자동 생성 · 조인트 더하기 */
export function mappingActions(state, changed) {
  if (!ui.rows) return null;
  const motors = motorList(state);
  const autoBuild = () => {
    const used = new Set(ui.rows.map(rowTarget));
    let added = 0;
    for (const motor of motors) {
      if (ui.rows.some((row) => motorForRow(row, motors) === motor) || used.has(`axis:${motor.axis}`)) continue;
      ui.rows.push({ ...newRow(motor.axis, ''), motor_ref: motor.ref, _key: `k${keySeq += 1}` });
      added += 1;
    }
    toast(added ? `매핑 줄 ${added}개를 추가했습니다(모터마다 한 줄). 조인트 이름(Blender 본 이름)을 입력하세요.` : '모든 모터에 이미 매핑 줄이 있습니다', added ? 'ok' : 'warn');
    changed();
  };
  return [
    h('button', { class: 'btn', type: 'button', disabled: !motors.length, onclick: autoBuild,
      title: autoBuildReason(state, motors.length) }, '인식 모터 자동 생성'),
    h('button', { class: 'btn', type: 'button', onclick: () => {
      const row = { ...newRow(null, ''), _key: `k${keySeq += 1}` };
      ui.rows.push(row);
      ui.selected = row._key;
      changed();
    } }, '+ 조인트'),
  ];
}

/** ② 구획 설명 · 공식과 파일 이름 */
export function mappingNote() {
  return h('p', { class: 'muted small' }, '애니메이션 조인트 값을 모터 값으로 바꿉니다. 모터 = 기준점 + 조인트 × 감속·기어비 × 방향 · 파일 ',
    h('span', { class: 'mono', text: ui.fileId || '(새 파일)' }), ' · ', h('a', { href: '#/pack', text: '로봇 팩과 비교' }));
}

/** ② 조인트 매핑 구획 본문 · 머리와 저장 칸은 motor_setup.js */
export function mappingBody(state, changed) {
  if (!ui.rows) return h('p', { class: ui.loadError ? 'tone-text-bad' : 'muted', text: ui.loadError || '불러오는 중…' });
  return [
    ui.loadError ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: `다시 불러오기 실패 · ${ui.loadError} · 수정 중인 내용은 그대로 남아 있습니다` })) : null,
    unconfirmedRows(ui.rows).length ? h('div', { class: 'blocker bad' }, dot('bad'),
      h('span', { class: 'grow', text: `범위 미확인 · ${unconfirmedRows(ui.rows).map((r) => r.motion_id).join(', ')}. 최소·최대가 실제 기계 범위인지 확인한 뒤 「범위 확인」을 직접 체크하고 저장하세요(숫자만 입력해서는 풀리지 않습니다). 그 전에는 재생, 초기 위치 이동, 수동 조작이 차단됩니다.` })) : null,
    state.snap?.mapping_range_blocker && !unconfirmedRows(ui.rows).length && changeSummary(ui.saved, ui.rows).length
      ? h('p', { class: 'muted small', text: '「범위 확인」을 체크했습니다 · 저장해야 범위 미확인 상태가 해제됩니다' }) : null,
    h('section', { class: 'card', 'aria-label': '조인트' },
      ui.rows.length ? table(state, changed) : h('p', { class: 'muted', text: motorList(state).length
        ? '조인트가 없습니다. 「인식 모터 자동 생성」을 누르세요.'
        : `조인트가 없습니다. ${autoBuildReason(state, 0)}` })),
    previewCard(),
    // 원본 파일 그대로(저장된 것) · 이전 UI 처럼 열어 볼 수 있게 (사용자 2026-10-12)
    ui.content ? h('details', { class: 'raw card' }, h('summary', { text: `원본 파일 · ${ui.fileId || '조인트 매핑'} (저장된 내용)` }),
      h('pre', { class: 'doc-code small raw-file' }, h('code', { text: ui.content }))) : null,
  ];
}
