/** UI v2 · 늘 같은 자리 · 상단 바(이 PC · 상태 한 문장 · 운전 모드 · 정지 둘) + 왼쪽 메뉴
 *
 * 원칙 1 · 4 · 7 (설계안 2026-10-09) · 상태 문장을 누르면 확인할 일과 해결 버튼
 */
import { h, dot, replace } from './dom.js';
import { headline, runMode } from './model.js';
import * as act from './actions.js';

export const NAV = [
  { label: '운영', items: [['home', '홈'], ['play', '공연'], ['schedule', '스케줄'], ['store', '매장 PC']] },
  { label: '작업', items: [['animations', '애니메이션'], ['manual', '수동 조작']] },
  { label: '정비', items: [['maintain-motors', '모터·드라이브'], ['mapping', '조인트 매핑'], ['pack', '로봇 팩·3D'],
    ['alarms', '알람 정책'], ['network', '네트워크·시간'], ['backup', '업데이트·백업']] },
  { label: '기록·도구', items: [['records', '기록'], ['tools', '터미널 · PC 성능'], ['docs', '사용법']] },
];

export function routeLabel(route) {
  for (const group of NAV) for (const [id, label] of group.items) if (id === route) return label;
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
  const modeButtons = Object.entries({ schedule: '자동', manual: '수동', off: '끔' }).map(([mode, label]) =>
    h('button', { class: 'seg', type: 'button', 'data-mode': mode, 'aria-pressed': 'false', onclick: () => act.setRunMode(mode) }, label));
  const modeGroup = h('div', { class: 'segmented', role: 'group', 'aria-label': '운전 모드' }, modeButtons);
  const stopButton = h('button', { class: 'btn btn-stop', type: 'button', title: '모든 움직임을 멈춥니다 · 서보는 켠 채 그 자리', onclick: act.stopAll }, '정지');
  const estopButton = h('button', { class: 'btn btn-estop', type: 'button', title: '서보를 끄고 잠급니다 · 프로그램을 다시 시작해야 풀립니다', onclick: act.emergencyStop }, '긴급 정지');
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
    ]));
  const main = h('main', { class: 'main', id: 'main', tabindex: '-1' });
  root.replaceChildren(topbar, drawer, h('div', { class: 'body' }, nav, main));

  pill.addEventListener('click', () => {
    const open = drawer.hidden;
    drawer.hidden = !open;
    pill.setAttribute('aria-expanded', String(open));
  });
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
    const config = snap?.coordination?.runtime?.config || snap?.coordination?.config || {};
    pcName.textContent = snap?.system_info?.hostname || config.pc_id || '…';
    const group = config.enabled && config.group_id ? ` · 그룹 ${config.group_id}` : '';
    pcRole.textContent = `${config.enabled ? (config.is_master ? '마스터' : '참가자') : '혼자'}${group}`;

    const line = headline(snap, sched, { connected: state.connected });
    pill.className = `status-pill tone-${line.tone}`;
    pill.replaceChildren(dot(line.tone), h('span', { class: 'status-text', text: line.text }));
    pill.disabled = !line.issues.length;
    replace(drawer,
      h('div', { class: 'drawer-head' }, h('h2', { text: line.issues.length ? `확인할 일 ${line.issues.length}` : '확인할 일 없음' })),
      line.issues.map((issue) => issueRow(issue, navigate)));
    if (!line.issues.length) drawer.hidden = true;

    const mode = runMode(sched);
    const slave = sched && sched.coordination_enabled && sched.coordination_joined && sched.is_master === false;
    for (const button of modeButtons) {
      const active = button.dataset.mode === mode;
      button.setAttribute('aria-pressed', String(active));
      button.disabled = !sched || Boolean(slave);
      button.title = slave ? '참가자 PC 는 마스터를 따릅니다 · 마스터 화면에서 바꾸세요' : '';
    }
  }

  function setRoute(route) {
    for (const [id, link] of navLinks) {
      if (id === route) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
  }

  return { main, update, setRoute };
}
