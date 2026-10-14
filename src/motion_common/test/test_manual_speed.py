"""수동 조작 상한 · 조인트 2 °/s · 4 °/s² · 수정 목록 126 (사용자 결정 2026-10-13)"""

import math

import pytest

from motion_common import manual_speed


def test_joint_limits_scale_with_the_mapping_gain():
    limits = manual_speed.motor_limits(-150.0)          # 방향(invert)은 상관없음
    assert math.degrees(limits[manual_speed.VELOCITY_FIELD]) == pytest.approx(300.0)
    assert math.degrees(limits[manual_speed.ACCELERATION_FIELD]) == pytest.approx(600.0)


@pytest.mark.parametrize('gain', [None, 0.0, float('nan')])
def test_unknown_gain_is_the_slowest(gain):
    limits = manual_speed.motor_limits(gain)
    assert math.degrees(limits[manual_speed.VELOCITY_FIELD]) == pytest.approx(2.0)


def test_request_values_win_and_bad_ones_fall_back():
    fast = {manual_speed.VELOCITY_FIELD: 1.0, manual_speed.ACCELERATION_FIELD: 2.0}
    assert manual_speed.limits_from_request(fast) == fast
    bad = {manual_speed.VELOCITY_FIELD: -1, manual_speed.ACCELERATION_FIELD: 'x'}
    assert manual_speed.limits_from_request(bad) == manual_speed.motor_limits(None)
    assert manual_speed.limits_from_request(None) == manual_speed.motor_limits(None)
