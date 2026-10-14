/** UI v2 · 다회전 클리어 뒤 기준점 다시 지정 · 확인할 일 · 재생 막힘 · 앱솔루트 설정 끝 · 기준점 화면 (수정 목록 140) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { collectIssues, referenceRedoView } from '../static/v2/js/model.js';
import { absoluteClearRule, absoluteJobText } from '../static/v2/js/motors_model.js';
import { startBlocker } from '../static/v2/js/play_model.js';
import { capturePatch, hashAxis, notAlignedAxes } from '../static/v2/js/pages/manual.js';

const PROMPT = '다회전 클리어한 1번 모터 · 몸을 정면·수평에 맞추고 기준점을 다시 지정해 저장하세요';
const snap = {
  multiturn_clear: {
    blocked_axes: [1], pending_axes: [1], stale_axes: [],
    message: '1번 모터 다회전 클리어 뒤 기준점 다시 지정 필요', prompt: PROMPT,
  },
};

test('확인할 일 · 웹을 다시 켜도 표시가 남아 같은 안내 · 버튼은 그 축 기준점 화면', () => {
  assert.equal(referenceRedoView({}), null);
  assert.equal(referenceRedoView({ multiturn_clear: { blocked_axes: [] } }), null);
  const view = referenceRedoView(snap);
  assert.deepEqual(view.axes, [1]);
  assert.equal(view.target, 'manual?axis=1');
  const issue = collectIssues(snap, {}).find((item) => item.title === PROMPT);
  assert.ok(issue, '확인할 일에 나온다');
  assert.equal(issue.tone, 'bad');
  assert.deepEqual(issue.action, { kind: 'open', target: 'manual?axis=1', label: '기준점 지정 열기' });
  assert.match(issue.detail, /수동 조작은 됩니다/);
});

test('재생 화면 · 서버 글 그대로 막고 · 그 축 기준점 화면으로', () => {
  const blocker = startBlocker({ ...snap, execution_context: { ready: true } }, { run_mode: 'manual' }, { scope: 'local', playlist: ['a.json'], mappingId: 'm.yaml' });
  assert.equal(blocker.text, '1번 모터 다회전 클리어 뒤 기준점 다시 지정 필요');
  assert.equal(blocker.fix, 'open:manual?axis=1');
});

test('앱솔루트 설정 끝 · 클리어했으면 「완료」 가 아니라 기준점 다시 지정 대기 · 확인 창은 Err40 규칙', () => {
  const text = absoluteJobText({ state: 'reference_pending', step_index: 7, step_count: 7, step_label: '최종 확인', message: PROMPT });
  assert.match(text, /^앱솔루트 설정 · 기준점 다시 지정 대기 · 7\/7/);
  assert.match(text, /몸을 정면·수평에 맞추고 기준점을 다시 지정해 저장하세요/);
  assert.match(absoluteJobText({ state: 'done', step_index: 7, step_count: 7, message: '앱솔루트 설정을 마쳤습니다 · 다회전 정상 · 클리어 안 함 · 기준점 그대로' }),
    /^앱솔루트 설정 완료 · 7\/7 · .*클리어 안 함 · 기준점 그대로/);
  const rule = absoluteClearRule();
  assert.match(rule, /Err40\(다회전 무효\)인 드라이브만/);
  assert.match(rule, /Err40이 없으면 클리어하지 않고 기준점도 그대로/);
  assert.match(rule, /감속 있는 축은 기준점을 눈으로 다시 맞춰야 합니다 · 모든 프로젝트/);
  const motors = readFileSync(new URL('../static/v2/js/pages/motors.js', import.meta.url), 'utf8');
  assert.match(motors, /absoluteClearRule\(\)/, '앱솔루트 설정 확인 창이 규칙을 쓴다');
  assert.match(motors, /모든 프로젝트의 이 축 기준점이 무효가 됩니다\(감속 있는 축은 눈으로 다시 맞춤\)/, '클리어만 하는 길 확인 창');
  assert.match(motors, /reference_pending' \? referenceButton/, '끝나면 기준점 지정으로 바로');
});

test('기준점 화면 · 주소의 축 · 「클리어 뒤 아직 안 맞춤」 · 캡처는 지정 표시를 보낸다', () => {
  assert.equal(hashAxis('#/manual?axis=3'), 3);
  assert.equal(hashAxis('#/manual'), null);
  assert.equal(hashAxis('#/manual?axis='), null);
  assert.deepEqual([...notAlignedAxes(snap)], [1]);
  assert.deepEqual([...notAlignedAxes({})], []);
  const plan = capturePatch({ motion_id: 'neck', gear_ratio: 20, reference_position_deg: 0 }, 'reference', 12.5);
  assert.equal(plan.patch.reference_captured, true, '값이 같아도 「지금 지정함」 · 서버가 지정 시각을 적는다');
  const manual = readFileSync(new URL('../static/v2/js/pages/manual.js', import.meta.url), 'utf8');
  assert.match(manual, /클리어 뒤 아직 안 맞춤/);
  const mapping = readFileSync(new URL('../static/v2/js/pages/mapping.js', import.meta.url), 'utf8');
  assert.match(mapping, /reference_captured = true/, '조인트 매핑 표의 캡처도');
});
