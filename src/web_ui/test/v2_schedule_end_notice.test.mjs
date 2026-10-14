/** UI v2 · 구간 끝 주차 실패 · 그 자리에서 서보 끔 알림 · 수정 목록 131 (실물 V-19 · 2026-10-13) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { collectIssues, scheduleEndNotice } from '../static/v2/js/model.js';

const retrying = {
  state: 'retry_wait',
  notice: { tone: 'warn', title: '구간 끝 주차 실패 · 1/3회', detail: '기준점 이동 거절 · 실행 컨텍스트 적용 대기 · 약 1분 뒤 다시 시도합니다.' },
};
const keptOn = {
  state: 'gave_up',
  notice: { tone: 'bad', title: '구간 끝 주차 못 함 · 서보가 켜진 채입니다', detail: '서보 알람 2등급이라 서보 끄기는 알람 처리에 맡김' },
};

test('다시 시도 중 · 노랑 · 스케줄 열기', () => {
  const issue = collectIssues({ schedule_end: retrying }).find((i) => i.title === retrying.notice.title);
  assert.ok(issue, '확인할 일에 있다');
  assert.equal(issue.tone, 'warn');
  assert.match(issue.detail, /1분 뒤 다시/);
  assert.deepEqual(issue.action, { kind: 'open', target: 'schedule', label: '스케줄 열기' });
});

test('서보가 켜진 채 포기 · 빨강 · 맨 앞', () => {
  const issues = collectIssues({ schedule_end: keptOn, boot_params: { state: 'stale', message: '설정 적용 필요' } });
  assert.equal(issues[0].title, keptOn.notice.title);
  assert.equal(issues[0].tone, 'bad');
});

test('알림 없음 · 끝났거나 풀림 · 아무것도 안 띄움', () => {
  assert.equal(scheduleEndNotice({ schedule_end: { state: 'done', message: '운영 종료 · 기준점 이동 후 서보 OFF' } }), null);
  assert.equal(scheduleEndNotice({ schedule_end: { notice: null } }), null);
  assert.equal(scheduleEndNotice({}), null);
  assert.equal(collectIssues({ schedule_end: { state: 'cancelled' } }).length, 0);
});

test('스케줄 화면도 같은 알림 줄 · 서버 칸 schedule_end_notice', () => {
  const page = readFileSync(new URL('../static/v2/js/pages/schedule.js', import.meta.url), 'utf8');
  assert.match(page, /sched\.schedule_end_notice\?\.title/);
});
