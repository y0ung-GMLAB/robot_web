/** UI v2 · 사용법 · 저장소 문서(사용법 · 설치법)를 화면에서 (설계안 2026-10-09 · 기존 §6-157 과 같은 문서)
 *
 * 본문은 문서마다 한 번만 만든다 · 화면은 0.5초마다 다시 그리는데 1000줄 문서를 그때마다 만들면 무겁다.
 * 문서 안 링크(#…)는 주소창 대신 그 자리로 스크롤 · 주소창의 # 은 화면 이동에 쓴다.
 */
import { h } from '../dom.js';
import { outline, renderMarkdown, searchSections } from '../markdown.js';
import { api } from '../net.js';

const ui = { query: '', built: null, builtKey: '' };

export async function loadDocs(state, changed) {
  const page = state.docsPage || (state.docsPage = { documents: [], active: '', doc: null, error: '' });
  try {
    const list = await api('GET', '/api/docs');
    page.documents = Array.isArray(list?.documents) ? list.documents : [];
    if (!page.active || !page.documents.some((d) => d.id === page.active)) {
      page.active = (page.documents.find((d) => d.available) || page.documents[0])?.id || '';
    }
    page.error = '';
    if (page.active && (!page.doc || page.doc.id !== page.active)) await openDoc(state, changed, page.active);
  } catch (error) {
    page.error = error.message || String(error);
  }
  changed();
}

async function openDoc(state, changed, id, force = false) {
  const page = state.docsPage;
  page.active = id;
  if (force) ui.builtKey = '';
  try {
    // 파일이 없으면 서버가 success:false 로 이유를 준다 · 오류가 아니라 「아직 없음」(§6-157)
    const response = await fetch(`/api/docs/${encodeURIComponent(id)}`, { headers: { Accept: 'application/json' } });
    const data = await response.json();
    page.doc = { id, title: data.title || id, markdown: String(data.markdown || ''), message: data.success === false ? String(data.message || '') : '' };
  } catch (error) {
    page.doc = { id, title: id, markdown: '', message: error.message || String(error) };
  }
  changed();
}

function scrollTo(id) {
  const target = document.getElementById(id);
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function article(doc) {
  const key = `${doc.id}:${doc.markdown.length}:${doc.markdown.slice(0, 64)}`;
  if (ui.builtKey !== key) {
    ui.built = h('article', { class: 'doc', onclick: (event) => {
      const link = event.target.closest('a[data-anchor]');
      if (!link) return;
      event.preventDefault();
      scrollTo(link.getAttribute('href').slice(1));
    } }, renderMarkdown(doc.markdown, { imageBase: '/api/docs/images/' }));
    ui.builtKey = key;
  }
  return ui.built;
}

export function renderDocs(state, { changed }) {
  const page = state.docsPage || {};
  const doc = page.doc && page.doc.id === page.active ? page.doc : null;
  const toc = doc ? outline(doc.markdown) : [];
  const hits = doc && ui.query ? searchSections(doc.markdown, ui.query) : [];
  const jumpList = ui.query ? hits.map((hit) => ({ ...hit, level: 2, label: `${hit.text} · ${hit.count}` })) : toc.map((item) => ({ ...item, label: item.text }));
  return [
    h('div', { class: 'page-head' },
      h('h1', { text: '사용법' }),
      h('div', { class: 'segmented', role: 'tablist', 'aria-label': '문서' },
        (page.documents || []).map((d) => h('button', {
          class: 'seg', type: 'button', role: 'tab', 'aria-selected': String(d.id === page.active), 'aria-pressed': String(d.id === page.active),
          title: d.available ? (d.subtitle || '') : `${d.source} 파일이 없습니다`,
          onclick: () => { ui.query = ''; openDoc(state, changed, d.id); },
        }, d.title))),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn', type: 'button', disabled: !page.active, title: '업데이트로 문서가 바뀌었다면 다시 불러옵니다',
        onclick: () => openDoc(state, changed, page.active, true) }, '새로 고침')),
    page.error ? h('p', { class: 'tone-text-bad', text: page.error }) : null,
    h('div', { class: 'docs-layout' },
      h('nav', { class: 'card docs-outline', 'aria-label': '목차' },
        h('input', { class: 'input', type: 'search', placeholder: '문서 검색', value: ui.query, 'aria-label': '문서 검색',
          oninput: (event) => { ui.query = event.target.value; },
          onkeydown: (event) => { if (event.key === 'Enter') { event.target.blur(); changed(); } },
          onchange: () => changed() }),
        ui.query ? h('p', { class: 'muted small', text: hits.length ? `${hits.length}곳` : '없음' }) : null,
        h('ul', { class: 'outline-list' }, jumpList.map((item) => h('li', { class: `outline-${item.level}` },
          h('a', { href: `#${item.id}`, onclick: (event) => { event.preventDefault(); scrollTo(item.id); } }, item.label))))),
      h('div', { class: 'card docs-body' },
        !doc ? h('p', { class: 'muted', text: '불러오는 중…' })
          : doc.message ? h('p', { class: 'tone-text-warn', text: doc.message })
            : article(doc))),
  ];
}
