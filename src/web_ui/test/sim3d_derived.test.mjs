// 수정 목록 159 · 파생 관절 표 · json 값 → 노드 TRS · 다중선형 · 쿼터니언 nlerp · 격자 밖 clamp
import assert from 'node:assert/strict';
import test from 'node:test';

import { decodeFloat32Base64, prepareDerived, sampleDerivedTable } from '../static/js/sim3d_math.js';

function b64(values) {
  const buffer = Buffer.alloc(values.length * 4);
  values.forEach((value, index) => buffer.writeFloatLE(value, index * 4));
  return buffer.toString('base64');
}

const close = (a, b, eps = 1e-5) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

function zQuat(angle) {
  return [0, 0, Math.sin(angle / 2), Math.cos(angle / 2)];
}

test('base64 float32 little-endian', () => {
  const out = decodeFloat32Base64(b64([1.5, -2, 0.25]));
  assert.deepEqual([...out], [1.5, -2, 0.25]);
});

test('1D · 위치·크기 선형 · 회전 nlerp · 끝 밖은 clamp · 없는 입력은 0', () => {
  // 입력 a · −1 .. 1 · 3점 · 노드 1개 · t.x = 입력 · 회전 Z = 입력 · 크기 x = 1 + 입력
  const values = [];
  for (const v of [-1, 0, 1]) values.push(v, 0, 0, ...zQuat(v), 1 + v, 1, 1);
  const [table] = prepareDerived({ version: 1, tables: [{ inputs: ['a'], grid: [{ min: -1, max: 1, n: 3 }], nodes: ['N'], channels: 'trs', values_b64: b64(values) }] });
  const [mid] = sampleDerivedTable(table, { a: 0.5 });
  close(mid.t[0], 0.5);
  close(mid.s[0], 1.5);
  const angle = 2 * Math.atan2(mid.q[2], mid.q[3]);
  close(angle, 0.5, 0.01); // nlerp 는 각 속도만 조금 다르다
  close(Math.hypot(...mid.q), 1);
  const [over] = sampleDerivedTable(table, { a: 9 });
  close(over.t[0], 1);
  const [missing] = sampleDerivedTable(table, {});
  close(missing.t[0], 0);
});

test('2D · 마지막 입력이 가장 빠른 순서 · 쌍선형', () => {
  // 입력 a(2점) · b(3점) · 값 = t.x = 10a + b
  const values = [];
  for (const a of [0, 1]) for (const b of [0, 1, 2]) values.push(10 * a + b, 0, 0, 0, 0, 0, 1, 1, 1, 1);
  const [table] = prepareDerived({ version: 1, tables: [{ inputs: ['a', 'b'], grid: [{ min: 0, max: 1, n: 2 }, { min: 0, max: 2, n: 3 }], nodes: ['N'], channels: 'trs', values_b64: b64(values) }] });
  close(sampleDerivedTable(table, { a: 0.5, b: 1.5 })[0].t[0], 6.5);
  close(sampleDerivedTable(table, { a: 1, b: 2 })[0].t[0], 12);
});

test('회전 표(r) · 반대 부호 쿼터니언도 같은 회전으로 보간 · 위치·크기는 null', () => {
  const q = zQuat(0.4);
  const values = [...q, ...q.map((value) => -value)];
  const [table] = prepareDerived({ version: 1, tables: [{ inputs: ['a'], grid: [{ min: 0, max: 1, n: 2 }], nodes: ['N'], channels: 'r', values_b64: b64(values) }] });
  const [pose] = sampleDerivedTable(table, { a: 0.5 });
  assert.equal(pose.t, null);
  assert.equal(pose.s, null);
  close(Math.abs(pose.q[2]), Math.abs(q[2]));
  close(Math.abs(pose.q[3]), Math.abs(q[3]));
});

test('모양이 틀린 표는 던진다', () => {
  assert.throws(() => prepareDerived({ version: 2, tables: [] }));
  assert.throws(() => prepareDerived({ version: 1, tables: [{ inputs: ['a'], grid: [{ min: 0, max: 1, n: 2 }], nodes: ['N'], channels: 'r', values_b64: b64([0, 0, 0, 1]) }] }));
});
