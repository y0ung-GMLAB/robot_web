/** UI v2 · 늘 같은 자리 · 상단 바(이 PC · 상태 한 문장 · 운전 모드 · 정지 둘) + 왼쪽 메뉴
 *
 * 원칙 1 · 4 · 7 (설계안 2026-10-09) · 상태 문장을 누르면 확인할 일과 해결 버튼
 */
import { h, dot, replace } from './dom.js';
import { headline, pcRole as pcRoleOf, runMode, RUN_MODE_HINT } from './model.js';
import * as act from './actions.js';

export const NAV = [
  { label: '운영', items: [['home', '홈'], ['play', '재생'], ['schedule', '스케줄'], ['store', 'PC 현황']] },
  { label: '작업', items: [['animations', '애니메이션'], ['manual', '수동 조작']] },
  { label: '설정', items: [['maintain-motors', '모터 설정'], ['pack', '로봇 팩·3D'],
    ['alarms', '드라이브 알람'], ['network', '네트워크·시간·그룹'], ['backup', '업데이트·백업']] },
  { label: '기록·도구', items: [['records', '기록'], ['tools', '터미널 · PC 성능'], ['docs', '사용법']] },
];

/** 메뉴에 따로 없는 화면 → 메뉴에서 켜질 칸 · 조인트 매핑은 「모터 설정」 의 두 번째 탭 */
export const NAV_ALIASES = { mapping: 'maintain-motors' };

export function routeLabel(route) {
  const id = NAV_ALIASES[route] || route;
  for (const group of NAV) for (const [item, label] of group.items) if (item === id) return label;
  return '';
}

/** 문제 하나의 해결 버튼 */
export function issueAction(issue, navigate) {
  const action = issue.action;
  if (!action) return null;
  const run = {
    'restart-program': act.restartProgram,
    'fault-reset': act.faultReset,
    'update-all': act.updateAll,
    'ack-group-error': act.ackGroupError,
    'apply-motor-config': act.applyBootParams,
    open: () => navigate(action.target),
  }[action.kind];
  if (!run) return null;
  return h('button', { class: `btn btn-${issue.tone === 'bad' ? 'danger-soft' : 'warn'}`, type: 'button', onclick: run }, action.label);
}

export function issueRow(issue, navigate) {
  return h('div', { class: `issue issue-${issue.tone}` },
    dot(issue.tone === 'bad' ? 'bad' : 'warn'),
    h('div', { class: 'issue-text' },
      h('strong', { text: issue.title }),
      issue.detail ? h('span', { text: issue.detail }) : null),
    issueAction(issue, navigate));
}

