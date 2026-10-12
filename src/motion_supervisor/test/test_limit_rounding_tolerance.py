"""한계 비교 반올림 여유 · 수정 목록 103(라) (2026-10-12 실물)

매핑 범위를 모터 deg 로 바꾸면 35.577092 가 되고, 설정 파일 한계는 0.001° 로 반올림한 35.577 이다 ·
페이더 끝값이 「상한 35.577 보다 큽니다」 로 거절됐다(두 값이 같게 찍혀 이유를 알 수 없었다) ·
0.001° 안쪽 넘침은 거절하지 않고 경계값으로 자른다 · 그 밖은 지금처럼 거절 · 문구는 소수 4자리.
"""

import math

from motion_supervisor.supervisor_node import MotionSupervisor

R = math.radians


def _supervisor():
    return MotionSupervisor.__new__(MotionSupervisor)


def _motor(lower=-35.577, upper=35.577):
    return {'controller_index': 1, 'motor_type': 'ac_servo', 'lower': lower, 'upper': upper}


def test_overshoot_inside_rounding_is_not_an_error_and_is_clamped():
    supervisor = _supervisor()
    target = R(35.577092)
    assert supervisor._target_position_limit_error(_motor(), target) == ''
    assert math.isclose(supervisor._clamp_to_limits(_motor(), target), R(35.577))
    assert supervisor._target_position_limit_error(_motor(), R(-35.5775)) == ''


def test_real_overshoot_is_still_refused_with_four_decimals():
    message = _supervisor()._target_position_limit_error(_motor(), R(35.59))
    assert '상한' in message
    assert '35.5900' in message and '35.5770' in message


def test_inside_target_is_untouched():
    assert math.isclose(_supervisor()._clamp_to_limits(_motor(), R(10.0)), R(10.0))
