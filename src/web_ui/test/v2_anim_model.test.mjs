/** UI v2 · 애니메이션 화면 값 · 검사 칸 · 범위 넘음 · 재생 목록 칸 · 그래프 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { checkState, factLine, fileRows, graphSeriesView, mappedCount, mujocoState, playlistSlots, rangeIssues, seriesGeometry } from '../static/v2/js/anim_model.js';

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
  assert.equal(checkState({ analysis }, mapping).text, '경고 · 범위 초과 1개');
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

test('그래프 12 개 넘음 · 「20 개 중 12 개」 + 「나머지 보기」 ↔ 「접기」 · 수정 목록 138', () => {
  const one = (id) => ({ motion_id: id, points: [{ time_sec: 0, value: 0 }] });
  const ids = Array.from({ length: 20 }, (_, i) => `f${Math.floor(i / 5) + 1}-${(i % 5) + 1}`);
  const narration = { graph_series: ids.slice(0, 12).map(one), graph_series_extra: ids.slice(12).map(one), graph_series_total: 20 };

  const closed = graphSeriesView(narration, false);
  assert.equal(closed.series.length, 12);
  assert.equal(closed.note, '20 개 중 12 개');
  assert.equal(closed.toggle, '나머지 보기');

  const open = graphSeriesView(narration, true);
  assert.deepEqual(open.series.map((s) => s.motion_id), ids, '나머지 8 개가 뒤에 · 이름 순 그대로');
  assert.equal(open.note, '20 개 모두');
  assert.equal(open.toggle, '접기');

  // 12 개 이하 · 줄 자체가 없다
  assert.deepEqual(graphSeriesView({ graph_series: [one('a')], graph_series_extra: [], graph_series_total: 1 }), { series: [one('a')], note: '', toggle: '' });
  // 옛 서버(칸 없음) · 상세 전
  assert.deepEqual(graphSeriesView(null), { series: [], note: '', toggle: '' });
  // 개수만 알고 나머지가 안 왔으면 안내만 · 누를 버튼은 없다
  assert.deepEqual(graphSeriesView({ graph_series: narration.graph_series, graph_series_total: 20 }, true),
    { series: narration.graph_series, note: '20 개 중 12 개', toggle: '' });
});

test('애니메이션 화면 · 펼침은 파일마다 ui 에 기억 · 버튼이 그것을 뒤집는다 (0.5 초 다시 그리기에도 유지)', () => {
  const src = readFileSync(new URL('../static/v2/js/pages/animations.js', import.meta.url), 'utf8');
  assert.match(src, /graphsOpen: new Set\(\)/);
  assert.match(src, /const graphsOpen = ui\.graphsOpen\.has\(ui\.selected\);/);
  assert.match(src, /graphSeriesView\([^;]*graphsOpen\)/);
  assert.match(src, /onclick: \(\) => \{ toggleGraphs\(file\.id\); changed\(\); \}/);
  assert.match(src, /'aria-expanded': String\(graphsOpen\)/);
});
