/** 프로그램 시작이 오래 안 끝남 · 확인할 일 · 판정은 서버(`startup.overdue`) · 수정 목록 202 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { collectIssues } from '../static/v2/js/model.js';

const base = { motion_state: { motors: [] } };
const overdue = {
  ready: false, waiting: ['재생 관리자'], elapsed_sec: 301, overdue: true,
  message: '재생 관리자 상태를 5분 동안 받지 못했습니다. 프로그램을 재시작하세요.',
};

test('시작 중(아직 안 뜸)은 확인할 일이 아니다', () => {
  const snap = { ...base, startup: { ready: false, waiting: ['supervisor'], elapsed_sec: 120, overdue: false, message: '' } };
  assert.equal(collectIssues(snap, {}).length, 0);
});

test('오래 안 끝나면 빨간 줄 · 프로그램 재시작 버튼', () => {
  const [issue] = collectIssues({ ...base, startup: overdue }, {});
  assert.equal(issue.tone, 'bad');
  assert.equal(issue.title, '프로그램 시작이 끝나지 않았습니다');
  assert.equal(issue.detail, overdue.message);
  assert.deepEqual(issue.action, { kind: 'restart-program', label: '프로그램 재시작' });
});

test('supervisor 쪽은 「모터 제어가 응답하지 않습니다」 한 줄만', () => {
  const snap = {
    ...base,
    startup: { ...overdue, waiting: ['supervisor'] },
    supervisor_watchdog: { message: 'supervisor 시작 안 됨 · 301초 동안 상태를 한 번도 받지 못함' },
  };
  const titles = collectIssues(snap, {}).map((issue) => issue.title);
  assert.deepEqual(titles, ['모터 제어가 응답하지 않습니다']);
});
