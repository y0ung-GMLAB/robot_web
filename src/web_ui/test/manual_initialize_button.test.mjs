// 수정 목록 58 · 수동 조작 화면에도 초기 위치 이동 · 새 경로 없이 같은 함수
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../static/${path}`, import.meta.url), 'utf8');

test('수동 조작 패널에 버튼 · dom 등록 · 같은 함수 호출 · 수동 동작 중 꺼짐', () => {
  assert.match(read('panels/07-panel-manual.html'), /id="manualInitializeButton"/);
  assert.match(read('js/dom.js'), /manualInitializeButton: document\.getElementById\('manualInitializeButton'\)/);
  const motion = read('js/motion_data.js');
  assert.match(motion, /el\.manualInitializeButton\?\.addEventListener\('click', \(\) => initializeCurrentMotionRun\(\)\)/);
  assert.match(motion, /activity\.source === 'motion_supervisor'/);
  assert.match(motion, /el\.manualInitializeButton\.disabled = motionRunLoading \|\| running\s*\|\| !contextReady \|\| !hasMappingFile \|\| manualMoving/);
});
