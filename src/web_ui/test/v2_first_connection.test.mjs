/** UI v2 · 처음 연결 · 모터 설정 저장과 「인식 모터 자동 생성」 이 서로 막던 것 · 수정 목록 118 (실물 2026-10-13 S-3 · S-6)
 *  + 검색 확인 창 문구 = 실제 동작 · 저장 뒤 검색 알림 · 120 (사) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { blockReason } from '../static/v2/js/pages/motor_setup.js';
import { autoBuildReason } from '../static/v2/js/pages/mapping.js';
import { scanConfirmText } from '../static/v2/js/motors_model.js';

const MAPPING_SRC = readFileSync(new URL('../static/v2/js/pages/mapping.js', import.meta.url), 'utf8');
const SETUP_SRC = readFileSync(new URL('../static/v2/js/pages/motor_setup.js', import.meta.url), 'utf8');
const MOTORS_SRC = readFileSync(new URL('../static/v2/js/pages/motors.js', import.meta.url), 'utf8');

test('조인트 0개 · 매핑을 안 고쳤으면 매핑 검사로 모터 저장을 막지 않는다 · 고쳤으면 막는다', () => {
  const draft = MAPPING_SRC.slice(MAPPING_SRC.indexOf('export function mappingDraft'), MAPPING_SRC.indexOf('export function revertMapping'));
  assert.match(draft, /problems: changes\.length \? draftProblems\(ui\.rows\) : \[\]/);
});

test('막힌 저장 버튼마다 이유 툴팁 · 먼저 걸리는 것 하나', () => {
  assert.equal(blockReason({ busy: true, dirty: true, problems: ['x'] }, 'ok'), '저장·적용하는 중입니다');
  assert.equal(blockReason({ busy: false, dirty: true, problems: ['조인트가 하나도 없습니다'] }, 'ok'), '막힘 · 조인트가 하나도 없습니다');
  assert.equal(blockReason({ busy: false, dirty: false, problems: [] }, 'ok'), '바꾼 내용이 없습니다');
  assert.equal(blockReason({ busy: false, dirty: true, problems: [] }, 'ok'), 'ok');
  const bar = SETUP_SRC.slice(SETUP_SRC.indexOf("h('div', { class: 'apply-bar' }"));
  assert.equal((bar.match(/title: blockReason\(/g) || []).length, 3, '되돌리기 · 저장 · 저장 후 장비에 적용');
});

test('「인식 모터 자동 생성」 · 막혔으면 이유(다른 프로젝트로 돎 → 먼저 장비에 적용) · 버튼에 title', () => {
  const other = { snap: { project_scope: { runtime_matches_selected: false, runtime_project_id: 'floating4' } } };
  assert.match(autoBuildReason(other, 0), /「저장 후 장비에 적용」을 먼저/);
  assert.match(autoBuildReason(other, 0), /조인트 없이도 됩니다/);
  const same = { snap: { project_scope: { runtime_matches_selected: true } } };
  assert.match(autoBuildReason(same, 0), /모터 상태를 아직 보내지 않았습니다/);
  assert.match(autoBuildReason(same, 3), /3대마다 한 줄씩/);
  assert.match(MAPPING_SRC, /title: autoBuildReason\(state, motors\.length\)/);
});

test('검색 확인 창 · 다른 프로젝트로 돌던 모터 프로그램은 검색 뒤 다시 켜지 않는다고 말한다(서버 scan_orchestrator 와 같음)', () => {
  const other = scanConfirmText('all', { runtime_matches_selected: false, runtime_project_id: 'floating4' });
  assert.doesNotMatch(other, /다시 시작됩니다/);
  assert.match(other, /다른 프로젝트\(floating4\)/);
  assert.match(other, /검색 뒤에는 다시 켜지 않습니다/);
  const same = scanConfirmText('ac', { runtime_matches_selected: true });
  assert.match(same, /잠시 정지했다가 다시 시작됩니다/);
  assert.match(same, /검색하지 않은 종류의 모터는 그대로 둡니다/);
  const none = scanConfirmText('dxl', {}, { dirty: true });
  assert.doesNotMatch(none, /다시 시작됩니다/);
  assert.match(none, /저장하지 않은 변경 내용은 검색 결과로 대체됩니다/);
  assert.match(MOTORS_SRC, /body: scanConfirmText\(kind, state\.snap\?\.project_scope/);
});

test('저장 뒤에는 검색 알림 「아직 저장하지 않았습니다」 를 지운다 (수정 목록 120 (사))', () => {
  assert.match(MOTORS_SRC, /sum && dirty\(\) \? h\('p', \{ class: 'small muted', text: '아직 저장하지 않았습니다/);
});
