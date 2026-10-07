/** 상단의 두 칸 · **아는 쪽이 바로 고쳐 준다** · §6-286 §6-288
 *
 * 칸은 둘이다 ·
 *
 *     그룹 참여 / 그룹 미참여   이 PC 가 그룹으로 도나 혼자 도나
 *     운영시간 / 운영시간 외    지금이 스케줄 구간 안인가
 *
 * 두 사실은 **주인이 다르다** · 연동 여부는 연동 화면이 1초마다 받고, 구간
 * 여부는 스케줄 상태가 5초마다 받는다 · 전에는 둘 다 스케줄 상태에만
 * 묶여 있어서, 「연동 탈퇴」를 눌러도 상단이 최대 5초를 옛 값으로 버텼다 ·
 * 사람은 눌렸는지 안 눌렸는지를 모른다.
 *
 * 그래서 아는 쪽이 아는 것만 밀어 넣는다 · 나머지는 직전 값을 그대로 둔다.
 */

const state = {
  enabled: null,
  joined: null,
  inWindow: null,
  // supervisor 응답 없음 사유 · 빈 글자면 정상 · 수정 목록 29 (2026-10-06)
  supervisorProblem: '',
  // 앱솔루트 미확인 사유 · 판단은 서버(`minas_absolute_blocker`) · 수정 목록 62
  absoluteProblem: '',
};

/** 앱솔루트 미확인 · 모든 화면 · 누르면 모터 관리 · 수정 목록 62 */
function absoluteCell(problem) {
  return problem
    ? [{
      key: 'absolute',
      text: '앱솔루트 미확인',
      on: false,
      bad: true,
      action: 'config',
      title: `${problem} · 모든 모터 동작이 막혀 있습니다 · 누르면 모터 관리로 갑니다`,
    }]
    : [];
}

/** 문제가 있을 때만 붙는 빨간 칸 · 모터로 가는 명령을 내는 노드가 응답하지 않는다 */
function supervisorCell(problem) {
  return problem
    ? [{
      key: 'supervisor',
      text: '모터 제어 응답 없음',
      on: false,
      bad: true,
      title: `${problem} · 10초 넘게 계속되면 상위 프로그램을 자동으로 다시 띄웁니다 (모터는 제자리 홀드)`,
    }]
    : [];
}

/** 순수 계산 · 화면을 모른다 · 시험은 이것만 본다 */
export function motionHeaderConditionCells({
  enabled, joined, inWindow, supervisorProblem = '', absoluteProblem = '',
}) {
  if (enabled === null || joined === null) {
    return [
      { key: 'scope', text: '그룹?', on: false, title: '그룹 참여 상태 확인 중' },
      { key: 'window', text: '운영시간?', on: false, title: '스케줄 상태 확인 중' },
      ...supervisorCell(supervisorProblem),
      ...absoluteCell(absoluteProblem),
    ];
  }
  const grouped = Boolean(enabled) && Boolean(joined);
  return [
    {
      key: 'scope',
      text: grouped ? '그룹 참여' : '그룹 미참여',
      on: grouped,
      title: grouped
        ? '그룹 참여 중 · 다른 PC 들과 함께 재생합니다'
        : (enabled
          ? '연동을 쓰지만 그룹에서 나가 있습니다 · 이 PC 혼자 재생합니다'
          : '연동을 쓰지 않습니다 · 이 PC 혼자 재생합니다'),
    },
    {
      key: 'window',
      // 시간만 본다 · 돌지 말지는 옆의 스케줄러 배지가 말한다
      text: inWindow ? '운영시간' : '운영시간 외',
      on: Boolean(inWindow),
      title: inWindow
        ? '지금은 스케줄 운영시간입니다'
        : '지금은 스케줄 운영시간이 아닙니다 · 운영시간이 되면 스스로 켭니다',
    },
    ...supervisorCell(supervisorProblem),
    ...absoluteCell(absoluteProblem),
  ];
}

function draw() {
  // 화면이 없는 곳(시험)에서도 불린다 · 계산만 하고 조용히 돌아간다
  if (typeof document === 'undefined') return;
  const host = document.getElementById('headerConditionBadges');
  if (!host) return;
  const cells = motionHeaderConditionCells(state);
  const key = cells.map((cell) => `${cell.text}:${cell.on}:${cell.title || ''}`).join('|');
  if (host.dataset.key === key) return;
  host.dataset.key = key;
  host.replaceChildren(...cells.map((cell) => {
    const node = document.createElement('span');
    node.className = cell.bad ? 'bad' : (cell.on ? 'on' : 'off');
    node.textContent = cell.text;
    node.title = cell.title || '';
    if (cell.action) {
      // 누르면 그 화면으로 · 실제 이동은 main.js 가 한다(`data-header-action`)
      node.dataset.headerAction = cell.action;
      node.setAttribute('role', 'button');
      node.tabIndex = 0;
    }
    return node;
  }));
}

/** 아는 것만 밀어 넣는다 · 안 준 값은 직전 것을 그대로 둔다 */
export function motionHeaderConditionsUpdate(part) {
  let changed = false;
  for (const [key, value] of Object.entries(part || {})) {
    if (!(key in state) || value === undefined) continue;
    if (state[key] !== value) {
      state[key] = value;
      changed = true;
    }
  }
  if (changed) draw();
}
