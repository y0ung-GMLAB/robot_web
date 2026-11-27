"""AC 서보 절대 이동 · 운전 한계(`lower/upper`) 밖 목표는 시작 전에 거절

실물 2026-10-07(시험 16) · 범위 밖 300° 를 success 로 받고 궤적을 돌리다가
스텝별 발행 검사(`_publish_ac_servo_action_setpoint`)에 걸려 230° 근처에서 멈췄다 ·
다이나믹셀 절대 이동·조그와 같은 `_target_position_limit_error` 를 앞에서 본다.
"""

import math

from motion_supervisor.supervisor_node import MotionSupervisor

#: 요청은 rad · 하한·상한(모터 설정)은 deg
R = math.radians


def _supervisor(motors):
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._current_motors = lambda: motors
    return supervisor


def _ac_servo(lower, upper):
    return {'controller_index': 0, 'motor_type': 'ac_servo', 'lower': lower, 'upper': upper}


def test_target_above_upper_is_rejected_before_anything_else():
    supervisor = _supervisor([_ac_servo(-248.35, 231.65)])
    supervisor._manual_readiness_error = lambda *_args, **_kwargs: 'must not reach readiness'
    success, message = supervisor._handle_ac_servo_absolute_move({'axis': 0, 'target_rad': R(300.0)})
    assert success is False
    assert '상한' in message and '300.000' in message and '231.650' in message


def test_target_below_lower_is_rejected():
    supervisor = _supervisor([_ac_servo(-248.35, 231.65)])
    success, message = supervisor._handle_ac_servo_absolute_move({'axis': 0, 'target_rad': R(-300.0)})
    assert success is False
    assert '하한' in message and '-300.000' in message


def test_target_inside_limits_goes_on_to_readiness():
    supervisor = _supervisor([_ac_servo(-248.35, 231.65)])
    # 한계 검사를 지나면 준비 상태 검사로 간다 · 거기서 멈춰 세워 통과를 확인한다
    supervisor._manual_readiness_error = lambda *_args, **_kwargs: 'stop here'
    success, message = supervisor._handle_ac_servo_absolute_move({'axis': 0, 'target_rad': R(30.0)})
    assert (success, message) == (False, 'stop here')


def test_range_recovery_skips_the_limit_check():
    supervisor = _supervisor([_ac_servo(-10.0, 10.0)])
    supervisor._manual_readiness_error = lambda *_args, **_kwargs: 'stop here'
    success, message = supervisor._handle_ac_servo_absolute_move(
        {'axis': 0, 'target_rad': R(10.0), 'range_recovery': True}
    )
    assert (success, message) == (False, 'stop here')


def test_stop_during_the_setpoint_wait_drops_the_next_point():
    """수정 목록 112 나 · 「동작 취소」 가 「지금 위치에 서라」 를 보낸 뒤 궤적 스레드가 다음 점을 또 보내
    모터가 7.4° 더 갔다(2026-10-12 floating4) · 기다리는 사이 정지가 오면 보내지 않는다"""
    import threading
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._command_lock = threading.RLock()
    sent = []
    supervisor._target_position_limit_error = lambda _motor, _target: ''
    supervisor._publish_controlword = lambda *_a: None
    supervisor._action_setpoint_clear_sec = lambda: 0.0
    supervisor._publish_position_target = lambda *a: sent.append(a[3]) or (True, 'sent')
    alive = {'yes': False}       # 기다리는 사이 정지가 액션을 지웠다

    ok, message = supervisor._publish_ac_servo_action_setpoint(
        [], {}, 0, 1.0, still_active=lambda: alive['yes'],
    )
    assert ok is True and 'cancelled' in message
    assert sent == []

    alive['yes'] = True
    supervisor._publish_ac_servo_action_setpoint([], {}, 0, 2.0, still_active=lambda: alive['yes'])
    assert sent == [2.0]
