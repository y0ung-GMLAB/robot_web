/** MINAS 드라이브 설정 칸 · 매뉴얼(SX-DSV03241 R10.0) 기준 · 수정 목록 34 · 2026-10-06
 *
 * 예전 화면은 매뉴얼과 달랐다 ·
 * - 리밋 스위치(Pr5.04) 「1 사용 안 함」 → 실제로는 CiA402 감속 정지 (리밋 살아 있음 · p.155)
 * - 앱솔루트(Pr0.15) 0 인크리멘털 · 1 절대 → 실제로는 0 절대 · 1 인크리멘털 (p.176) ·
 *   게다가 속성 C 라 부팅 때 RAM 에 써도 반영되지 않는다 (p.241)
 * 그래서 리밋 스위치는 화면에서 빼고(명령어 메모) · 앱솔루트는 읽기만 한다.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const config = readFileSync(new URL('../static/js/motor_config.js', import.meta.url), 'utf8');
const server = readFileSync(
  new URL('../../web_bridge/motion_web_bridge/minas_params.py', import.meta.url), 'utf8');
const scanner = readFileSync(
  new URL('../../motion_state_monitor/motion_state_monitor/ethercat_scanner.py', import.meta.url), 'utf8');
const docs = readFileSync(new URL('../../../docs/사용법.md', import.meta.url), 'utf8');

test('the limit switch is gone from the screen, the boot SDO list and the scan read', () => {
  assert.doesNotMatch(config, /limit_switch_mode/);
  assert.doesNotMatch(config, /리밋 스위치를 켰습니다/);
  assert.doesNotMatch(server, /'limit_switch_mode': \(0x3504/);
  assert.doesNotMatch(scanner, /0x3504/);
});

test('absolute mode is shown with the manual meaning and never written at boot', () => {
  // 매뉴얼 p.176 · 0 절대 · 1 인크리멘털
  assert.match(config, /0: '절대',\n\s*1: '인크리멘털',/);
  assert.doesNotMatch(config, /\[0, '인크리멘털'\]/);
  // 고칠 수 있는 칸이 아니다
  assert.match(config, /const DRIVE_PARAM_FIELDS = \[\n\s*'brake_delay_stop_ms', 'brake_delay_run_ms', 'overload_monitor',\n\s*\];/);
  assert.match(config, /const DRIVE_READ_ONLY_FIELDS = \['encoder_absolute_mode'\];/);
  // 부팅 SDO 에서 빠짐 · 옛 키는 무시
  assert.doesNotMatch(server, /'encoder_absolute_mode': \(0x3015/);
  assert.match(server, /RETIRED_FIELDS: Tuple\[str, \.\.\.\] = \('encoder_absolute_mode', 'limit_switch_mode'\)/);
  // 검색 때는 계속 읽어 보여 준다
  assert.match(scanner, /'encoder_absolute_mode': \(0x3015, 0\)/);
});

test('remaining drive params keep the same screen and server rules', () => {
  assert.match(config, /value < 0 \|\| value > 10000/);
  assert.match(server, /'brake_delay_stop_ms': \(0, 10000\),/);
  assert.match(config, /overload_monitor: \[\[0, '끔'\], \[1, '켬'\]\]/);
  assert.match(config, /<option value=""\$\{value === '' \? ' selected' : ''\}>/);
  assert.match(config, /data-axis-edit="\$\{field\}" data-axis-row-id="\$\{escapeHtml\(row\.id\)\}"\$\{disabled\}`;/);
});

test('grey text shows the value read from the drive at the last scan, never a stored copy', () => {
  assert.match(config, /const scanned = row\?\.servedRow\?\.scanned;/);
  assert.match(config, /if \(!scanned\?\.drive_params_read\) return \{ state: 'none' \};/);
  assert.match(config, /`드라이브 \$\{read\.value\}`/);
  assert.match(config, /'읽기 실패' : '검색 후 표시'/);
  assert.doesNotMatch(config, /placeholder="유지"/);
});

test('the manual keeps a command memo for limit switches and input pins', () => {
  assert.match(docs, /ethercat download -p <위치> -t uint32 0x3401 0 0x00000000/);
  assert.match(docs, /0x1010 1 0x65766173/);
  assert.match(docs, /SX-DSV03241/);
});
