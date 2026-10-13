/**
 * UI v2 · 모터 설정 ① · 모터 상세 · 파라미터 (고급) · 수정 목록 109 · 114 (2026-10-13)
 * 드라이브에 지금 들어 있는 값 · 부팅 때 우리가 쓴 값(지금 도는 모터 프로그램 · 116) · 팩토리값을 한 표에 · 다르면 표시.
 * 직접 읽기·쓰기 · 평소엔 잠김 · 쓰기는 드라이브 RAM 에만(전원을 끄면 사라짐 · 남기려면 「드라이브 저장(EEPROM)」) ·
 * 제어 워드 · 운전 모드 · PDO · EEPROM 저장 · 앱솔루트 · 0x60B2 등은 서버가 거절(전용 버튼이 있다).
 * 값은 숫자 그대로 · 뜻은 마우스를 올리면 (사용자 2026-10-13).
 */
import { h } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';

const TYPES = ['int16', 'uint16', 'int32', 'uint32', 'int8', 'uint8'];
const ui = { axis: null, rows: null, stale: '', loading: false, error: '', unlocked: false, form: { object: '', type: 'int16', value: '' }, last: '' };

async function load(axis, changed) {
  ui.loading = true;
  ui.error = '';
  changed();
  try {
    const data = await api('GET', `/api/motor-config/drive-params?axis=${axis}`, { timeoutMs: 60000 });
    if (data?.success === false) { ui.error = data.message || '읽지 못했습니다'; ui.rows = null; }
    else { ui.rows = data?.rows || []; ui.stale = String(data?.boot_stale || ''); ui.axis = axis; }
  } catch (error) {
    ui.error = error.message || String(error);
  } finally {
    ui.loading = false;
    changed();
  }
}

/** 마우스를 올리면 뜨는 글 · 번호 · 형식 · 메모 */
export function rowHint(row) {
  const parts = [`${row.number} · 0x${row.index.toString(16).toUpperCase().padStart(4, '0')}:${row.subindex} · ${row.type}`];
  if (row.memo === 'C') parts.push('전원 재투입 때 반영(지금 값을 바꿔도 바로 안 바뀜)');
  else if (row.memo === 'auto') parts.push('모터 설정 값에서 계산해 부팅 시 적용');
  else if (row.memo) parts.push(row.memo);
  if (row.error) parts.push(`못 읽음 · ${row.error}`);
  if (row.type.endsWith('32') && Number.isInteger(row.drive)) parts.push(`16진 0x${(row.drive >>> 0).toString(16).toUpperCase()}`);
  return parts.join('\n');
}

/** 표시 · 팩토리값과 다름 · 부팅 시 적용값과 다름(재시작하면 부팅 값으로 돌아감) · 적용하면 바뀜(116) */
export function rowFlags(row) {
  const flags = [];
  if (row.differs_boot) flags.push({ tone: 'warn', text: '부팅 시 적용값과 다름', hint: `재시작하면 ${row.boot} 로 돌아갑니다` });
  // 지금 도는 모터 프로그램은 옛 부팅 값 · 적용하면 바뀜 · 수정 목록 116
  if (row.boot_next !== null && row.boot_next !== undefined) flags.push({ tone: 'warn', text: `적용하면 ${row.boot_next}`, hint: '드라이브 공통 설정 · 모터 칸 값 · 「장비에 적용」 전에는 안 들어갑니다' });
  if (row.differs_factory) flags.push({ tone: 'info', text: '팩토리값과 다름', hint: `팩토리값 ${row.factory}` });
  return flags;
}

async function readOne(axis, changed) {
  try {
    const result = await api('POST', '/api/motor-config/drive-params/read', { body: { axis, object: ui.form.object, type: ui.form.type } });
    ui.last = result?.success === false ? `읽기 실패 · ${result.message}` : `${ui.form.object} = ${result.value}${result.boot !== null && result.boot !== undefined ? ` (부팅 때 ${result.boot})` : ''}`;
  } catch (error) {
    ui.last = error.message || String(error);
  }
  changed();
}

async function writeOne(axis, changed) {
  const ok = await confirmBox({
    title: `${axis}번 드라이브 파라미터 쓰기`,
    body: `${ui.form.object} (${ui.form.type}) ← ${ui.form.value}\n\n`
      + '드라이브 RAM 에 바로 씁니다. 모터가 움직이지 않을 때만 됩니다. 전원을 끄면 사라집니다(남기려면 「드라이브 저장(EEPROM)」).\n'
      + '부팅 때 우리가 쓰는 값이면 모터 프로그램이 다시 켜질 때 그 값으로 돌아갑니다.\n'
      + '뜻을 모르는 값은 쓰지 마세요. 잘못 쓰면 그 방향으로 못 움직이거나 알람이 날 수 있습니다.',
    confirmLabel: '쓰기', tone: 'danger',
  });
  if (!ok) return;
  try {
    const result = await api('POST', '/api/motor-config/drive-params/write', {
      body: { axis, object: ui.form.object, type: ui.form.type, value: ui.form.value, confirmed: true }, timeoutMs: 20000 });
    toast(result?.message || '썼습니다', result?.success === false ? 'bad' : 'ok');
    ui.last = [result?.message, ...(result?.notes || [])].filter(Boolean).join(' · ');
    if (result?.success !== false) await load(axis, changed);
  } catch (error) {
    toast(error.message || String(error), 'bad');
  }
  changed();
}

