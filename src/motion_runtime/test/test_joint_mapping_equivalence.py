"""조인트 매핑 식 원본(`motion_common.joint_mapping`) = 흩어져 있던 사본들 · 수정 목록 6

rad 로 옮기기 전에 원본 하나를 세우고, 지금 쓰는 사본들과 값이 같은지 무작위 줄로 본다 ·
그 다음에 사본을 원본 호출로 바꾼다.
"""

import math
import random

import pytest

from motion_common import joint_mapping, units
from motion_runtime import motion_run_rules
from motion_runtime.motion_trace import joint_from_motor as trace_joint_from_motor
from motion_web_bridge import mapping_motor_limits


def _rows(count=300, seed=7):
    rng = random.Random(seed)
    for _ in range(count):
        yield {
            'invert': rng.random() < 0.5,
            'reference_enabled': rng.random() < 0.8,
            'reference_position_deg': rng.uniform(-50000, 50000),
            'offset_deg': rng.uniform(-30, 30),
            'scale': rng.choice([1.0, 0.5, 2.0, -1.0]),
            'gear_ratio': rng.choice([1.0, 35.0, 50.0, 100.0, 150.0]),
        }, rng.uniform(-180, 180)


@pytest.mark.parametrize('row, joint', list(_rows()))
def test_one_formula_matches_every_copy_in_degrees(row, joint):
    expected = motion_run_rules._motor_target(row, joint)

    assert joint_mapping.motor_target(row, joint, units.DEG) == pytest.approx(expected, abs=1e-9)
    assert mapping_motor_limits.motor_target(row, joint) == pytest.approx(expected, abs=1e-9)
    back = joint_mapping.joint_from_motor(row, expected, units.DEG)
    assert back == pytest.approx(trace_joint_from_motor(row, expected), abs=1e-6)
    assert back == pytest.approx(joint, abs=1e-6)


def test_the_same_motion_in_rad_gives_the_same_motor_position():
    row = {'reference_position_deg': 1234.5, 'offset_deg': 2.0, 'scale': 1.0, 'gear_ratio': 150.0, 'invert': True}
    in_deg = joint_mapping.motor_target(row, 10.0, units.DEG)
    in_rad = joint_mapping.motor_target(row, math.radians(10.0), units.RAD)
    assert math.degrees(in_rad) == pytest.approx(in_deg, abs=1e-9)


def test_rad_fields_win_over_deg_fields_and_defaults_follow_the_unit():
    row = {'offset_rad': 0.1, 'offset_deg': 999.0}
    assert joint_mapping.angle(row, 'offset', units.RAD) == pytest.approx(0.1)
    assert joint_mapping.angle({}, 'motion_upper', units.RAD) == pytest.approx(math.pi)
    assert joint_mapping.angle({}, 'motion_upper', units.DEG) == pytest.approx(180.0)
    assert joint_mapping.rate({'max_velocity_deg_s': 90.0}, 'max_velocity', units.RAD) == pytest.approx(math.pi / 2)
    assert joint_mapping.rate({}, 'max_velocity') is None


def test_row_in_unit_renames_every_angle_field():
    row = {
        'motion_id': 'Neck_Yaw', 'gear_ratio': 100.0,
        'offset_deg': 1.0, 'motion_lower_deg': -15.0, 'motion_upper_deg': 15.0,
        'reference_position_deg': 3600.0, 'max_velocity_deg_s': 120.0,
    }
    rad = joint_mapping.row_in_unit(row, units.RAD)
    assert set(rad) == {
        'motion_id', 'gear_ratio', 'offset_rad', 'motion_lower_rad', 'motion_upper_rad',
        'reference_position_rad', 'max_velocity_rad_s',
    }
    back = joint_mapping.row_in_unit(rad, units.DEG)
    for key in ('offset_deg', 'motion_lower_deg', 'reference_position_deg', 'max_velocity_deg_s'):
        assert back[key] == pytest.approx(row[key])
