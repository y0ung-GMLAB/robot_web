// 운영 시간이 끝나면 · 기준점 주차 → 서보 OFF · 수정 목록 36 (2026-10-06)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { scheduleEndText } from '../static/js/schedule_scope.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('the last schedule-end result is shown as one line', () => {
  assert.equal(scheduleEndText({ state: 'idle', message: '' }), '');
  assert.equal(scheduleEndText({}), '');
  assert.equal(
    scheduleEndText({ state: 'failed', message: '스케줄 끝 · 서보를 끄지 않고 그대로 둠 · Servo 알람 2등급' }),
    '스케줄 끝 · 서보를 끄지 않고 그대로 둠 · Servo 알람 2등급',
  );
});

test('the schedule window saves the end action as a project setting', () => {
  const html = read('../static/panels/11-modals.html');
  const manager = read('../static/js/schedule_manager.js');
  assert.match(html, /id="scheduleEndAction"/);
  assert.match(html, /value="park_servo_off"/);
  assert.match(html, /value="hold"/);
  assert.match(manager, /configureMotionAutomation\(\{ schedule_end_action: action \}\)/);
});

test('each motor can stay powered at schedule end', () => {
  const motorConfig = read('../static/js/motor_config.js');
  assert.match(motorConfig, /const SCHEDULE_END_FIELD = 'schedule_end_servo_off'/);
  // 켬이 기본 · 끌 때만 false 를 적는다
  assert.match(motorConfig, /if \(value === false\) config\[field\] = false;\s*else delete config\[field\];/);
  assert.match(motorConfig, /setAxisEditValue\(row, field, Boolean\(input\.checked\)\)/);
});

// supervisor 응답 없음 · 상단 빨간 칸 · 수정 목록 29
import { motionHeaderConditionCells } from '../static/js/header_conditions.js';

test('the top bar shows a red cell only while the supervisor is silent', () => {
  const ok = motionHeaderConditionCells({ enabled: true, joined: true, inWindow: true, supervisorProblem: '' });
  assert.equal(ok.length, 2);
  const silent = motionHeaderConditionCells({
    enabled: true, joined: false, inWindow: false, supervisorProblem: 'supervisor 응답 없음 · 4초째',
  });
  const cell = silent.find((item) => item.key === 'supervisor');
  assert.equal(cell.bad, true);
  assert.equal(cell.text, '모터 제어 응답 없음');
  assert.match(cell.title, /4초째/);
});

// MINAS 드라이브 정비 버튼 · 수정 목록 15 + 34-3
test('MINAS rows offer EEPROM save, absolute mode and multi-turn clear', () => {
  const motorConfig = read('../static/js/motor_config.js');
  const api = read('../static/js/api.js');
  for (const action of ['eeprom_save', 'absolute_mode', 'absolute_clear']) {
    assert.match(motorConfig, new RegExp(`data-axis-maintenance="${action}"`));
  }
  assert.match(motorConfig, /const payload = \{ action, axis, confirmed: true \};/);
  assert.match(api, /'\/api\/motor-config\/drive-maintenance'/);
});

// 프로젝트 백업·복원·휴지통 · 수정 목록 33
test('the project panel offers zip backup, zip restore and a trash with restore', () => {
  const html = read('../static/panels/03b-panel-project.html');
  const explorer = read('../static/js/project_explorer.js');
  const api = read('../static/js/api.js');
  for (const id of ['projectExportButton', 'projectImportZipButton', 'projectImportZipInput', 'projectTrashButton']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(api, /\/api\/project-import/);
  assert.match(api, /\/api\/project-trash/);
  // 같은 프로젝트가 있으면 확인 뒤에만 덮어쓴다
  assert.match(explorer, /if \(confirmed\) await restoreFromZip\(file, true\);/);
  assert.match(explorer, /휴지통으로 옮깁니다/);
});
