/** UI v2 · 모터 설정 · ① 조인트 매핑 과 ② 모터·드라이브 를 한 페이지의 두 구획으로 (사용자 결정 2026-10-12)
 *
 * 따로 있던 두 화면이 각자 단계 표시와 「저장 후 장비에 적용」 을 갖고 있어 같은 일을 하는 것처럼 보였다 ·
 * 탭으로 나누는 것보다 한 페이지에 구획을 나눠 두는 쪽이 찾기 쉽다(사용자) · 머리 · 저장 칸은 여기 하나만.
 * 저장은 바뀐 쪽만 · 장비 적용은 둘 다 저장한 뒤 한 번 · #/mapping 주소는 ① 구획 · #/motors 주소는 ② 구획으로 스크롤.
 * 2026-10-16 (사용자) 조인트 매핑을 위로 · 처음 설치 순서(모터 검색 → 「인식 모터 자동 생성」)는 그대로, 화면 위치만 바뀜.
 */
import { h, dot } from '../dom.js';
import { bootParamsNotice } from '../model.js';
import { confirmBox, toast } from '../dialog.js';
import * as act from '../actions.js';
import { loadMotors, motorsActions, motorsBody, motorsDraft, revertMotors, saveMotors } from './motors.js';
import { isRevisionConflict } from '../mapping_model.js';
import { loadMapping, mappingActions, mappingBody, mappingDraft, mappingNote, revertMapping, saveMapping } from './mapping.js';

// 화면 위에서부터 · [구획 id, 제목, 설명, 주소] · 2026-10-16 조인트 매핑을 위로 (사용자)
export const SETUP_PARTS = [
  ['part-mapping', '① 조인트 매핑', '애니메이션 조인트 값을 모터 값으로 바꾸는 규칙 · 감속·기어비 · 방향 · 기준점 · 범위', 'mapping'],
  ['part-motors', '② 모터·드라이브', '실제 모터 · 검색 · 이름 · 속도 · 브레이크 · 서보 · 앱솔루트 · 게인', 'motors'],
];
const part = (id) => SETUP_PARTS.find(([partId]) => partId === id);
// 이 주소로 들어오면 그 구획으로 한 번 내려간다 · #/maintain-motors(메뉴)는 페이지 맨 위
const SCROLL_ROUTES = Object.fromEntries(SETUP_PARTS.map(([id, , , route]) => [route, id]));

const ui = { busy: false, scrolledFor: '' };

export async function loadSetup(state, changed) {
  await Promise.all([loadMotors(state, changed), loadMapping(state, changed)]);
}

/** 구획마다 끝났는지 · 장비 적용 상태 · 화면 없이 시험된다 */
export function setupStatus(snap, { dirty = false } = {}) {
  const motors = Array.isArray(snap?.motion_state?.motors) ? snap.motion_state.motors : [];
  const detected = motors.filter((m) => m.state === 'detected').length;
  const scope = snap?.project_scope || {};
  const applied = scope.runtime_matches_selected === true && scope.motor_config_applied === true;
  // 파일은 적용됐어도 지금 도는 모터 프로그램의 부팅 값이 옛 값이면 적용 필요 · 수정 목록 116
  const boot = bootParamsNotice(snap);
  let apply = applied ? (dirty ? ['장비에 적용됨 · 저장하지 않은 변경 있음', 'warn'] : ['장비에 적용됨', 'ok']) : ['장비에 적용 필요', 'warn'];
  if (applied && boot) apply = [boot.title, 'warn'];
  return {
    motors: { done: motors.length > 0 && detected === motors.length, note: `${detected}/${motors.length}대 연결` },
    mapping: { done: !snap?.mapping_range_blocker, note: snap?.mapping_range_blocker ? '범위 미확인' : '' },
    apply,
    boot,
  };
}

/** 저장 칸 글 · 두 구획 변경을 한 줄로 */
export function pendingText(motorChanges, mappingChanges) {
  const parts = [];
  if (motorChanges.length) parts.push(`모터 ${motorChanges.length}개`);
  if (mappingChanges.length) parts.push(`조인트 매핑 ${mappingChanges.length}개`);
  if (!parts.length) return '저장됨';
  const first = [...motorChanges, ...mappingChanges].slice(0, 3);
  const rest = motorChanges.length + mappingChanges.length - 3;
  const more = rest > 0 ? ` 외 ${rest}개` : '';
  return `저장하지 않은 변경 · ${parts.join(' · ')} · ${first.join(' · ')}${more}`;
}

