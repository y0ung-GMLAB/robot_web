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
import { loadPlay, renderPlay } from './pages/play.js';

const state = { snap: null, sched: null, schedules: [], events: [], connected: false };
/** 화면 · render 는 상태로 그리기만 · load 는 그 화면만 쓰는 값을 받아 온다(들어올 때 + reloadMs 마다) */
const PAGES = {
  home: { render: renderHome },
  play: { render: renderPlay, load: loadPlay, reloadMs: 15000 },
};
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
  const page = PAGES[route];
  replace(shell.main, page ? page.render(state, { navigate, changed }) : renderPlaceholder(route, routeLabel(route)));
}

let loadTimer = null;
function startLoading(route) {
  clearInterval(loadTimer);
  loadTimer = null;
  const page = PAGES[route];
  if (!page?.load) return;
  page.load(state, changed);
  if (page.reloadMs) {
    loadTimer = setInterval(() => { if (!document.hidden) page.load(state, changed); }, page.reloadMs);
  }
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
  startLoading(route);
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
startLoading(currentRoute());
document.title = `${routeLabel(currentRoute())} · Robot Web`;
changed();
