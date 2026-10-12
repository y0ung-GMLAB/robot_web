/** UI v2 · 애니메이션 화면 값 · 검사 칸 · 범위 넘음 · 재생 목록 칸 · 그래프 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { checkState, factLine, fileRows, mappedCount, mujocoState, playlistSlots, rangeIssues, seriesGeometry } from '../static/v2/js/anim_model.js';

const R = Math.PI / 180;
const mapping = { mappings: [
  { motion_id: 'A', motion_lower_rad: -10 * R, motion_upper_rad: 13 * R },
  { motion_id: 'B', motion_lower_rad: -5 * R, motion_upper_rad: 5 * R },
  { motion_id: 'off', enabled: false, motion_lower_rad: 0, motion_upper_rad: 0 },
] };
const analysis = { valid: true, motion_ids: [
  { motion_id: 'A', min_value: -20 * R, max_value: 20 * R },
  { motion_id: 'B', min_value: -5 * R, max_value: (5 + 1e-7) * R },
  { motion_id: 'X', min_value: -90 * R, max_value: 90 * R },
] };

test('범위 넘음 · 이 PC 매핑에 있는 것만 · 반올림 정도는 넘음 아님', () => {
  const issues = rangeIssues(analysis, mapping);
  assert.deepEqual(issues.map((i) => i.id), ['A']);
  assert.ok(Math.abs(issues[0].over - 10) < 1e-9);
  assert.deepEqual(mappedCount(analysis, mapping), { total: 3, mapped: 2 });
});

test('검사 칸 · 오류 > 범위 넘음 > 이 PC 조인트 없음 > 경고 > 정상', () => {
  assert.deepEqual(checkState({ analysis: { valid: false, errors: ['헤더 없음'] } }, mapping), { text: '오류 · 헤더 없음', tone: 'bad' });
  assert.equal(checkState({ analysis }, mapping).text, '경고 · 범위 초과 1');
  assert.equal(checkState({ analysis: { valid: true, motion_ids: [{ motion_id: 'X', min_value: 0, max_value: 0 }] } }, mapping).text, '경고 · 매핑된 조인트 없음');
  assert.equal(checkState({ analysis: { valid: true, motion_ids: [], warnings: ['보간 필요'] } }, mapping).text, '경고 · 보간 필요');
  assert.equal(checkState({ analysis: { valid: true, motion_ids: [{ motion_id: 'A', min_value: 0, max_value: 0 }] } }, mapping).tone, 'ok');
  assert.equal(checkState({}, mapping).text, '검사 전');
});

test('3D 계산 · 재생 목록 칸 · 줄 정렬', () => {
  assert.equal(mujocoState({ preview: { state: 'stale' } }).text, '다시 계산 필요');
  assert.equal(mujocoState({}).text, '-');
  assert.equal(playlistSlots('a', ['a', 'b', 'a']), '1·3번');
  assert.equal(playlistSlots('c', ['a']), '–');
  const rows = fileRows([{ id: 'b.json', analysis: { valid: true, time: { duration_sec: 556 } } }, { id: 'a.json' }], { playlist: ['b.json'] });
  assert.deepEqual(rows.map((r) => [r.name, r.duration, r.slots]), [['a.json', '-', '–'], ['b.json', '9:16', '1번']]);
});

test('머리 한 줄 · 길이 · fps · 프레임', () => {
  assert.equal(factLine({ time: { duration_sec: 556 }, interpolation: { period_sec: 0.02, sample_count: 27802 } }), '길이 9:16 · 50 fps · 27,802 프레임');
});

test('그래프 · 범위 선도 보이게 세로 폭 · 값은 deg', () => {
  const geo = seriesGeometry([{ time_sec: 0, value: 0 }, { time_sec: 1, value: 2 * R }], { width: 100, height: 50, lower: -10, upper: 10 });
  assert.ok(geo.line.startsWith('M0.0,'));
  assert.ok(geo.lowerY > geo.upperY, '아래 선이 화면 아래');
  assert.ok(geo.lowerY <= 50 && geo.upperY >= 0);
  assert.ok(Math.abs(geo.max - 2) < 1e-9);
  assert.equal(seriesGeometry([]), null);
});
