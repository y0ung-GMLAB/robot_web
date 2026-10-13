/** UI v2 · 수동 조작 「기준점·하한점·상한점 지정」 이 매핑 파일에 들어간다 · 수정 목록 117 (실물 2026-10-13 S-7) */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { draftToRow, findRowIndex, patchRow, rowToDraft, savedMismatch } from '../static/v2/js/mapping_model.js';
import { capturePatch } from '../static/v2/js/pages/manual.js';

const R = Math.PI / 180;
const MANUAL_SRC = readFileSync(new URL('../static/v2/js/pages/manual.js', import.meta.url), 'utf8');
const server = [
  { motion_id: 'f4_eye_yaw_l', enabled: true, motor_axis: 0, motor_ref: 'ac_servo:master:0:slave:0', gear_ratio: 20, scale: 1, reference_position_rad: 0, motion_lower_rad: -12 * R, motion_upper_rad: 12 * R },
  { motion_id: 'f4_eye_yaw_r', enabled: true, motor_axis: 1, motor_ref: 'ac_servo:master:0:slave:1', gear_ratio: 20, scale: 1, reference_position_rad: 0, motion_lower_rad: -12 * R, motion_upper_rad: 12 * R },
];

test('매핑을 다시 불러온 뒤(새 객체)에도 같은 줄을 찾는다 · === 로 찾던 것이 원인', () => {
  const before = server.map(rowToDraft);
  const stale = before[1];
  const reloaded = server.map(rowToDraft);
  assert.equal(reloaded.indexOf(stale), -1, '옛 객체는 새 목록에 없다(실물에서 저장이 안 된 이유)');
  assert.equal(findRowIndex(reloaded, stale), 1);
  const plan = capturePatch(stale, 'reference', 39.95);
  const next = patchRow(reloaded, stale, plan.patch);
  assert.equal(next.index, 1);
  assert.equal(next.rows[1].reference_position_deg, 39.95);
  assert.equal(next.rows[0], reloaded[0], '다른 줄은 그대로');
  assert.ok(Math.abs(draftToRow(next.rows[1]).reference_position_rad - 39.95 * R) < 1e-9, '보내는 값 rad');
});

test('줄 찾기 · 이름 + 모터 · 모터가 바뀌었으면 이름이 하나일 때만 · 이름 없으면 못 찾음', () => {
  const rows = server.map(rowToDraft);
  assert.equal(findRowIndex(rows, { ...rows[0], motor_ref: '', motor_axis: 5 }), 0, '이름이 하나뿐');
  const twin = [...rows, { ...rows[0], motor_ref: '', motor_axis: 7 }];
  assert.equal(findRowIndex(twin, { motion_id: 'f4_eye_yaw_l', motor_ref: '', motor_axis: 9 }), -1, '같은 이름 둘 · 모터도 다르면 고르지 않음');
  assert.equal(findRowIndex(rows, { motion_id: '' }), -1);
  assert.equal(patchRow(rows, { motion_id: 'none' }, { reference_position_deg: 1 }), null);
});

test('하한·상한 · 안쪽으로 반올림 · 하한 > 상한이면 막음', () => {
  const row = rowToDraft(server[0]);
  assert.deepEqual(capturePatch(row, 'lower', -100.00004).patch, { motion_lower_deg: -5 });
  assert.equal(capturePatch(row, 'upper', 100.00004).patch.motion_upper_deg, 5);
  assert.match(capturePatch({ ...row, motion_upper_deg: -6 }, 'lower', -100).error, /하한이 상한보다/);
  assert.equal(capturePatch(row, 'reference', 12.345678).patch.reference_position_deg, 12.3457);
});

test('저장 뒤 확인 · 파일 값이 다르면 무엇이 다른지 · 같으면 빈 목록', () => {
  const target = rowToDraft(server[1]);
  const patch = { reference_position_deg: 39.95, reference_enabled: true };
  assert.deepEqual(savedMismatch([server[0], { ...server[1], reference_position_rad: 39.95 * R }], target, patch), []);
  const wrong = savedMismatch(server, target, patch);
  assert.equal(wrong.length, 1);
  assert.match(wrong[0], /기준점 · 보낸 값 39\.95 · 파일 값 0/);
  assert.match(savedMismatch([server[0]], target, patch)[0], /찾지 못했습니다/);
});

test('다이얼 한 칸 기본값 = 조인트 1° (수정 목록 126 · 120 (라))', () => {
  assert.match(MANUAL_SRC, /mode: 'axis', axis: null, unit: 'joint', dialOn: false, step: 1,/);
});

test('capture 는 객체 비교 대신 patchRow · 저장 뒤 다시 읽어 savedMismatch', () => {
  const body = MANUAL_SRC.slice(MANUAL_SRC.indexOf('async function capture('), MANUAL_SRC.indexOf('/* ---------- 그리기'));
  assert.doesNotMatch(body, /r === item\.row/);
  assert.match(body, /patchRow\(ui\.mapping/);
  assert.ok(body.indexOf("api('GET'") > body.indexOf("api('POST'"), '저장 뒤 다시 읽음');
  assert.match(body, /savedMismatch\(/);
});
