"""supervisor 단위 경계 · 수정 목록 6-4 (2026-10-06)

안쪽(요청 · 모터 상태 · 계산)은 rad · motor_manager 로 나가는 위치만 아직 deg ·
들어오는 상태는 `position_rad` · 모터 설정의 하한·상한은 설정 단위(deg) 그대로.
"""

import math
import threading

import pytest

from motion_supervisor.command_arbiter import CommandArbiter
from motion_supervisor.supervisor_node import MotionSupervisor

R = math.radians


class _Capture:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


def _supervisor(motors):
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._active_jogs = {}
    supervisor._active_actions = {}
    supervisor._action_threads = {}
    supervisor._last_motion_run_command_at = 0.0
    supervisor._emergency_latched = False
    supervisor._motion_stop_block_until = 0.0
    supervisor._command_lock = threading.RLock()
    supervisor._command_arbiter = CommandArbiter()
    supervisor._project_generation = 1
    supervisor._command_pub = _Capture()
    supervisor._safety_status_pub = _Capture()
    supervisor._current_motors = lambda: motors
    supervisor.max_jog_delta_deg = 360.0
    return supervisor


def _published_positions(supervisor):
    command = supervisor._command_pub.messages[-1]
    return {
        int(axis): float(command.position[slot])
        for slot, axis in enumerate(command.controller_index)
        if int(command.number_of_target_interfaces[slot]) == 2
    }


def test_motion_stop_holds_the_rad_state_position_and_sends_motor_manager_deg():
    supervisor = _supervisor([
        {'controller_index': 0, 'state': 'detected', 'motor_type': 'ac_servo', 'position_rad': R(1234.5)},
    ])
    success, _ = supervisor._handle_safety_stop(False)
    assert success is True
    assert _published_positions(supervisor) == pytest.approx({0: 1234.5})


def test_dynamixel_jog_adds_a_rad_delta_to_the_rad_position():
    supervisor = _supervisor([{
        'controller_index': 3, 'state': 'detected', 'motor_type': 'dynamixel',
        'servo_on': True, 'fault': False, 'position_rad': R(100.0),
        'lower': -720.0, 'upper': 720.0,
    }])
    supervisor._manual_readiness_error = lambda *_args, **_kwargs: ''
    success, message = supervisor._handle_dynamixel_jog({'axis': 3, 'relative_rad': R(-30.0)})
    assert success is True, message
    assert _published_positions(supervisor) == pytest.approx({3: 70.0})
    assert '-30.000 deg, target 70.000 deg' in message   # 글은 deg
    assert supervisor._active_jogs[3]['target_position'] == pytest.approx(R(70.0))


def test_jog_delta_limit_parameter_stays_in_degrees():
    supervisor = _supervisor([])
    success, message = supervisor._handle_dynamixel_jog({'axis': 3, 'relative_rad': R(361.0)})
    assert success is False
    assert 'jog delta exceeds limit: 360 deg' in message


def test_limit_check_compares_rad_targets_with_degree_config_limits():
    supervisor = _supervisor([])
    motor = {'controller_index': 1, 'lower': -10.0, 'upper': 13.0}
    assert supervisor._target_position_limit_error(motor, R(12.9)) == ''
    message = supervisor._target_position_limit_error(motor, R(13.5))
    assert '13.500 deg' in message and '상한 13.000 deg' in message


def test_profile_limits_from_the_degree_config_become_rad_per_second():
    supervisor = _supervisor([])
    supervisor._driver_config_for_motor = lambda _motor: {
        'profile_velocity': 18000.0, 'profile_acceleration': 180000.0,
    }
    assert supervisor._velocity_limit({}) == pytest.approx(R(18000.0))
    assert supervisor._acceleration_limit({}) == pytest.approx(R(180000.0))
    supervisor._driver_config_for_motor = lambda _motor: {'rated_speed_rpm': 3000.0}
    assert supervisor._velocity_limit({}) == pytest.approx(3000.0 * 2.0 * math.pi / 60.0)
