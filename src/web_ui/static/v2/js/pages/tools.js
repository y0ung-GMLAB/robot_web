/** UI v2 · 터미널 · PC 성능 · 이 PC 의 ttyd(:8081) 와 btop(:8080) (설계안 2026-10-09)
 *
 * 한 번만 그린다(main.js `static`) · iframe 은 DOM 에서 옮기면 다시 읽혀 터미널 세션이 끊긴다 ·
 * 탭은 칸 숨김만 바꾼다 · 주소는 처음 볼 때 넣는다(안 보는 쪽은 연결도 안 한다).
 */
import { h } from '../dom.js';

const TOOLS = [
  { key: 'terminal', label: '터미널', port: 8081 },
  { key: 'btop', label: 'PC 성능 (btop)', port: 8080 },
];
const TAB_KEY = 'robot_web.v2.toolsTab';

export function renderTools() {
  const host = location.hostname;
  const parts = Object.fromEntries(TOOLS.map((tool) => {
    const frame = h('iframe', { class: 'tool-frame', title: tool.label });
    const tab = h('button', { class: 'seg', type: 'button', 'aria-pressed': 'false', onclick: () => show(tool.key) }, tool.label);
    const section = h('section', { class: 'card tool-card', 'aria-label': tool.label, hidden: true },
      tool.key === 'terminal' ? [
        h('p', { class: 'small' }, h('strong', { text: '코드 받기 + 다시 빌드' }),
          ' · 아래 명령을 그대로 입력하세요(몇 분 걸립니다). 빌드하는 동안 웹 화면은 잠시 끊기지만 터미널은 끊기지 않습니다. 끝나면 「설치 완료」가 표시됩니다.'),
        h('pre', { class: 'doc-code' }, h('code', { text: 'bash scripts/install.sh' })),
      ] : null,
      frame);
    return [tool.key, { ...tool, frame, tab, section, url: `http://${host}:${tool.port}/` }];
  }));
  const newWindow = h('a', { class: 'btn btn-mini', target: '_blank', rel: 'noopener' }, '새 창 ↗');

  function show(key) {
    for (const part of Object.values(parts)) {
      const on = part.key === key;
      part.section.hidden = !on;
      part.tab.setAttribute('aria-pressed', String(on));
      if (on && !part.frame.getAttribute('src')) part.frame.setAttribute('src', part.url);
      if (on) newWindow.setAttribute('href', part.url);
    }
    try { localStorage.setItem(TAB_KEY, key); } catch { /* 기억 못 해도 된다 */ }
  }

  let first = 'terminal';
  try { if (localStorage.getItem(TAB_KEY) === 'btop') first = 'btop'; } catch { /* 기본 */ }
  show(first);
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '터미널 · PC 성능' }),
      h('div', { class: 'segmented', role: 'group', 'aria-label': '도구' }, TOOLS.map((tool) => parts[tool.key].tab)),
      h('span', { class: 'spacer' }),
      newWindow),
    TOOLS.map((tool) => parts[tool.key].section),
  ];
}
