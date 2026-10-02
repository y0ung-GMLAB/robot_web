/** 리밋 스위치(구동 금지 입력 POT/NOT) 설정 · Pr5.04 · 2026-10-02
 *
 * 스위치가 배선되지 않은 축에 켜면(0/2) b접점 입력이 열린 채라 드라이브가
 * 「눌림」으로 읽는다 → 그 방향으로 못 움직이거나 Err38 알람 · 그래서
 * 빈 칸 = 드라이브 값 유지 · 0/1/2 밖은 거절 · 켜면 경고를 띄운다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const config = readFileSync(new URL('../static/js/motor_config.js', import.meta.url), 'utf8');
const server = readFileSync(
  new URL('../../web_bridge/motion_web_bridge/minas_params.py', import.meta.url), 'utf8');

test('limit switch is a drive param field with its own label', () => {
  assert.match(config, /'brake_delay_run_ms', 'encoder_absolute_mode', 'limit_switch_mode',/);
  assert.match(config, /limit_switch_mode: \['리밋 스위치',/);
  assert.match(server, /'limit_switch_mode': \(0x3504, 's16'/);
});

test('screen and server accept the same values', () => {
  // 화면: 0/1/2 · 브레이크 0~10000 ms
  assert.match(config, /\['encoder_absolute_mode', 'limit_switch_mode'\]\.includes\(field\) && !\[0, 1, 2\]\.includes\(value\)/);
  assert.match(config, /value < 0 \|\| value > 10000/);
  // 서버: 같은 규칙으로 버린다
  assert.match(server, /'limit_switch_mode': \(0, 1, 2\),/);
  assert.match(server, /'brake_delay_stop_ms': \(0, 10000\),/);
});

// 0/1/2 · 켬/끔 은 선택 상자 · 빈 값(첫 항목) = 유지 · 2026-10-02
test('discrete drive params are select boxes whose first option keeps the drive value', () => {
  assert.match(config, /encoder_absolute_mode: \[\[0, '인크리멘털'\], \[1, '절대'\], \[2, '절대·다회전 무시'\]\]/);
  assert.match(config, /limit_switch_mode: \[\[0, '사용·그 방향 금지'\], \[1, '사용 안 함'\], \[2, '사용·알람\(Err38\)'\]\]/);
  assert.match(config, /overload_monitor: \[\[0, '끔'\], \[1, '켬'\]\]/);
  assert.match(config, /<option value=""\$\{value === '' \? ' selected' : ''\}>/);
  // 같은 change 처리 · data-axis-edit 를 그대로 단다
  assert.match(config, /data-axis-edit="\$\{field\}" data-axis-row-id="\$\{escapeHtml\(row\.id\)\}"\$\{disabled\}`;/);
});

test('grey text shows the value read from the drive at the last scan, never a stored copy', () => {
  assert.match(config, /const scanned = row\?\.servedRow\?\.scanned;/);
  assert.match(config, /if \(!scanned\?\.drive_params_read\) return \{ state: 'none' \};/);
  assert.match(config, /`유지 \(드라이브: \$\{driveChoiceText\(field, read\.value\)\}\)`/);
  assert.match(config, /`드라이브 \$\{read\.value\}`/);
  assert.match(config, /'읽기 실패' : '검색 후 표시'/);
  assert.doesNotMatch(config, /placeholder="유지"/);
});

test('turning it on warns about unwired axes and is not swallowed by the generic message', () => {
  const start = config.indexOf("if (field === 'limit_switch_mode' && (text === '0' || text === '2'))");
  assert.ok(start > 0);
  const body = config.slice(start, start + 700);
  assert.match(body, /스위치가 배선된 축에만 쓰세요/);
  assert.match(body, /그 방향으로 못 움직입니다/);
  assert.match(body, /Err38 알람/);
  // 일반 「변경됨」 문구가 덮지 않게 경고를 그린 뒤 끝낸다
  assert.match(body, /true,\n\s*\);\n\s*return;/);
});
