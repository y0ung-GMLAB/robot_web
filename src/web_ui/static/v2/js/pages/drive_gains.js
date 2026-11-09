/**
 * UI v2 · 모터 설정 ② · 드라이브 게인 · 수정 목록 108 (다) (사용자 2026-10-13)
 * 자동조정(Pr0.02) · 강성(Pr0.03) · 지령 스무딩(Pr2.22) · 지령 FIR(Pr2.23) · 추정 속도(Pr6.31) · 평소엔 잠김 · 「잠금 해제」 확인 뒤에만 쓴다.
 * 쓰기는 모터 프로그램을 멈추지 않는다(토크가 안 풀림) · 드라이브 RAM 에만 · 남기려면 EEPROM 저장(재시작).
 * 값은 숫자 그대로 · 뜻은 마우스를 올리면 (사용자 2026-10-13).
 * 관성비는 자동조정이 정하므로 쓰지 않는다 · 위치·속도 게인도 자동조정이 강성과 관성비로 정한다.
 */
import { h } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import { tip } from '../tip.js';

export const GAIN_FIELDS = [
  { key: 'auto_tuning', label: '자동조정', number: 'Pr0.02', min: 0, max: 4,
    meanings: { 0: '끔 (게인 고정)', 1: '표준 (일반 축)', 2: '위치결정 (짧게 이동하고 자주 정지하는 축)', 3: '수직축 (중력 부하가 걸리는 축)', 4: '마찰 보상' } },
  { key: 'stiffness', label: '강성', number: 'Pr0.03', min: 0, max: 31,
    meanings: null, note: '높을수록 지령을 강하게 따라가지만, 너무 높으면 진동과 소음 발생\n낮은 값부터 한 칸씩 올려서 조정\n팩토리값 13' },
  // 지령 필터 · 입력은 드라이브 값 그대로(0.1 ms 정수 · 92 = 9.2 ms) · 옆에 ms 로 바꿔 보여 줌 · 2026-10-16 (사용자 요청)
  { key: 'command_smoothing', label: '지령 스무딩 필터', number: 'Pr2.22', min: 0, max: 10000, msPerUnit: 0.1,
    meanings: null, note: '위치 지령 1차 지연 필터 (시작·정지는 부드러워지고 그만큼 추종이 늦어짐)'
      + '\n단위 0.1 ms (92 = 9.2 ms)'
      + '\n팩토리값 92(A~C 프레임), 139(D~H 프레임)'
      + '\n2자유도 제어(Pr6.47 bit0 = 1)일 때 최대 2000(200.0 ms)'
      + '\n강성을 바꾸면 자동조정이 이 값을 다시 쓸 수 있음'
      + '\n한 로봇의 모든 모터를 같은 값으로 설정' },
  { key: 'command_fir', label: '지령 FIR 필터', number: 'Pr2.23', min: 0, max: 10000, msPerUnit: 0.1, stoppedOnly: true,
    meanings: null, note: '위치 지령 이동 평균 필터 (설정 시간만큼 추종이 늦어짐)'
      + '\n단위 0.1 ms (10 = 1.0 ms)'
      + '\n팩토리값 10'
      + '\n모든 모터가 정지해 있을 때만 변경 가능 (동작 중에는 거절)'
      + '\n한 로봇의 모든 모터를 같은 값으로 설정' },
  { key: 'estimation_speed', label: '관성비 추정 속도', number: 'Pr6.31', min: 0, max: 3,
    meanings: { 0: '추정 안 함 (관성비 고정)', 1: '분 단위로 천천히 (팩토리값)', 2: '초 단위', 3: '최대한 빠르게 (부하가 급변하는 축)' } },
];

const ui = { unlockedAxis: null, draft: {}, busy: false };

/** 0.1 ms 칸 → 「9.2 ms」 · 다른 칸 · 숫자가 아니면 '' */
export function gainMs(field, value) {
  if (!field.msPerUnit || value === null || value === undefined || String(value).trim() === '') return '';
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  return `${(number * field.msPerUnit).toFixed(1)} ms`;
}

/** 보여 주는 값 · 「92 (9.2 ms)」 · ms 칸이 아니면 숫자 그대로 · 없으면 「-」 */
export function gainValueText(field, value) {
  if (value === null || value === undefined || value === '') return '-';
  const ms = gainMs(field, value);
  return ms ? `${value} (${ms})` : String(value);
}

