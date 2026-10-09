/** UI v2 · 시작 · 상태 모으기 · 주소(#/화면) 따라 그리기 (설계안 2026-10-09 · 뼈대 + 홈)
 *
 * 그리기 규칙 · 상단 바는 상태가 올 때마다 · 본문은 0.5초에 한 번까지 · 누르는 중(포인터 눌림)에는
 * 미룬다 · 버튼을 누르는 사이 그 버튼이 새로 그려져 눌림이 사라지는 일을 막는다.
 */
import { replace } from './dom.js';
import { api, poll, StatusStream } from './net.js';
import { createShell, routeLabel } from './shell.js';
import { renderHome } from './pages/home.js';
import { renderPlaceholder } from './pages/placeholder.js';

const state = { snap: null, sched: null, schedules: [], events: [], connected: false };
const PAGES = { home: renderHome };
const PAGE_INTERVAL_MS = 500;

function currentRoute() {
  const route = location.hash.replace(/^#\/?/, '').split('?')[0];
  return route && routeLabel(route) ? route : 'home';
}

function navigate(route) {
  location.hash = `#/${route}`;
}

const shell = createShell(document.getElementById('app'), { navigate });

let pointerDown = false;
let pagePending = false;
let lastPageAt = 0;
document.addEventListener('pointerdown', () => { pointerDown = true; }, true);
document.addEventListener('pointerup', () => { pointerDown = false; schedulePage(); }, true);
document.addEventListener('pointercancel', () => { pointerDown = false; }, true);

function renderPage() {
  pagePending = false;
  if (pointerDown) return;
  lastPageAt = Date.now();
  const route = currentRoute();
  const render = PAGES[route];
  replace(shell.main, render ? render(state, { navigate }) : renderPlaceholder(route, routeLabel(route)));
}

function schedulePage() {
  if (pagePending) return;
  pagePending = true;
  const wait = Math.max(0, PAGE_INTERVAL_MS - (Date.now() - lastPageAt));
  setTimeout(() => requestAnimationFrame(renderPage), wait);
}

function changed() {
  shell.update(state);
  schedulePage();
}

window.addEventListener('hashchange', () => {
  const route = currentRoute();
  shell.setRoute(route);
  document.title = `${routeLabel(route)} · Robot Web`;
  lastPageAt = 0;
  renderPage();
  shell.main.focus({ preventScroll: true });
});

new StatusStream(
  (snap) => { state.snap = snap; changed(); },
  (connected) => { state.connected = connected; changed(); },
).start();

poll(async () => { state.sched = await api('GET', '/api/schedule/status'); changed(); }, 5000);
poll(async () => {
  const list = await api('GET', '/api/schedule/list');
  state.schedules = Array.isArray(list) ? list : (list?.schedules || []);
  changed();
}, 30000);
poll(async () => {
  const data = await api('GET', '/api/motor-events?category=all&limit=6');
  state.events = Array.isArray(data?.events) ? data.events : [];
  changed();
}, 10000);

shell.setRoute(currentRoute());
document.title = `${routeLabel(currentRoute())} · Robot Web`;
changed();
