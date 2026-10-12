/** UI v2 · 조인트 매핑 · 애니메이션 조인트 → 이 PC 모터 (설계안 2026-10-09)
 *
 * 범위(최소·최대)가 유일한 한계다 · 저장하면 모터 설정의 운전 한계도 같이 바뀌고,
 * 드라이브 소프트 리밋은 「장비에 적용 · 모터 재시작」 뒤에 바뀐다(86b5c8e).
 * 저장은 서버 판정 그대로 · 다른 화면이 먼저 바꿨으면 한 번 묻는다(§6-243) · 읽기 실패로 초안을 덮지 않는다(§6-237).
 * 재생 목록은 공연 화면 몫 · 여기서 건드리지 않는다(§6-160).
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import * as act from '../actions.js';
import {
  INITIAL_MODES, changeSummary, draftProblems, draftToRow, isRevisionConflict, motorForRow, motorRefFor, newRow, previewRow, rowToDraft, rowTarget,
} from '../mapping_model.js';
import { signedDeg } from '../play_model.js';

const ui = { fileId: '', revision: '', name: '', saved: [], rows: null, selected: '', validation: null, busy: '', loadError: '' };
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
      Object.assign(ui, { fileId: '', revision: '', name: 'motion_axis', saved: [], rows: [], validation: null, loadError: '' });
      changed();
      return;
    }
    const data = await api('GET', `/api/motion-mappings/${encodeURIComponent(fileId)}`);
    if (!data?.mapping) throw new Error(data?.message || '매핑을 못 읽었습니다');
    const rows = withKeys(Array.isArray(data.mapping.mappings) ? data.mapping.mappings : []);
    Object.assign(ui, {
      fileId, revision: String(data.file?.mapping_revision || data.file?.revision || ''), name: String(data.mapping.name || fileId.replace(/\.ya?ml$/, '')),
      saved: clone(rows), rows, validation: data.validation || null, loadError: '',
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
    type: motor.motor_type === 'dynamixel' ? 'DXL' : 'AC',
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

async function save(state, changed, { apply = false } = {}) {
  const problems = draftProblems(ui.rows);
  if (problems.length) { toast(problems[0], 'bad'); return; }
  if (apply) {
    const go = await act.confirmApplyMotorConfig('조인트 매핑을 저장한 뒤 바로 장비에 적용합니다 · 운전 한계(소프트 리밋)가 새 범위로 바뀝니다.');
    if (!go) return;
  }
  ui.busy = '저장 중';
  changed();
  try {
    const checked = await api('POST', '/api/motion-mappings/validate', { body: payload() }).catch((error) => ({ success: false, message: error.message, validation: error.data?.validation }));
    if (checked?.validation) ui.validation = checked.validation;
    if (checked?.success === false && checked?.validation?.valid === false) {
      toast(`검사 실패 · ${(checked.validation.errors || [])[0] || checked.message}`, 'bad');
      return;
    }
    const result = await api('POST', '/api/motion-mappings', { body: payload(), timeoutMs: 20000 });
    toast(result?.message || '저장했습니다', 'ok');
    await loadMapping(state, changed, { force: true });
    if (apply) await act.applyMotorConfig();
  } catch (error) {
    if (isRevisionConflict(error.message)) {
      const reload = await confirmBox({
        title: '다른 화면에서 먼저 바꿨습니다',
        body: '이 화면을 연 뒤 조인트 매핑이 바뀌었습니다.\n고친 것을 버리고 다시 불러올까요? 「그대로 두기」 를 고르면 고친 것이 남고, 다시 저장할 수 있습니다.',
        confirmLabel: '버리고 다시 불러오기', tone: 'warning',
      });
      if (reload) await loadMapping(state, changed, { force: true });
      else if (error.data?.file?.mapping_revision) ui.revision = error.data.file.mapping_revision;
    } else {
      if (error.data?.validation) ui.validation = error.data.validation;
      toast(error.message || String(error), 'bad');
    }
  } finally {
    ui.busy = '';
    changed();
  }
}

/* ---------- 표 ---------- */

