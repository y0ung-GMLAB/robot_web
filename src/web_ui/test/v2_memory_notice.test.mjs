/** 메모리 부족 알림 · 확인할 일 · PC 현황 칸 · 수정 목록 170 (NY 2026-11-03 · 스왑 1.25 GB 에서 실행기가 멈췄다) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { collectIssues, memoryCell, memoryNotice } from '../static/v2/js/model.js';

const healthy = { available: true, low: false, reasons: [], available_mb: 1800, total_mb: 4700, swap_used_mb: 600, swap_total_mb: 2048 };
const low = { ...healthy, low: true, available_mb: 420, swap_used_mb: 1250, reasons: ['남은 메모리 420 MB', '스왑 1250 MB'] };

test('서버가 low 라고 할 때만 · 제목에 스왑 MB', () => {
  assert.equal(memoryNotice(healthy), null);
  assert.equal(memoryNotice(undefined), null);
  assert.equal(memoryNotice({ available: false, low: true }), null);
  const notice = memoryNotice(low);
  assert.equal(notice.title, '메모리 부족 · 스왑 1250 MB');
  assert.match(notice.detail, /남은 메모리 420 MB · 스왑 1250 MB/);
});

test('확인할 일에 경고로 · 스케줄 상태의 memory 칸 · PC 성능 화면 버튼', () => {
  const snap = { motion_state: { motors: [] } };
  assert.equal(collectIssues(snap, { memory: healthy }).length, 0);
  const [issue] = collectIssues(snap, { memory: low });
  assert.equal(issue.tone, 'warn');
  assert.equal(issue.title, '메모리 부족 · 스왑 1250 MB');
  assert.deepEqual(issue.action, { kind: 'open', target: 'tools', label: 'PC 성능 열기' });
});

test('PC 현황 칸 · 옛 버전 PC(칸 없음)는 -', () => {
  assert.deepEqual(memoryCell(undefined), { tone: 'muted', text: '-' });
  assert.deepEqual(memoryCell(healthy), { tone: 'ok', text: '남은 1.8 GB · 스왑 600 MB' });
  assert.deepEqual(memoryCell(low), { tone: 'warn', text: '메모리 부족 · 남은 420 MB · 스왑 1250 MB' });
});

test('PC 현황 운전 모드 표에 메모리 칸', () => {
  const source = readFileSync(new URL('../static/v2/js/pages/store.js', import.meta.url), 'utf8');
  assert.match(source, /'PC', '지금', '전환', '메모리'/);
  assert.match(source, /memoryTd\(pc\.memory\)/);
});
