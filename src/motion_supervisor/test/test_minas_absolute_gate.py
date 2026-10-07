"""앱솔루트 미확인이면 모든 모터 동작 거부 · 끄기·리셋·정지는 통과 · 수정 목록 62 ②"""

import json
import math
import threading
import time

from motion_supervisor.command_arbiter import CommandArbiter
from motion_supervisor.supervisor_node import (
    CW_DISABLE_OPERATION_MINAS,
    CW_ENABLE_OPERATION_MINAS,
    CW_FAULT_RESET_MINAS,
    CW_NEW_SET_POINT_MINAS,
    CW_SHUTDOWN_MINAS,
    DYNAMIXEL_TORQUE_ENABLE,
    MotionSupervisor,
)

R = math.radians
BLOCKED = {
    'state': 'blocked',
    'drives': [{'master_index': 0, 'slave_position': 1, 'axis': 1, 'absolute_mode': 1, 'status': 'not_absolute'}],
    'message': '앱솔루트 미확인 · 1번 모터 Pr0.15=1(인크리멘털) · 모터 관리에서 앱솔루트 설정',
}


class Capture:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


def _supervisor(minas_absolute):
    motors = [
        {'controller_index': 0, 'state': 'detected', 'motor_type': 'ac_servo', 'fault': False,
         'lower': -90.0, 'upper': 90.0},
        {'controller_index': 1, 'state': 'detected', 'motor_type': 'ac_servo', 'fault': False,
         'lower': -90.0, 'upper': 90.0},
    ]
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._latest_state = {'motors': motors, 'minas_absolute': minas_absolute}
    supervisor._latest_state_at = time.time()
    supervisor._current_motors = lambda: motors
    supervisor._command_lock = threading.RLock()
    supervisor._command_pub = Capture()
    supervisor._emergency_latched = False
    supervisor._motion_stop_block_until = 0.0
    supervisor._active_jogs = {}
    supervisor._active_actions = {}
    supervisor._command_arbiter = CommandArbiter()
    return supervisor


def test_absolute_ok_or_no_minas_does_not_block():
    assert _supervisor({'state': 'ok'})._motion_block_reason(0) == ''
    assert _supervisor({'state': 'none'})._motion_block_reason(0) == ''


def test_blocked_checking_or_missing_info_blocks_every_axis():
    assert _supervisor(BLOCKED)._motion_block_reason(0) == BLOCKED['message']   # 0번은 정상이어도 막힘
    assert '확인 중' in _supervisor({'state': 'checking'})._motion_block_reason(0)
    assert '확인 정보 없음' in _supervisor(None)._motion_block_reason(0)


def test_servo_on_is_refused_but_servo_off_and_fault_reset_go_through():
    supervisor = _supervisor(BLOCKED)

    success, message = supervisor._handle_ac_servo_control({'action': 'servo_on', 'scope': 'all'})
    assert success is False and message == BLOCKED['message']
    assert supervisor._command_pub.messages == []

    success, _ = supervisor._handle_ac_servo_control({'action': 'servo_off', 'scope': 'all'})
    assert success is True
    success, _ = supervisor._handle_ac_servo_control({'action': 'fault_reset', 'scope': 'all'})
    assert success is True
    sent = [int(command.controlword[0]) for command in supervisor._command_pub.messages]
    # 끄기 · 리셋 · 리셋 뒤 0x06(전원 차단 상태로) 모두 나감
    assert sent == [CW_DISABLE_OPERATION_MINAS, CW_FAULT_RESET_MINAS, CW_SHUTDOWN_MINAS]


def test_energizing_controlwords_are_dropped_at_the_last_gate():
    supervisor = _supervisor(BLOCKED)
    motors = supervisor._current_motors()
    for word in (CW_ENABLE_OPERATION_MINAS, CW_NEW_SET_POINT_MINAS, DYNAMIXEL_TORQUE_ENABLE):
        supervisor._publish_controlword(motors, [0], word)
    assert supervisor._command_pub.messages == []


def test_absolute_move_and_jog_are_refused_with_the_reason():
    supervisor = _supervisor(BLOCKED)
    success, message = supervisor._publish_position_target(
        supervisor._current_motors(), supervisor._current_motors()[0], 0, R(10.0), CW_NEW_SET_POINT_MINAS,
    )
    assert success is False and message == BLOCKED['message']
    assert supervisor._command_pub.messages == []


def test_dynamixel_torque_on_is_refused():
    supervisor = _supervisor(BLOCKED)
    motors = [{'controller_index': 2, 'state': 'detected', 'motor_type': 'dynamixel', 'fault': False}]
    supervisor._current_motors = lambda: motors
    success, message = supervisor._handle_dynamixel_torque_control({'action': 'torque_on'})
    assert success is False and message == BLOCKED['message']
    success, _ = supervisor._handle_dynamixel_torque_control({'action': 'torque_off'})
    assert success is True


class JsonCapture:
    def __init__(self):
        self.payloads = []

    def publish(self, message):
        self.payloads.append(json.loads(message.data))


def test_safety_status_blocks_commands_so_playback_schedule_and_screen_stop_too():
    supervisor = _supervisor(BLOCKED)
    supervisor._safety_status_pub = JsonCapture()
    supervisor._last_motion_run_command_at = time.monotonic() - 10.0

    supervisor._publish_safety_status()

    payload = supervisor._safety_status_pub.payloads[-1]
    assert payload['commands_blocked'] is True
    assert payload['minas_absolute_blocked'] is True
    assert payload['message'] == BLOCKED['message']

    supervisor._latest_state['minas_absolute'] = {'state': 'ok'}
    supervisor._publish_safety_status()
    payload = supervisor._safety_status_pub.payloads[-1]
    assert payload['commands_blocked'] is False and payload['message'] == '동작 가능'