export function paramsField(row, changed) {
  if (!row.ac) return null;
  if (ui.axis !== null && ui.axis !== row.axis) { ui.axis = null; ui.rows = null; ui.stale = ''; ui.unlocked = false; ui.last = ''; }
  const groups = [];
  for (const item of ui.rows || []) {
    let group = groups.find((g) => g.name === item.group);
    if (!group) { group = { name: item.group, rows: [] }; groups.push(group); }
    group.rows.push(item);
  }
  const pick = (item) => { ui.form = { object: item.number, type: item.type, value: '' }; changed(); };
  return h('details', { class: 'detail-group' },
    h('summary', { class: 'group-title', text: '파라미터 (고급) · 드라이브 현재값 · 부팅 시 적용값 · 팩토리값' }),
    h('div', { class: 'row' },
      h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.loading, onclick: () => load(row.axis, changed) },
        ui.loading ? '읽는 중' : ui.rows ? '다시 읽기' : '드라이브에서 읽기'),
      h('span', { class: 'muted small', text: '모터 프로그램을 멈추지 않고 읽습니다. 줄을 누르면 아래 칸에 채워집니다.' })),
    ui.error ? h('p', { class: 'tone-text-bad', text: ui.error }) : null,
    // 「부팅 시 적용값」 은 지금 도는 모터 프로그램 기준 · 지금 설정과 다르면 한 줄 · 수정 목록 116
    ui.rows && ui.stale ? h('p', { class: 'tone-text-warn small', text: `${ui.stale} · 「저장 후 장비에 적용」 을 누르세요` }) : null,
    ui.rows ? h('div', { class: 'table-wrap' }, h('table', { class: 'table params-table' },
      h('thead', {}, h('tr', {}, ['항목', '드라이브 현재값', '부팅 시 적용값', '팩토리값', ''].map((text) => h('th', { scope: 'col', text })))),
      h('tbody', {}, groups.map((group) => [
        h('tr', { class: 'params-group' }, h('td', { colspan: '5', text: group.name })),
        group.rows.map((item) => h('tr', { class: 'pick-row', title: rowHint(item), onclick: () => pick(item) },
          h('td', {}, h('span', { text: item.label }), h('span', { class: 'muted small mono', text: `  ${item.number}` })),
          h('td', { class: 'mono' }, item.drive === null ? h('span', { class: 'muted', text: '못 읽음' }) : `${item.drive}${item.unit ? ` ${item.unit}` : ''}`),
          h('td', { class: 'mono muted' }, item.boot === 'auto' ? '모터 설정에서' : item.boot === null || item.boot === undefined ? '-' : String(item.boot)),
          h('td', { class: 'mono muted' }, item.factory === null ? '-' : String(item.factory)),
          h('td', {}, rowFlags(item).map((flag) => h('span', { class: `chip chip-${flag.tone}`, title: flag.hint, text: flag.text })))))]))))
      : null,
    h('div', { class: 'field' },
      h('div', { class: 'row' },
        h('input', { class: 'input mono', placeholder: 'Pr5.04 · 0x607D:2', value: ui.form.object, 'aria-label': '객체',
          oninput: (e) => { ui.form.object = e.target.value; } }),
        h('select', { class: 'input mono', 'aria-label': '형식', onchange: (e) => { ui.form.type = e.target.value; } },
          TYPES.map((type) => h('option', { value: type, selected: type === ui.form.type ? '' : null }, type))),
        h('button', { class: 'btn btn-mini', type: 'button', disabled: !ui.form.object, onclick: () => readOne(row.axis, changed) }, '읽기'),
        ui.unlocked
          ? [h('input', { class: 'input mono num-input', placeholder: '새 값', value: ui.form.value, 'aria-label': '새 값',
            oninput: (e) => { ui.form.value = e.target.value; } }),
          h('button', { class: 'btn btn-mini btn-primary', type: 'button', disabled: !ui.form.object, onclick: () => writeOne(row.axis, changed) }, '쓰기'),
          h('button', { class: 'btn btn-mini', type: 'button', onclick: () => { ui.unlocked = false; changed(); } }, '잠금')]
          : h('button', { class: 'btn btn-mini', type: 'button', onclick: async () => {
            if (await confirmBox({ title: '파라미터 쓰기 잠금 해제', body: '드라이브 파라미터를 직접 씁니다. 매뉴얼에서 뜻을 확인한 값만 쓰세요.', confirmLabel: '잠금 해제', tone: 'warning' })) {
              ui.unlocked = true; changed();
            }
          } }, '쓰기 잠금 해제')),
      ui.last ? h('p', { class: 'muted small mono', text: ui.last }) : null));
}
