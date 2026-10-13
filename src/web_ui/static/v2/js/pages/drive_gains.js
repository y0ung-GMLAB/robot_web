/**
 * UI v2 · 모터 설정 ① · 드라이브 게인 · 수정 목록 108 (다) (사용자 2026-10-13)
 * 자동조정(Pr0.02) · 강성(Pr0.03) · 추정 속도(Pr6.31) · 평소엔 잠김 · 「잠금 해제」 확인 뒤에만 쓴다.
 * 쓰기는 모터 프로그램을 멈추지 않는다(토크가 안 풀림) · 드라이브 RAM 에만 · 남기려면 EEPROM 저장(재시작).
 * 값은 숫자 그대로 · 뜻은 마우스를 올리면 (사용자 2026-10-13).
 * 관성비는 자동조정이 정하므로 쓰지 않는다 · 위치·속도 게인도 자동조정이 강성과 관성비로 정한다.
 */
import { h } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';

export const GAIN_FIELDS = [
  { key: 'auto_tuning', label: '자동조정', number: 'Pr0.02', min: 0, max: 4,
    meanings: { 0: '끔 · 게인이 그대로 고정', 1: '표준 · 보통은 이것', 2: '위치결정 · 짧게 자주 서는 축', 3: '수직축 · 중력이 늘 걸리는 축', 4: '마찰 보상' } },
  { key: 'stiffness', label: '강성', number: 'Pr0.03', min: 0, max: 31,
    meanings: null, note: '높을수록 단단하게 따라감 · 너무 높으면 떨림·소리 · 낮은 값부터 한 칸씩 · 출하값 13' },
  { key: 'estimation_speed', label: '관성비 추정 속도', number: 'Pr6.31', min: 0, max: 3,
    meanings: { 0: '멈춤 · 관성비 고정', 1: '분 단위 · 천천히(출하값)', 2: '초 단위', 3: '급변 · 부하가 갑자기 바뀌는 축' } },
];

const ui = { unlockedAxis: null, draft: {}, busy: false };

export function gainHint(field, value) {
  if (field.meanings) {
    const meaning = field.meanings[value];
    const all = Object.entries(field.meanings).map(([v, text]) => `${v} = ${text}`).join('\n');
    return `${field.number} ${field.label}${meaning ? ` · ${value} = ${meaning}` : ''}\n${all}`;
  }
  return `${field.number} ${field.label} · ${field.note || ''}`;
}

/** 바뀐 칸만 · 숫자 · 범위 밖이면 문제 글 */
export function gainChanges(gains, draft) {
  const values = {};
  const problems = [];
  for (const field of GAIN_FIELDS) {
    if (!(field.key in (draft || {}))) continue;
    const text = String(draft[field.key] ?? '').trim();
    if (text === '') continue;
    const value = Number(text);
    if (!Number.isInteger(value) || value < field.min || value > field.max) {
      problems.push(`${field.label}(${field.number}) 는 ${field.min}~${field.max} 사이 정수`);
      continue;
    }
    if (gains && gains[field.key] === value) continue;
    values[field.key] = value;
  }
  return { values, problems };
}

async function unlock(row, changed) {
  const ok = await confirmBox({
    title: `${row.axis}번 게인 잠금 해제`,
    body: '드라이브 게인을 바꿉니다. 모터 프로그램을 멈추지 않고 바로 적용됩니다(전원을 끄면 사라짐).\n'
      + '강성을 너무 높이면 떨리거나 소리가 납니다. 한 번에 한두 칸씩 바꾸고, 주변에 사람이 없는지 확인하세요.',
    confirmLabel: '잠금 해제', tone: 'warning',
  });
  if (!ok) return;
  ui.unlockedAxis = row.axis;
  ui.draft = {};
  changed();
}

async function write(row, changed, reload) {
  const { values, problems } = gainChanges(row.gains, ui.draft);
  if (problems.length) { toast(problems.join(' · '), 'bad'); return; }
  if (!Object.keys(values).length) { ui.unlockedAxis = null; changed(); return; }
  const before = row.gains?.stiffness;
  const jump = values.stiffness !== undefined && Number.isInteger(before) && Math.abs(values.stiffness - before) > 2;
  const lines = Object.entries(values).map(([key, value]) => {
    const field = GAIN_FIELDS.find((f) => f.key === key);
    return `· ${field.label}(${field.number}) ${row.gains?.[key] ?? '?'} → ${value}`;
  });
  const ok = await confirmBox({
    title: `${row.axis}번 게인 쓰기`,
    body: `${lines.join('\n')}\n\n${jump ? '강성을 한 번에 2칸 넘게 바꿉니다. 떨림이 생기면 바로 「정지」 후 되돌리세요.\n' : ''}`
      + '모터가 움직이지 않을 때만 씁니다. 지금부터 적용되고, 전원을 끄면 사라집니다.',
    confirmLabel: '쓰기', tone: jump ? 'danger' : 'warning',
  });
  if (!ok) return;
  ui.busy = true;
  changed();
  try {
    const result = await api('POST', '/api/motor-config/drive-gains', { body: { axis: row.axis, values, confirmed: true }, timeoutMs: 30000 });
    if (result?.success === false) { toast(result.message || '쓰지 못했습니다', 'bad'); return; }
    toast(result?.message || '썼습니다', 'ok');
    ui.unlockedAxis = null;
    ui.draft = {};
    const keep = await confirmBox({
      title: '드라이브에 저장 (EEPROM)',
      body: '지금 값은 전원을 끄면 사라집니다. EEPROM에도 저장할까요?\n모터 프로그램이 몇 초 멈췄다 다시 켜지고, 그동안 서보 토크가 풀립니다. 브레이크가 없는 모터는 처질 수 있습니다.\n(값을 더 맞춰 볼 거면 나중에 저장해도 됩니다. 표의 게인 칸은 1분 안에 새 값으로 바뀝니다.)',
      confirmLabel: '저장', cancelLabel: '나중에', tone: 'warning',
    });
    if (keep) await saveAll([row.axis], changed, reload);
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = false;
    changed();
  }
}

