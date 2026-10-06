"""rad 로 옮긴 조인트 매핑 식 = 옮기기 전 deg 식 · 수정 목록 6

옮기기 전 식을 아래에 그대로 남겨 두고(`_legacy_motor_target_deg`), 지금 쓰는 길이
**모터로 나가는 값**(아직 deg)에서 같은 값을 내는지 무작위 줄로 본다 ·
매핑 줄은 옛 파일(deg 칸)과 새 파일(rad 칸 · 정규화 결과) 둘 다.
"""

import math
import random

import pytest

from motion_common import joint_mapping, units, wire_units
from motion_runtime import motion_run_rules
from motion_runtime.motion_mapping_manager import MotionMappingManager
from motion_runtime.motion_trace import joint_from_motor as trace_joint_from_motor
from motion_web_bridge import mapping_motor_limits


def _legacy_motor_target_deg(row, motion_value):
    """2026-10-06 까지의 `motion_run_rules._motor_target` (deg) 그대로"""
    sign = -1.0 if bool(row.get('invert')) else 1.0
    reference = float(row.get('reference_position_deg') or 0.0)
    if row.get('reference_enabled') is False:
        reference = 0.0
    offset = float(row.get('offset_deg') or 0.0)
    scale = float(row.get('scale') or 1.0)
    gear_ratio = float(row.get('gear_ratio') or 1.0)
    return reference + ((float(motion_value) + offset) * scale * sign) * gear_ratio


def _rows(count=300, seed=7):
    rng = random.Random(seed)
    for _ in range(count):
        lower = rng.uniform(-90, 0)
        yield {
            'motion_id': 'j',
            'invert': rng.random() < 0.5,
            'reference_enabled': rng.random() < 0.8,
            'reference_position_deg': rng.uniform(-50000, 50000),
            'offset_deg': rng.uniform(-30, 30),
            'scale': rng.choice([1.0, 0.5, 2.0, -1.0]),
            'gear_ratio': rng.choice([1.0, 35.0, 50.0, 100.0, 150.0]),
            'motion_lower_deg': lower,
            'motion_upper_deg': lower + rng.uniform(0, 120),
        }, rng.uniform(-180, 180)


def _saved_rad_row(row):
    """새 버전이 저장하는 줄 모양(rad 칸뿐)"""
    manager = MotionMappingManager.__new__(MotionMappingManager)
    return manager._normalize_mapping({'name': 'n', 'mappings': [row]})['mappings'][0]


ROWS = list(_rows())


@pytest.mark.parametrize('row, joint_deg', ROWS)
def test_motor_command_on_the_wire_is_unchanged(row, joint_deg):
    expected = _legacy_motor_target_deg(row, joint_deg)
    joint = math.radians(joint_deg)
    for source in (row, _saved_rad_row(row)):
        target = motion_run_rules._motor_target(source, joint)
        # 재생 → supervisor(명령 토픽) → motor_manager(아직 deg) · 50000° 대 값이라 상대 오차로 본다
        on_wire = wire_units.to_motor_node(wire_units.from_command(wire_units.command_value(target)))
        assert on_wire == pytest.approx(expected, rel=1e-12, abs=1e-9)
        back = trace_joint_from_motor(source, target)
        assert back == pytest.approx(joint, abs=1e-9)


@pytest.mark.parametrize('row, joint_deg', ROWS[:60])
def test_motor_config_limits_are_unchanged(row, joint_deg):
    first = _legacy_motor_target_deg(row, row['motion_lower_deg'])
    second = _legacy_motor_target_deg(row, row['motion_upper_deg'])
    expected = (round(min(first, second), 3), round(max(first, second), 3))
    for source in (row, _saved_rad_row(row)):
        low, high = mapping_motor_limits.row_motor_limits(source)
        assert low == pytest.approx(expected[0], abs=1.1e-3)
        assert high == pytest.approx(expected[1], abs=1.1e-3)


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


def test_motor_state_positions_are_read_as_rad():
    assert wire_units.motor_position({'position_deg': 180.0}) == pytest.approx(math.pi)
    assert wire_units.motor_position({'position_rad': 1.0, 'position_deg': 999.0}) == 1.0
    # 이름에 단위가 없는 칸은 상태 단위(rad) · `*_deg` 칸은 이름대로
    assert wire_units.motor_position({'position': 0.5}) == pytest.approx(0.5)
    assert wire_units.motor_velocity({'velocity_deg_s': 90.0}) == pytest.approx(math.pi / 2)
    assert wire_units.motor_velocity({'velocity_rad_s': 0.25}) == 0.25
    assert wire_units.motor_position(None) is None
    # 하한·상한은 모터 설정 파일에서 그대로 옮겨 실린 값 · 설정 단위(아직 deg)
    assert wire_units.motor_limit({'lower': -90.0}, 'lower') == pytest.approx(-math.pi / 2)
    assert wire_units.motor_limit({'lower_rad': -1.0, 'lower': -90.0}, 'lower') == -1.0
    assert wire_units.motor_limit({}, 'upper') is None
