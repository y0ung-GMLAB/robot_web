/** UI v2 · 아직 안 만든 화면 · 지금 UI 에서 하도록 안내 (v2 는 뼈대 + 홈부터) */
import { h } from '../dom.js';

const OLD_PLACE = {
  play: '실행 › 애니메이션 재생 (매장 전체는 실행 › PC 연동 설정)',
  schedule: '상단 「📅 재생 스케줄」',
  store: '실행 › PC 연동 설정',
  animations: '실행 › 애니메이션 재생',
  manual: '실행 › 수동 조작',
  'maintain-motors': '설정 › 모터 관리',
  mapping: '설정 › 모터 관리 › 조인트 매핑',
  pack: '설정 › 시스템 정보 › 로봇 팩',
  alarms: '운영 › 서보 에러 관리',
  network: '설정 › 시스템 정보',
  backup: '설정 › 프로젝트 관리',
  records: '운영 › 재생 기록 · 로그',
  tools: '운영 › 터미널 · PC 성능',
  docs: '운영 › 사용법',
};

export function renderPlaceholder(route, label) {
  return [
    h('section', { class: 'card placeholder', 'aria-label': label },
      h('h1', { text: label }),
      h('p', { text: '이 화면은 새 UI 에서 아직 만드는 중입니다.' }),
      h('p', { class: 'muted', text: `지금은 기존 화면의 「${OLD_PLACE[route] || label}」 에서 하면 됩니다.` }),
      h('div', { class: 'row' }, h('a', { class: 'btn btn-primary', href: '/' }, '기존 화면 열기'))),
  ];
}