/** 여러 축 EEPROM 저장 · 모터 프로그램 재시작 한 번 */
export async function saveAll(axes, changed, reload) {
  ui.busy = true;
  changed();
  try {
    const result = await api('POST', '/api/motor-config/eeprom-save-all', { body: { axes, confirmed: true }, timeoutMs: 120000 });
    toast(result?.message || (result?.success === false ? 'EEPROM 저장 실패' : '저장했습니다'), result?.success === false ? 'bad' : 'ok');
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = false;
    if (reload) await reload();
    changed();
  }
}

/** 자동조정이 꺼진 축 모두 켜기 · 강성은 그대로 · 108 (다) 「전체를 자동으로」 */
export async function autoTuneAll(rows, changed, reload) {
  const off = rows.filter((r) => r.ac && r.gains && r.gains.auto_tuning === 0);
  if (!off.length) return;
  const ok = await confirmBox({
    title: '자동조정 켜기',
    body: `${off.map((r) => `${r.axis}번`).join(' · ')} 의 자동조정(Pr0.02)을 1(표준)로 켭니다. 강성은 그대로입니다.\n`
      + '모터가 움직이지 않을 때만 씁니다. 켠 뒤 몇 분 움직여야 관성비가 맞춰집니다.',
    confirmLabel: '켜기', tone: 'warning',
  });
  if (!ok) return;
  ui.busy = true;
  changed();
  try {
    const result = await api('POST', '/api/motor-config/drive-gains', {
      body: { axes: off.map((r) => r.axis), values: { auto_tuning: 1 }, confirmed: true }, timeoutMs: 60000 });
    toast(result?.message || '켰습니다', result?.success === false ? 'bad' : 'ok');
    if (result?.success !== false && await confirmBox({
      title: '드라이브에 저장 (EEPROM)', body: '전원을 꺼도 남게 EEPROM에도 저장할까요? 모터 프로그램이 몇 초 멈췄다 다시 켜집니다.',
      confirmLabel: '저장', cancelLabel: '나중에', tone: 'warning',
    })) await saveAll(off.map((r) => r.axis), changed, reload);
  } catch (error) {
    toast(error.message || String(error), 'bad');
  } finally {
    ui.busy = false;
    changed();
  }
}

/** 모터 상세 칸 · 게인 묶음 */
export function gainField(row, changed, reload) {
  if (!row.ac) return null;
  const gains = row.gains;
  const unlocked = ui.unlockedAxis === row.axis;
  const cells = GAIN_FIELDS.map((field) => {
    const current = gains?.[field.key];
    const shown = ui.draft[field.key] !== undefined ? ui.draft[field.key] : (current ?? '');
    const control = unlocked
      ? (field.meanings
        ? h('select', { class: 'input mono', 'aria-label': field.label, title: gainHint(field, Number(shown)),
          onchange: (e) => { ui.draft[field.key] = e.target.value; changed(); } },
        Object.keys(field.meanings).map((v) => h('option', { value: v, title: `${v} = ${field.meanings[v]}`, selected: String(shown) === v ? '' : null }, v)))
        : h('input', { class: 'input mono num-input', type: 'number', min: field.min, max: field.max, step: '1', value: shown,
          'aria-label': field.label, title: gainHint(field, current),
          oninput: (e) => { ui.draft[field.key] = e.target.value; }, onchange: () => changed() }))
      : h('span', { class: 'mono hint', text: current ?? '-', title: gainHint(field, current) });
    return h('label', { class: 'field' }, h('span', { class: 'field-label', text: `${field.label} ` }, h('span', { class: 'muted small mono', text: field.number })), control);
  });
  return h('div', { class: 'field' },
    h('span', { class: 'field-label', text: `게인 · 드라이브에 저장된 값${gains?.inertia_ratio !== undefined && gains?.inertia_ratio !== null ? ` · 관성비 ${gains.inertia_ratio} %(자동조정이 정함)` : ''}` }),
    h('div', { class: 'row form-row' }, cells),
    h('div', { class: 'row' },
      unlocked
        ? [h('button', { class: 'btn btn-mini btn-primary', type: 'button', disabled: ui.busy, onclick: () => write(row, changed, reload) }, ui.busy ? '쓰는 중' : '드라이브에 쓰기'),
          h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy, onclick: () => { ui.unlockedAxis = null; ui.draft = {}; changed(); } }, '취소')]
        : h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy || !gains, title: gains ? '' : '아직 드라이브에서 읽지 못했습니다',
          onclick: () => unlock(row, changed) }, '잠금 해제')),
    h('p', { class: 'muted small', text: '자동조정이 켜져 있으면 관성비와 위치·속도 게인은 드라이브가 정합니다. 사람이 맞추는 것은 강성입니다. 쓰면 바로 적용되고 전원을 끄면 사라집니다(남기려면 EEPROM 저장).' }));
}
