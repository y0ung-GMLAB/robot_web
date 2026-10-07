"""수정 목록 57 · AC 서보 도달 허용 오차 · 관절 기준 × 감속비 · 모터 0.1° 바닥 · 다이나믹셀 불변"""

from types import SimpleNamespace

import pytest

from motion_runtime.motion_player import ac_target_tolerance_motor_deg


@pytest.mark.parametrize('ratio, expected', [(150, 7.5), (10, 0.5), (1, 0.1)])
def test_joint_tolerance_is_scaled_by_the_ratio_with_the_motor_floor(ratio, expected):
    assert ac_target_tolerance_motor_deg({'gear_ratio': ratio}, 0.1, 0.05) == pytest.approx(expected)


def test_scale_and_invert_use_the_size_only_and_missing_rows_keep_the_floor():
    assert ac_target_tolerance_motor_deg({'gear_ratio': 50, 'scale': 2, 'invert': True}, 0.1, 0.05) == pytest.approx(5.0)
    assert ac_target_tolerance_motor_deg(None, 0.1, 0.05) == 0.1
    assert ac_target_tolerance_motor_deg({'gear_ratio': 150}, 0.1, 0.0) == 0.1


def test_player_uses_it_for_ac_and_leaves_dynamixel_alone():
    import math

    from motion_runtime.motion_player import MotionPlayer

    params = {'ac_target_tolerance_deg': 0.1, 'ac_target_tolerance_joint_deg': 0.05,
              'dynamixel_target_tolerance_deg': 1.0}
    manager = SimpleNamespace(
        _runtime_float_parameter=lambda name, fallback: params.get(name, fallback),
        ac_target_tolerance_deg=0.1, ac_target_tolerance_joint_deg=0.05,
        dynamixel_target_tolerance_deg=1.0,
    )
    player = MotionPlayer.__new__(MotionPlayer)
    player.manager = manager
    ac = player._target_tolerance({'motor_type': 'ac_servo', 'row': {'gear_ratio': 150}})
    dxl = player._target_tolerance({'motor_type': 'dynamixel', 'row': {'gear_ratio': 150}})
    assert math.degrees(ac) == pytest.approx(7.5)
    assert math.degrees(dxl) == pytest.approx(1.0)
