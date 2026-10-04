"""다이나믹셀 절대 이동 · ±180 한 바퀴 검사 폐지 · 한계 = 모터 운전 한계 하나 · 2026-10-04

Extended Position(멀티턴) · 외부 기어 사례 · 한계는 조인트 매핑 환산값(lower/upper)
이고 AC 서보 절대 이동과 같은 `_target_position_limit_error` 가 본다.
"""

from motion_supervisor.supervisor_node import MotionSupervisor


def _supervisor(motors):
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor._current_motors = lambda: motors
    return supervisor


def _dynamixel(lower, upper):
    return {'controller_index': 2, 'motor_type': 'dynamixel', 'lower': lower, 'upper': upper}


def test_target_outside_motor_limits_is_rejected_before_anything_else():
    supervisor = _supervisor([_dynamixel(-10.0, 10.0)])
    success, message = supervisor._handle_dynamixel_absolute_move({'axis': 2, 'target_deg': 200.0})
    assert success is False
    assert '상한' in message and '200.000' in message


def test_target_beyond_one_turn_passes_when_motor_limits_allow_it():
    supervisor = _supervisor([_dynamixel(-720.0, 720.0)])
    # 한계 검사를 지나면 준비 상태 검사로 간다 · 거기서 멈춰 세워 통과를 확인한다
    supervisor._manual_readiness_error = lambda *_args, **_kwargs: 'stop here'
    success, message = supervisor._handle_dynamixel_absolute_move({'axis': 2, 'target_deg': 400.0})
    assert (success, message) == (False, 'stop here')


def test_range_recovery_skips_the_limit_check():
    supervisor = _supervisor([_dynamixel(-10.0, 10.0)])
    supervisor._manual_readiness_error = lambda *_args, **_kwargs: 'stop here'
    success, message = supervisor._handle_dynamixel_absolute_move(
        {'axis': 2, 'target_deg': 10.0, 'range_recovery': True}
    )
    assert (success, message) == (False, 'stop here')
