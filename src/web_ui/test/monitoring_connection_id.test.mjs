/** 실시간 모니터링 · 「연결 ID」는 무슨 번호인지 이름을 붙인다 · 2026-10-02
 *
 * 사용자 보고 · 「모터 번호」와 「ID」가 둘 다 숫자라 헷갈린다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../static/js/monitoring.js', import.meta.url), 'utf8');

// 모듈 밖으로 내보내지 않는 함수 · 본문을 꺼내 같은 도우미(motorFilterKey · formatInt)로 돌린다
const { formatInt, normalizeMotorTypeKey } = await import('../static/js/format.js');
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(name);
}
// eslint-disable-next-line no-new-func
const connectionIdLabel = new Function(
  'formatInt', 'normalizeMotorTypeKey',
  `${extract('motorFilterKey')}\n${extract('connectionIdLabel')}\nreturn connectionIdLabel;`,
)(formatInt, normalizeMotorTypeKey);

test('AC servo shows its EtherCAT alias by name', () => {
  assert.equal(connectionIdLabel({ motor_type: 'ac_servo', alias: 103, slave_position: 0 }), 'Alias 103');
});

test('alias 0 (not set) adds the ring position so motors differ', () => {
  assert.equal(connectionIdLabel({ motor_type: 'ac_servo', alias: 0, slave_position: 2 }), 'Alias 0 · Slave 2');
  assert.equal(connectionIdLabel({ motor_type: 'ac_servo', alias: 0 }), 'Alias 0');
});

test('Dynamixel shows its bus ID by name', () => {
  assert.equal(connectionIdLabel({ motor_type: 'dynamixel', bus_id: 3 }), 'ID 3');
});

test('unknown values stay a dash, never a bare number', () => {
  assert.equal(connectionIdLabel({ motor_type: 'ac_servo' }), '-');
  assert.equal(connectionIdLabel({ motor_type: 'dynamixel' }), '-');
});

test('the column and the detail say 연결 ID, not a bare ID', () => {
  assert.match(source, /label: '연결 ID'/);
  assert.match(source, /\['연결 ID', connectionIdLabel\(motor\)\]/);
  assert.doesNotMatch(source, /label: 'ID'/);
});