function numberInput(row, key, changed, attrs = {}) {
  const value = row[key];
  return h('input', {
    class: 'input input-num mono', type: 'number', step: 'any', value: value === null || value === undefined ? '' : String(value),
    'aria-label': attrs.label || key, placeholder: attrs.placeholder || '',
    oninput: (e) => { row[key] = e.target.value === '' ? null : Number(e.target.value); },
    onchange: () => changed(),
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
      unknown ? h('option', { value: 'keep', selected: true }, `${row.motor_axis !== null ? `${row.motor_axis}번` : row.motor_ref} (지금 안 보임)`) : null,
      motors.map((m) => h('option', { value: String(m.axis), selected: found === m }, `${m.label} · ${m.type}`)),
    ];
  };
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table mapping-table' },
    h('thead', {}, h('tr', {}, ['사용', '조인트', '모터', '감속·기어비', '방향 반전', '기준점 (모터°)', '범위 (조인트°)', '최대 속도 · 가속', '시작 자세', '상태', ''].map((text) => h('th', { scope: 'col', text })))),
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
      h('td', {}, h('select', { class: 'select select-sm', 'aria-label': `${index + 1}번 줄 모터`,
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
          title: canCapture ? '지금 모터 위치를 기준점(조인트 0°)으로 · 저장해야 남습니다' : '이 프로젝트 모터 설정을 장비에 적용한 뒤 캡처할 수 있습니다',
          onclick: () => { row.reference_position_deg = Math.round(motor.positionDeg * 1e4) / 1e4; row.reference_enabled = true; changed(); } }, '캡처'))),
      h('td', {}, h('div', { class: 'cell-row' },
        numberInput(row, 'motion_lower_deg', changed, { label: '최소' }), h('span', { class: 'muted', text: '~' }), numberInput(row, 'motion_upper_deg', changed, { label: '최대' }))),
      h('td', {}, h('div', { class: 'cell-row' },
        numberInput(row, 'max_velocity_deg_s', changed, { label: '최대 속도 deg/s', placeholder: '없음' }),
        numberInput(row, 'max_acceleration_deg_s2', changed, { label: '최대 가속 deg/s²', placeholder: '없음' }))),
      h('td', {}, h('div', { class: 'cell-row' },
        h('select', { class: 'select select-sm', 'aria-label': '시작 자세', onchange: (e) => {
          row.initial_mode = e.target.value;
          if (row.initial_mode === 'reference') row.initial_motion_position_deg = 0;
          changed();
        } }, INITIAL_MODES.map(([value, label]) => h('option', { value, selected: row.initial_mode === value }, label))),
        row.initial_mode === 'manual' ? numberInput(row, 'initial_motion_position_deg', changed, { label: '지정 값 조인트 deg' }) : null)),
      h('td', { class: 'wrap' }, h('span', { class: `chip chip-${status.tone}`, title: status.text, text: status.text })),
      h('td', {}, h('button', { class: 'btn btn-mini', type: 'button', 'aria-label': `${index + 1}번 줄 빼기`, onclick: () => {
        ui.rows = ui.rows.filter((r) => r !== row);
        if (ui.selected === row._key) ui.selected = ui.rows[0]?._key || '';
        changed();
      } }, '빼기')));
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
    h('p', { class: 'muted small', text: '저장 후 「장비에 적용」 하면 드라이브 소프트 리밋이 됩니다' }),
    validation ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '검사' }),
      (validation.errors || []).length
        ? h('ul', { class: 'list small' }, validation.errors.map((e) => h('li', { class: 'tone-text-bad', text: e })))
        : h('p', { class: 'small' }, dot('ok'), ' 오류 없음'),
      (validation.warnings || []).length
        ? h('ul', { class: 'list small' }, validation.warnings.map((w) => h('li', { class: 'tone-text-warn', text: w }))) : null) : null);
}

export function renderMapping(state, { changed }) {
  if (!ui.rows) {
    return [h('div', { class: 'page-head' }, h('h1', { text: '조인트 매핑' })),
      h('p', { class: ui.loadError ? 'tone-text-bad' : 'muted', text: ui.loadError || '불러오는 중…' })];
  }
  const summary = changeSummary(ui.saved, ui.rows);
  const problems = draftProblems(ui.rows);
  const motors = motorList(state);
  const autoBuild = () => {
    const used = new Set(ui.rows.map(rowTarget));
    let added = 0;
    for (const motor of motors) {
      if (ui.rows.some((row) => motorForRow(row, motors) === motor) || used.has(`axis:${motor.axis}`)) continue;
      ui.rows.push({ ...newRow(motor.axis, ''), motor_ref: motor.ref, _key: `k${keySeq += 1}` });
      added += 1;
    }
    toast(added ? `모터 ${added}개 줄을 더했습니다 · 조인트 이름(Blender 본 이름)을 넣으세요` : '모든 모터에 이미 줄이 있습니다', added ? 'ok' : 'warn');
    changed();
  };
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '조인트 매핑' }),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn', type: 'button', disabled: !motors.length, onclick: autoBuild }, '모터로 자동 만들기'),
      h('button', { class: 'btn', type: 'button', onclick: () => {
        const row = { ...newRow(null, ''), _key: `k${keySeq += 1}` };
        ui.rows.push(row);
        ui.selected = row._key;
        changed();
      } }, '+ 조인트'),
      h('p', { class: 'muted small' }, '애니메이션의 조인트 → 이 PC 모터 · 모터 = 기준점 + 조인트 × 감속비 × 방향 · 파일 ',
        h('span', { class: 'mono', text: ui.fileId || '(새로 만듦)' }), ' · ', h('a', { href: '#/pack', text: '로봇 팩과 비교' }))),
    ui.loadError ? h('div', { class: 'blocker' }, dot('warn'), h('span', { class: 'grow', text: `다시 읽기 실패 · ${ui.loadError} · 고치던 것은 그대로` })) : null,
    h('section', { class: 'card', 'aria-label': '조인트' },
      ui.rows.length ? table(state, changed) : h('p', { class: 'muted', text: '조인트가 없습니다 · 「모터로 자동 만들기」 를 누르세요' })),
    previewCard(),
    h('div', { class: 'apply-bar' },
      h('div', { class: 'grow' },
        h('span', { text: summary.length ? `저장 안 한 변경 ${summary.length} · ${summary.slice(0, 3).join(' · ')}${summary.length > 3 ? ' …' : ''}` : '저장됨' }),
        problems.length ? h('p', { class: 'tone-text-warn small', text: problems[0] }) : null),
      h('button', { class: 'btn', type: 'button', disabled: Boolean(ui.busy) || !summary.length, onclick: () => { ui.rows = clone(ui.saved); changed(); } }, '되돌리기'),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: Boolean(ui.busy) || Boolean(problems.length), onclick: () => save(state, changed) }, ui.busy || '저장'),
      h('button', { class: 'btn btn-warn', type: 'button', disabled: Boolean(ui.busy) || Boolean(problems.length), onclick: () => save(state, changed, { apply: true }) }, '저장 · 장비에 적용 · 모터 재시작…')),
  ];
}