export function gainHint(field, value) {
  if (field.meanings) {
    const meaning = field.meanings[value];
    const all = Object.entries(field.meanings).map(([v, text]) => `${v} = ${text}`).join('\n');
    return `${field.number} ${field.label}${meaning ? ` · ${value} = ${meaning}` : ''}\n${all}`;
  }
  const ms = gainMs(field, value);
  return `${field.number} ${field.label}${ms ? ` · 현재 ${value} = ${ms}` : ''}${field.note ? `\n${field.note}` : ''}`;
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
      problems.push(`${field.label}(${field.number})는 ${field.min}~${field.max} 사이 정수여야 합니다${field.msPerUnit ? ' (0.1 ms 단위, 92 = 9.2 ms)' : ''}`);
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
    body: '강성을 너무 높이면 진동이나 소음이 발생합니다. 한 번에 한두 칸씩 바꾸고, 주변에 사람이 없는지 확인하세요.\n'
      + '모터 프로그램 정지 없이 바로 적용되며, 전원을 끄면 원래 값으로 돌아갑니다.\n'
      + '지령 필터(스무딩, FIR)는 값을 키울수록 부드러워지지만 그만큼 추종이 늦어집니다. 한 로봇의 모든 모터를 같은 값으로 설정하세요.',
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
    const before = row.gains?.[key];
    return `· ${field.label}(${field.number}) ${before === null || before === undefined ? '?' : gainValueText(field, before)} → ${gainValueText(field, value)}`;
  });
  const stoppedOnly = GAIN_FIELDS.filter((f) => f.stoppedOnly && values[f.key] !== undefined).map((f) => f.label);
  const ok = await confirmBox({
    title: `${row.axis}번 게인 쓰기`,
    body: `${lines.join('\n')}\n\n${jump ? '강성을 한 번에 2칸 넘게 바꿉니다. 진동이 생기면 바로 「정지」를 누르고 값을 되돌리세요.\n' : ''}`
      + (stoppedOnly.length ? `${stoppedOnly.join(', ')}는 모든 모터가 정지해 있을 때만 바뀝니다(동작 중에는 거절).\n` : '')
      + '모터가 정지해 있을 때만 씁니다. 바로 적용되며, 전원을 끄면 원래 값으로 돌아갑니다.',
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
      title: '드라이브 저장(EEPROM)',
      body: '현재 값은 전원을 끄면 원래 값으로 돌아갑니다. 드라이브 EEPROM에도 저장할까요?\n저장하면 모터 프로그램이 몇 초 정지했다가 다시 시작되고, 그동안 서보 토크가 해제됩니다. 브레이크 없는 모터는 처질 수 있습니다.\n값을 더 조정할 예정이면 「나중에」를 누르세요. 표의 게인 칸은 1분 안에 갱신됩니다.',
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
          'aria-label': field.msPerUnit ? `${field.label} (0.1 ms 단위)` : field.label, title: gainHint(field, current),
          oninput: (e) => { ui.draft[field.key] = e.target.value; }, onchange: () => changed() }))
      : h('span', { class: 'mono hint', text: gainValueText(field, current), title: gainHint(field, current) });
    // ms 칸 · 입력은 0.1 ms 정수 · 쓰는 중엔 바꾼 값을 ms 로 바로 아래에
    const unit = field.msPerUnit
      ? h('span', { class: 'muted small mono', text: unlocked && String(shown).trim() !== '' ? `× 0.1 ms = ${gainMs(field, shown) || '?'}` : '× 0.1 ms' })
      : null;
    return h('label', { class: 'field' }, h('span', { class: 'field-label', text: `${field.label} ` }, h('span', { class: 'muted small mono', text: field.number })), control, unit);
  });
  return h('div', { class: 'field' },
    h('div', { class: 'group-title' }, '게인', tip([
      '자동조정이 켜져 있으면 관성비와 위치·속도 게인은 드라이브가 정하고, 사람은 강성만 조정',
      '지령 필터(스무딩, FIR)는 0.1 ms 단위 정수로 입력 (92 = 9.2 ms)',
      '지령 필터는 클수록 부드럽지만 추종이 늦어짐',
      '지령 필터는 모든 모터를 같은 값으로 설정하고, FIR은 정지 상태에서만 변경 가능',
      '드라이브에 쓰면 바로 적용되지만 전원을 끄면 원래 값으로 돌아감',
      '값을 유지하려면 「드라이브 저장(EEPROM)」',
    ], '게인 설명')),
    h('span', { class: 'muted small', text: `드라이브에 저장된 값${gains?.inertia_ratio !== undefined && gains?.inertia_ratio !== null ? ` · 관성비 ${gains.inertia_ratio} % (자동조정 값)` : ''}` }),
    h('div', { class: 'row form-row' }, cells),
    h('div', { class: 'row' },
      unlocked
        ? [h('button', { class: 'btn btn-mini btn-primary', type: 'button', disabled: ui.busy, onclick: () => write(row, changed, reload) }, ui.busy ? '쓰는 중' : '드라이브에 쓰기'),
          h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy, onclick: () => { ui.unlockedAxis = null; ui.draft = {}; changed(); } }, '취소')]
        : h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.busy || !gains, title: gains ? '' : '아직 드라이브에서 읽지 못했습니다',
          onclick: () => unlock(row, changed) }, '잠금 해제')));
}