export function createShell(root, { navigate }) {
  const pcName = h('strong', { class: 'pc-name', text: '…' });
  const pcRole = h('span', { class: 'pc-role', text: '' });
  const pill = h('button', { class: 'status-pill tone-info', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'issues-drawer' },
    dot('info'), h('span', { class: 'status-text', text: '연결 중' }));
  const modeButtons = Object.entries({ schedule: '스케줄', manual: '수동', off: '끔' }).map(([mode, label]) =>
    h('button', { class: 'seg', type: 'button', 'data-mode': mode, 'aria-pressed': 'false', onclick: () => act.setRunMode(mode) }, label));
  const modeGroup = h('div', { class: 'segmented', role: 'group', 'aria-label': '운전 모드' }, modeButtons);
  const stopButton = h('button', { class: 'btn btn-stop', type: 'button', title: '모든 움직임을 정지합니다. 서보 토크는 유지됩니다.', onclick: act.stopAll }, '정지');
  const estopButton = h('button', { class: 'btn btn-estop', type: 'button', title: '서보를 끄고 잠급니다. 프로그램을 다시 시작해야 해제됩니다.', onclick: act.emergencyStop }, '긴급 정지');
  const drawer = h('section', { id: 'issues-drawer', class: 'issues-drawer', hidden: true, 'aria-label': '확인할 일' });
  const menuButton = h('button', { class: 'btn btn-icon menu-toggle', type: 'button', 'aria-label': '메뉴', 'aria-expanded': 'false' }, '≡');

  const topbar = h('header', { class: 'topbar' },
    menuButton,
    h('div', { class: 'pc' }, pcName, pcRole),
    h('span', { class: 'spacer' }),
    pill,
    h('span', { class: 'spacer' }),
    modeGroup,
    h('div', { class: 'stops' }, stopButton, estopButton));

  const navLinks = new Map();
  const nav = h('nav', { class: 'nav', 'aria-label': '메뉴' },
    NAV.map((group) => [
      h('p', { class: 'nav-group', text: group.label }),
      group.items.map(([id, label]) => {
        const link = h('a', { href: `#/${id}`, class: 'nav-link', 'data-route': id }, label);
        navLinks.set(id, link);
        return link;
      }),
    ]),
    // 기존 화면은 / 에 그대로 · 같은 서버 · 같은 설정 · 익숙한 화면으로 돌아갈 때
    h('a', { href: '/', class: 'nav-link nav-old', title: '이전 UI · 같은 서버를 쓰므로 어느 쪽에서 바꿔도 똑같이 반영됩니다' }, '이전 UI ↗'));
  const main = h('main', { class: 'main', id: 'main', tabindex: '-1' });
  root.replaceChildren(topbar, drawer, h('div', { class: 'body' }, nav, main));

  // 확인할 일 창 · 닫기 버튼 · Esc · 바깥 누르기 · 해결 버튼 누르기 · 화면 이동 때 닫힌다 (실물 2026-10-12 · 전에는 상태 버튼을 다시 눌러야만 닫혀 메뉴를 가렸다)
  function setDrawer(open) {
    drawer.hidden = !open;
    pill.setAttribute('aria-expanded', String(open));
  }
  pill.addEventListener('click', (event) => {
    event.stopPropagation();
    setDrawer(drawer.hidden);
  });
  drawer.addEventListener('click', (event) => {
    event.stopPropagation();
    if (event.target.closest('button, a')) setDrawer(false);
  });
  document.addEventListener('click', () => { if (!drawer.hidden) setDrawer(false); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !drawer.hidden) setDrawer(false); });
  menuButton.addEventListener('click', () => {
    const open = !nav.classList.contains('open');
    nav.classList.toggle('open', open);
    menuButton.setAttribute('aria-expanded', String(open));
  });
  nav.addEventListener('click', () => {
    nav.classList.remove('open');
    menuButton.setAttribute('aria-expanded', 'false');
  });

  function update(state) {
    const snap = state.snap;
    const sched = state.sched;
    const role = pcRoleOf(snap);
    pcName.textContent = snap?.system_info?.hostname || role.pcId || '…';
    pcRole.textContent = role.text;

    const line = headline(snap, sched, { connected: state.connected });
    pill.className = `status-pill tone-${line.tone}`;
    pill.replaceChildren(dot(line.tone), h('span', { class: 'status-text', text: line.text }));
    pill.disabled = !line.issues.length;
    replace(drawer,
      h('div', { class: 'drawer-head' }, h('h2', { class: 'grow', text: line.issues.length ? `확인할 일 ${line.issues.length}` : '확인할 일 없음' }),
        h('button', { class: 'btn btn-mini', type: 'button', 'aria-label': '확인할 일 닫기' }, '닫기 ✕')),
      line.issues.map((issue) => issueRow(issue, navigate)));
    if (!line.issues.length) setDrawer(false);

    const mode = runMode(sched);
    const slave = sched && sched.coordination_enabled && sched.coordination_joined && sched.is_master === false;
    for (const button of modeButtons) {
      const active = button.dataset.mode === mode;
      button.setAttribute('aria-pressed', String(active));
      button.disabled = !sched || Boolean(slave);
      button.title = slave ? '슬레이브 PC는 마스터 설정을 따릅니다. 마스터 화면에서 바꾸세요.' : (RUN_MODE_HINT[button.dataset.mode] || '');
    }
  }

  function setRoute(route) {
    setDrawer(false);
    const navId = NAV_ALIASES[route] || route;
    for (const [id, link] of navLinks) {
      if (id === navId) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
  }

  return { main, update, setRoute };
}