function jumpTo(id) {
  const node = document.getElementById(id);
  if (!node) return;
  // 위 막대(sticky)에 제목이 가리지 않게 · 좁은 화면은 막대가 두세 줄이라 높이를 그때 잰다
  const bar = document.querySelector('.topbar');
  node.style.scrollMarginTop = `${(bar ? bar.getBoundingClientRect().height : 0) + 12}px`;
  node.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** 바뀐 쪽만 저장 · 저장한 것 메시지 목록 · 하나라도 실패하면 null */
async function saveChanged(state, changed) {
  const motors = motorsDraft();
  const mapping = mappingDraft();
  const messages = [];
  if (motors.changes.length) {
    try {
      const message = await saveMotors(state, changed);
      // 충돌 확인 창에서 「저장 안 함」 · 매핑 저장 · 장비 적용으로 넘어가지 않는다
      if (message === null) return null;
      messages.push(message);
    } catch (error) {
      if (isRevisionConflict(error.message)) {
        // 화면을 연 뒤 파일이 바뀌었다(다른 화면 저장 · 매핑 저장이 운전 한계를 고쳐 씀) · 고친 것을 버리고 다시 받을지 묻는다
        const reload = await confirmBox({
          title: '모터 설정 파일이 화면을 연 뒤 바뀌었습니다',
          body: '다른 화면에서 저장했거나, 조인트 매핑 저장으로 운전 한계가 바뀌었습니다.\n「다시 불러오기」를 누르면 최신 파일을 받습니다(이 화면에서 고친 모터 설정은 사라집니다). 다시 불러온 뒤 고쳐서 저장하세요.',
          confirmLabel: '다시 불러오기', tone: 'warning',
        });
        if (reload) await loadMotors(state, changed, { force: true });
        return null;
      }
      toast(`모터 설정 저장 실패 · ${error.message || error}`, 'bad');
      return null;
    }
  }
  if (mapping.changes.length) {
    const message = await saveMapping(state, changed);
    if (message === null) return null;
    messages.push(message);
    // 매핑을 저장하면 서버가 모터 설정 파일의 운전 한계(하한·상한)도 고쳐 쓴다 · 화면의 모터 설정 버전을
    // 새로 받지 않으면 다음 모터 저장이 「화면을 불러온 뒤 변경됐습니다」 로 막혔다 (2026-10-12 실물)
    await loadMotors(state, changed, { force: !motorsDraft().changes.length });
  }
  return messages;
}

async function save(state, changed, { apply = false } = {}) {
  if (ui.busy) return;
  const problems = [...motorsDraft().problems, ...mappingDraft().problems];
  if (problems.length) { toast(problems[0], 'bad'); return; }
  const dirty = motorsDraft().changes.length + mappingDraft().changes.length > 0;
  if (!apply && !dirty) { toast('저장할 변경이 없습니다', 'warn'); return; }
  if (apply && !(await act.confirmApplyMotorConfig(dirty
    ? '바꾼 모터 설정과 조인트 매핑을 저장한 뒤 바로 장비에 적용합니다. 운전 한계(소프트 리밋)도 조인트 매핑 범위로 바뀝니다.'
    : '저장된 모터 설정과 조인트 매핑을 장비에 적용합니다.'))) return;
  ui.busy = true;
  changed();
  try {
    const messages = await saveChanged(state, changed);
    if (messages === null) return;
    if (apply) {
      await act.applyMotorConfig();
    } else {
      await confirmBox({ title: '저장했습니다', body: `${messages.join('\n')}\n\n드라이브에 반영하려면 「저장 후 장비에 적용」을 누르세요.`, confirmLabel: '확인' });
    }
  } finally {
    ui.busy = false;
    changed();
  }
}

/** 아래 저장 칸 버튼 툴팁 · 막혔으면 먼저 걸리는 이유 · 아니면 하는 일 · 수정 목록 118 */
export function blockReason({ busy, dirty, problems }, ok) {
  if (busy) return '저장·적용하는 중입니다';
  if (problems.length) return `막힘 · ${problems[0]}`;
  if (!dirty) return '바꾼 내용이 없습니다';
  return ok;
}

function partHead([id, label, hint], status, actions, note) {
  return [
    h('div', { class: 'part-head' },
      h('h2', {}, label, status.note ? h('small', { class: `part-note${status.done ? ' ok' : ''}`, text: ` · ${status.note}` }) : null),
      h('span', { class: 'spacer' }),
      actions),
    note || h('p', { class: 'muted small', text: hint }),
  ];
}

export function renderSetup(state, { changed }) {
  const motors = motorsDraft();
  const mapping = mappingDraft();
  const dirty = motors.changes.length + mapping.changes.length > 0;
  const status = setupStatus(state.snap, { dirty });
  const busy = ui.busy || Boolean(motors.busy) || Boolean(mapping.busy);
  const problems = [...motors.problems, ...mapping.problems];
  // #/mapping → ① 구획 · #/motors → ② 구획 · 한 번만 내려간다(다시 그릴 때마다 끌어내리지 않게)
  const route = location.hash.replace(/^#\/?/, '').split('?')[0];
  const target = SCROLL_ROUTES[route];
  if (target && ui.scrolledFor !== route && mapping.ready) {
    ui.scrolledFor = route;
    requestAnimationFrame(() => jumpTo(target));
  } else if (!target) {
    ui.scrolledFor = '';
  }
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '모터 설정' }),
      h('nav', { class: 'row part-jumps', 'aria-label': '바로 가기' },
        SETUP_PARTS.map(([id, label, , partRoute]) => h('a', { class: 'btn btn-mini', href: `#/${partRoute}`,
          onclick: (event) => { event.preventDefault(); jumpTo(id); } }, label))),
      h('span', { class: `chip chip-${status.apply[1]}`, text: status.apply[0] })),
    // 지금 도는 모터 프로그램이 옛 부팅 값 · 업데이트만 하고 적용 안 함 · 수정 목록 116
    status.boot ? h('div', { class: 'blocker' }, dot('warn'),
      h('span', { class: 'grow' }, h('strong', { text: status.boot.title }), h('span', { class: 'muted small', text: ` · ${status.boot.detail}` })),
      h('button', { class: 'btn btn-warn', type: 'button', disabled: busy || Boolean(problems.length), onclick: () => save(state, changed, { apply: true }) }, '저장 후 장비에 적용')) : null,
    h('section', { class: 'setup-part', id: 'part-mapping', 'aria-label': '조인트 매핑' },
      partHead(part('part-mapping'), status.mapping, mappingActions(state, changed), mapping.ready ? mappingNote() : null),
      mappingBody(state, changed)),
    h('section', { class: 'setup-part', id: 'part-motors', 'aria-label': '모터·드라이브' },
      partHead(part('part-motors'), status.motors, motorsActions(state, changed)),
      motorsBody(state, changed)),
    h('div', { class: 'apply-bar' },
      h('div', { class: 'grow' },
        h('span', { text: pendingText(motors.changes, mapping.changes) }),
        problems.length ? h('p', { class: 'tone-text-warn small', text: problems[0] }) : null),
      // 막힌 버튼마다 이유를 툴팁으로 · 수정 목록 118
      h('button', { class: 'btn', type: 'button', disabled: busy || !dirty, title: blockReason({ busy, dirty, problems: [] }, '저장하지 않은 변경을 버립니다'),
        onclick: () => { revertMotors(); revertMapping(); changed(); } }, '되돌리기'),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: busy || !dirty || Boolean(problems.length), title: blockReason({ busy, dirty, problems }, '파일에만 저장합니다(드라이브에는 「저장 후 장비에 적용」 뒤 반영)'),
        onclick: () => save(state, changed) }, busy ? '저장 중…' : '저장'),
      h('button', { class: 'btn btn-warn', type: 'button', disabled: busy || Boolean(problems.length), title: blockReason({ busy, dirty: true, problems }, '저장한 뒤 장비에 적용하고 모터 프로그램을 다시 시작합니다'),
        onclick: () => save(state, changed, { apply: true }) }, '저장 후 장비에 적용')),
  ];
}
