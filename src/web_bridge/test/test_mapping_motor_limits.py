"""조인트 매핑 범위 → 모터 운전 한계 · 리밋 원본은 매핑 하나 (2026-10-02).

조인트 매핑 편집에서 최소·최대를 바꿔도 드라이브 soft limit 까지 안 갔다 ·
모터 설정의 lower/upper 는 모터 관리에서 따로 적는 값이었다 · 이제 매핑에서
환산해 넣는다 · 재생 클리핑과 soft limit 이 같은 범위를 쓴다.
"""

import copy
from pathlib import Path

import pytest

from motion_web_bridge.mapping_motor_limits import (
    apply_mapping_limits,
    motor_target,
    row_motor_limits,
)
from motion_web_bridge.motor_config_build import default_motor_config

WORKSPACE = Path(__file__).resolve().parents[3]


def _config():
    """MINAS 두 대 (alias 101 · 102) + Dynamixel 한 대."""
    config = default_motor_config(WORKSPACE)
    minas = config['drivers'][0]
    config['drivers'] = [
        {**minas, 'id': 0},
        {**minas, 'id': 1},
        {'id': 2, 'type': 'dynamixel', 'lower': -180.0, 'upper': 180.0},
    ]
    config['masters'] = [
        {
            'id': 0, 'type': 'ethercat', 'ethercat_master_index': 0,
            'slaves': [
                {'controller_index': 0, 'driver_id': 0, 'alias': 101, 'position': 0, 'ring_position': 0},
                {'controller_index': 1, 'driver_id': 1, 'alias': 102, 'position': 0, 'ring_position': 1},
            ],
        },
        {
            'id': 1, 'type': 'serial', 'serial_port': '/dev/ttyUSB0', 'serial_baudrate': 1000000,
            'slaves': [{'controller_index': 2, 'driver_id': 2, 'bus_id': 7}],
        },
    ]
    return config


def _driver(config, axis):
    for master in config['masters']:
        for slave in master['slaves']:
            if slave['controller_index'] == axis:
                return next(d for d in config['drivers'] if d['id'] == slave['driver_id'])
    raise AssertionError(axis)


def _row(**values):
    row = {
        'motion_id': 'Neck_Pitch', 'enabled': True,
        'motor_ref': 'ac_servo:master:0:alias:101',
        'reference_enabled': True, 'reference_position_deg': 100.0,
        'motion_lower_deg': -10.0, 'motion_upper_deg': 13.0,
        'invert': False, 'offset_deg': 0.0, 'scale': 1.0, 'gear_ratio': 150.0,
    }
    row.update(values)
    return row


def test_mapping_range_becomes_motor_deg_limits():
    config, changed = apply_mapping_limits(_config(), {'mappings': [_row()]})
    driver = _driver(config, 0)
    assert driver['lower'] == 100.0 - 1500.0
    assert driver['upper'] == 100.0 + 1950.0
    assert [item['controller_index'] for item in changed] == [0]
    # 매핑 없는 모터는 그대로
    assert _driver(config, 1)['lower'] == -36000.0


def test_invert_swaps_the_ends():
    lower, upper = row_motor_limits(_row(invert=True))
    assert (lower, upper) == (100.0 - 1950.0, 100.0 + 1500.0)


def test_reference_off_means_zero():
    lower, upper = row_motor_limits(_row(reference_enabled=False))
    assert (lower, upper) == (-1500.0, 1950.0)


def test_offset_and_scale_follow_the_runtime_formula():
    row = _row(offset_deg=2.0, scale=0.5)
    assert motor_target(row, 13.0) == 100.0 + (13.0 + 2.0) * 0.5 * 150.0


def test_dynamixel_gear_is_one_and_clamped():
    row = _row(motor_ref='dynamixel:port:%2Fdev%2FttyUSB0:id:7', gear_ratio=35.0,
               reference_position_deg=170.0)
    config, _ = apply_mapping_limits(_config(), {'mappings': [row]})
    driver = _driver(config, 2)
    assert driver['lower'] == 160.0          # 170 − 10 · 감속비 무시
    assert driver['upper'] == 180.0          # 170 + 13 = 183 → ±180 안으로


def test_legacy_motor_axis_rows_still_match():
    row = _row(motor_ref='', motor_axis=1)
    config, _ = apply_mapping_limits(_config(), {'mappings': [row]})
    assert _driver(config, 1)['upper'] == 2050.0
    assert _driver(config, 0)['upper'] == 36000.0


def test_disabled_rows_are_ignored():
    config, changed = apply_mapping_limits(_config(), {'mappings': [_row(enabled=False)]})
    assert changed == []
    assert _driver(config, 0)['lower'] == -36000.0


def test_two_rows_on_one_motor_take_the_narrowest():
    rows = [_row(), _row(motion_id='other', motion_lower_deg=-5.0, motion_upper_deg=20.0)]
    config, _ = apply_mapping_limits(_config(), {'mappings': rows})
    driver = _driver(config, 0)
    assert driver['lower'] == 100.0 - 750.0
    assert driver['upper'] == 100.0 + 1950.0


def test_no_change_means_no_change_report():
    first, _ = apply_mapping_limits(_config(), {'mappings': [_row()]})
    _, changed = apply_mapping_limits(copy.deepcopy(first), {'mappings': [_row()]})
    assert changed == []


def test_no_mapping_leaves_the_config_alone():
    config = _config()
    result, changed = apply_mapping_limits(config, None)
    assert result is config and changed == []


def test_shared_driver_is_split_before_writing():
    """두 축이 한 드라이버를 쓰면 한 축 한계가 다른 축으로 새면 안 된다."""
    config = _config()
    config['masters'][0]['slaves'][1]['driver_id'] = 0
    result, _ = apply_mapping_limits(config, {'mappings': [_row()]})
    assert _driver(result, 0)['upper'] == 2050.0
    assert _driver(result, 1)['upper'] == 36000.0


def test_same_formula_as_runtime():
    rules = pytest.importorskip('motion_runtime.motion_run_rules')
    for row in (_row(), _row(invert=True, offset_deg=1.5, scale=0.8),
                _row(reference_enabled=False, gear_ratio=35.0)):
        for value in (-10.0, 0.0, 13.0):
            assert motor_target(row, value) == pytest.approx(rules._motor_target(row, value))
