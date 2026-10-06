/** 다이나믹셀 토크 켜기·끄기·재부팅 · 서보 버튼 자리를 같이 쓴다 · 수정 목록 24 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { DYNAMIXEL_CONTROL_ACTIONS, servoButtonLabels } from '../static/js/motion_test.js';

const motionTest = readFileSync(new URL('../static/js/motion_test.js', import.meta.url), 'utf8');
const motorConfig = readFileSync(new URL('../static/js/motor_config.js', import.meta.url), 'utf8');
const api = readFileSync(new URL('../static/js/api.js', import.meta.url), 'utf8');

test('the three servo buttons map to torque on, torque off and reboot on a Dynamixel', () => {
  assert.deepEqual({ ...DYNAMIXEL_CONTROL_ACTIONS }, {
    servo_on: 'torque_on', servo_off: 'torque_off', fault_reset: 'reboot',
  });
  assert.deepEqual(servoButtonLabels({ motor_type: 'dynamixel' }), { on: '토크 켜기', off: '토크 끄기', reset: '재부팅' });
  assert.deepEqual(servoButtonLabels({ motor_type: 'ac_servo' }), { on: '서보 켜기', off: '서보 끄기', reset: '오류 초기화' });
});

test('a selected Dynamixel goes to its own route · reboot and torque off ask first', () => {
  assert.match(api, /request\('POST', '\/api\/motion-test\/dynamixel\/control'/);
  assert.match(motionTest, /if \(scope === 'selected' && motor && isDynamixelMotor\(motor\)\) \{/);
  assert.match(motionTest, /await sendDynamixelControl\(DYNAMIXEL_CONTROL_ACTIONS\[action\] \|\| action, axis\);/);
  assert.match(motionTest, /reboot: '선택 모터 다이나믹셀을 재부팅합니다/);
  assert.match(motionTest, /&& \(isAcServoMotor\(motor\) \|\| isDynamixelMotor\(motor\)\)/);
});

test('motor management shows torque ON/OFF and reboot on Dynamixel rows only', () => {
  assert.match(motorConfig, /const showDynamixelControls = rowMotorType\(row\) === 'dynamixel' &&/);
  assert.match(motorConfig, /\$\{view\.showDynamixelControls \? `/);
  assert.match(motorConfig, /data-axis-servo-action="fault_reset" data-axis-servo-index="\$\{escapeHtml\(view\.axisValue \?\? ''\)\}">재부팅<\/button>/);
});
