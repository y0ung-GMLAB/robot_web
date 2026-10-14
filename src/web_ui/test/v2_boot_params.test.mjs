/** UI v2 · 옛 부팅 값 알림 · 수정 목록 116 (실물 2026-10-13) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { bootParamsNotice, collectIssues } from '../static/v2/js/model.js';
import { setupStatus } from '../static/v2/js/pages/motor_setup.js';
import { rowFlags } from '../static/v2/js/pages/drive_params.js';

const stale = {
  state: 'stale', message: '설정 적용 필요 · 지금 드라이브는 옛 부팅 값',
  detail: '0번 Pr4.37 없음 → 150 · 0번 Pr5.12 50 → 0',
};
const applied = { runtime_matches_selected: true, motor_config_applied: true };

test('옛 부팅 값 · 홈 확인할 일 · 「장비에 적용」 버튼', () => {
  const issues = collectIssues({ boot_params: stale });
  const issue = issues.find((i) => i.title === stale.message);
  assert.ok(issue, '확인할 일에 있다');
  assert.equal(issue.tone, 'warn');
  assert.deepEqual(issue.action, { kind: 'apply-motor-config', label: '장비에 적용' });
  assert.match(issue.detail, /Pr5\.12 50 → 0/);
  assert.equal(bootParamsNotice({ boot_params: { state: 'ok' } }), null);
  assert.equal(bootParamsNotice({ boot_params: { state: 'none' } }), null);
  assert.equal(bootParamsNotice({}), null);
});

test('옛 부팅 값 · 모터 설정 머리 칩은 「적용됨」 이 아니다', () => {
  const status = setupStatus({ project_scope: applied, boot_params: stale });
  assert.deepEqual(status.apply, [stale.message, 'warn']);
  assert.ok(status.boot);
  assert.deepEqual(setupStatus({ project_scope: applied, boot_params: { state: 'ok' } }).apply, ['장비에 적용됨', 'ok']);
});

test('홈 · 모터 설정의 버튼이 실제로 적용을 부른다', () => {
  const shell = readFileSync(new URL('../static/v2/js/shell.js', import.meta.url), 'utf8');
  assert.match(shell, /'apply-motor-config': act\.applyBootParams/);
  const actions = readFileSync(new URL('../static/v2/js/actions.js', import.meta.url), 'utf8');
  assert.match(actions, /export async function applyBootParams\(\) \{\n {2}if \(!\(await confirmApplyMotorConfig\(/);
});

test('고급 표 · 적용하면 바뀔 값 표시 · 같으면 없음', () => {
  const flags = rowFlags({ boot: 0, boot_next: 150, differs_boot: false, differs_factory: false });
  assert.deepEqual(flags.map((f) => f.text), ['적용하면 150']);
  assert.deepEqual(rowFlags({ boot: 0, boot_next: null }), []);
});
