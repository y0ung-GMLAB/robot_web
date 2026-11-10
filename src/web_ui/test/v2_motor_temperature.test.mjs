/** 직렬 서보 온도 · 창 표 · 확인할 일 · 수정 목록 191 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { collectIssues, motorTemperatures } from '../static/v2/js/model.js';

const snapWith = (motors) => ({ motion_state: { motors } });
const ac = { controller_index: 0, motor_type: 'minas', temperature_c: null, temperature_limit_c: null };
const ft = (temp, limit = 70) => ({ controller_index: 4, motion_id: 'head_yaw', motor_type: 'feetech', temperature_c: temp, temperature_limit_c: limit });

test('온도를 읽는 축만 · AC 는 빠짐 · 여유 = 한계 - 온도', () => {
  const rows = motorTemperatures(snapWith([ac, ft(49)]));
  assert.equal(rows.length, 1);
  assert.deepEqual(
    [rows[0].index, rows[0].name, rows[0].tempText, rows[0].limitText, rows[0].marginText, rows[0].tone],
    [4, 'head_yaw', '49 °C', '70 °C', '21 °C', 'ok'],
  );
});

test('한계 10 °C 안 = warn · 3 °C 안 = bad · 통신 끊김(온도 없음) = muted', () => {
  assert.equal(motorTemperatures(snapWith([ft(60)]))[0].tone, 'warn');
  assert.equal(motorTemperatures(snapWith([ft(67)]))[0].tone, 'bad');
  const lost = motorTemperatures(snapWith([ft(null)]))[0];
  assert.equal(lost.tone, 'muted');
  assert.equal(lost.tempText, '-');
  // 한계를 모르면 색 없음
  assert.equal(motorTemperatures(snapWith([ft(99, null)]))[0].tone, 'ok');
});

test('확인할 일 · 한계 가까울 때만 · 버튼은 온도 창', () => {
  assert.equal(collectIssues(snapWith([ft(49)]), {}).filter((i) => i.title.includes('온도')).length, 0);
  const [issue] = collectIssues(snapWith([ft(61)]), {}).filter((i) => i.title.includes('온도'));
  assert.equal(issue.tone, 'warn');
  assert.match(issue.title, /4번 head_yaw 61 °C \(한계 70 °C\)/);
  assert.equal(issue.action.kind, 'open-temperature');
  const [hot] = collectIssues(snapWith([ft(68)]), {}).filter((i) => i.title.includes('온도'));
  assert.equal(hot.tone, 'bad');
});

test('직렬 서보는 온도가 안 들어와도 줄이 있다(「-」) · AC 는 없다 · 수정 목록 192', () => {
  const rows = motorTemperatures(snapWith([ac, { controller_index: 3, motor_type: 'dynamixel', motion_id: 'crank_r' }]));
  assert.deepEqual(rows.map((r) => [r.index, r.tempText, r.limitText, r.tone]), [[3, '-', '-', 'muted']]);
});
