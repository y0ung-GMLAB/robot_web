"""직렬 서보 운전 값 기본 0 = 서보 최대 · 옛 기본값 옮기기 · 적용 검사 · 수정 목록 163

사용자 2026-10-30 · AC 서보는 구조 안전 때문에 속도·가속 상한을 둔다 · 직렬 서보(Dynamixel · Feetech)는
작아서 구조 안전이 걸리지 않는다 · 서보가 낼 수 있는 만큼 · 사람이 더 낮게 적으면 그 값.
"""

from pathlib import Path

import pytest

from motion_web_bridge import motor_config_build, serial_params
from motion_web_bridge.motor_profile_validation import validate_runtime_motor_profiles

WORKSPACE = Path(__file__).resolve().parents[3]
U2D2 = '/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT1-if00-port0'
CH340 = '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'
FIELDS = motor_config_build.SERIAL_PROFILE_FIELDS


@pytest.fixture(autouse=True)
def _generated_files_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(serial_params, 'output_root', lambda _root: tmp_path / 'serial_params')
    from motion_web_bridge import minas_params

    monkeypatch.setattr(minas_params, 'OUTPUT_DIR', str(tmp_path / 'minas_params'))


def _serial(axis, kind, model, bus_id, *, port=U2D2, model_number=None, **config):
    return {
        'id': f'{kind}-{axis}', 'enabled': True, 'axis': axis, 'name': f'모터 {axis}',
        'motor_type': kind, 'driver_family': kind, 'transport': 'serial',
        'identity': {'serial_port': port, 'serial_baudrate': 1000000, 'bus_id': bus_id,
                     'model_number': model_number},
        'profile': {'driver_model': model, 'model_confirmed': True},
        'config': {'controller_index': axis, **config},
    }


def _driver_for(config, axis):
    for master in config['masters']:
        for slave in master.get('slaves', []):
            if slave['controller_index'] == axis:
                return next(d for d in config['drivers'] if d['id'] == slave['driver_id'])
    raise AssertionError(axis)


def _chicken2_saved_config():
    """chicken2 저장 모양 · XM430-W350 3대(100 · 703104.5) + Feetech 1대(180 · 703104.5)"""
    config = motor_config_build.default_motor_config(WORKSPACE)
    old_dxl = {'speed': 100.0, 'acceleration': 703104.5, 'deceleration': 703104.5,
               'profile_velocity': 100.0, 'profile_acceleration': 703104.5,
               'profile_deceleration': 703104.5}
    for driver_id in (1, 2, 3):
        config['drivers'].append({
            'id': driver_id, 'type': 'dynamixel', 'driver_model': 'XM430-W350',
            'rated_speed_rpm': 30, **old_dxl,
        })
    config['drivers'].append({
        'id': 4, 'type': 'feetech', 'driver_model': 'Feetech (버전 2)', 'rated_speed_rpm': 30.0,
        'speed': 180.0, 'acceleration': 703104.5, 'deceleration': 703104.5,
        'profile_velocity': 180.0, 'profile_acceleration': 703104.5, 'profile_deceleration': 703104.5,
    })
    return config


def _chicken2_registry(**overrides):
    motors = [
        _serial(0, 'dynamixel', 'XM430-W350', 1, model_number=1020, driver_id=1),
        _serial(1, 'dynamixel', 'XM430-W350', 2, model_number=1020, driver_id=2),
        _serial(2, 'dynamixel', 'XM430-W350', 3, model_number=1020, driver_id=3),
        _serial(3, 'feetech', 'Feetech (버전 2)', 1, port=CH340, driver_id=4),
    ]
    for axis, config in overrides.items():
        motors[int(axis[1:])]['config'].update(config)
    return {'motors': motors}


def test_new_serial_drivers_default_to_servo_max():
    for driver in (
        motor_config_build.default_dynamixel_driver(WORKSPACE, 'XM430-W350'),
        motor_config_build.default_dynamixel_driver(WORKSPACE, 'Model 9999'),
        motor_config_build.default_dynamixel_driver(WORKSPACE, 'XM540-W150'),
        motor_config_build.default_feetech_driver(WORKSPACE, 'STS3215'),
    ):
        assert {field: driver[field] for field in FIELDS} == dict.fromkeys(FIELDS, 0.0), driver['driver_model']
    # 정격 속도는 정보로 남는다 (수동 조작 상한 · 옛 화면 표시)
    assert motor_config_build.default_dynamixel_driver(WORKSPACE, 'XM540-W150')['rated_speed_rpm'] == 66
    assert motor_config_build.default_dynamixel_driver(WORKSPACE, 'XM430-W350')['rated_speed_rpm'] == 30
    assert motor_config_build.default_feetech_driver(WORKSPACE, 'STS3215')['rated_speed_rpm'] == 30.0


def test_ac_default_driver_is_unchanged():
    ac = motor_config_build.default_motor_config(WORKSPACE)['drivers'][0]
    assert (ac['speed'], ac['profile_velocity'], ac['profile_acceleration']) == (2000000.0, 18000.0, 180000.0)


def test_saved_old_defaults_become_servo_max_on_save():
    """chicken2 · 저장된 100 · 180 · 703104.5 → 다음 저장에서 0"""
    config = motor_config_build.motor_config_from_registry(
        WORKSPACE, _chicken2_registry(), _chicken2_saved_config(),
    )
    for axis in range(4):
        driver = _driver_for(config, axis)
        assert {field: driver[field] for field in FIELDS} == dict.fromkeys(FIELDS, 0.0), axis
    assert _driver_for(config, 0)['rated_speed_rpm'] == 30
    validate_runtime_motor_profiles(config)


def test_every_old_inherited_value_is_recognised():
    drivers = [
        {'id': 1, 'type': 'dynamixel', 'speed': 396.0, 'profile_velocity': 222.0,
         'acceleration': 703104.5, 'profile_acceleration': 703104.5},
        {'id': 2, 'type': 'feetech', 'speed': 180, 'profile_velocity': 180.0,
         'acceleration': 439.453125, 'profile_acceleration': 439.453125,
         'deceleration': 703104.5, 'profile_deceleration': 439.453125},
    ]
    migrated = motor_config_build.migrate_serial_profile_defaults(drivers)
    for driver in migrated:
        assert all(driver[field] == 0.0 for field in FIELDS if field in driver), driver
    assert drivers[0]['speed'] == 396.0      # 입력은 복사본으로 다룬다


def test_values_a_person_set_are_kept():
    drivers = [
        {'id': 1, 'type': 'dynamixel', 'profile_velocity': 120.0, 'profile_acceleration': 5000.0,
         'speed': 100.0, 'acceleration': 703104.5},
        # Feetech 에 다이나믹셀 옛 값 100 · Feetech 옛 기본이 아니므로 사람이 정한 값
        {'id': 2, 'type': 'feetech', 'profile_velocity': 100.0, 'profile_acceleration': 50.0},
    ]
    dxl, ft = motor_config_build.migrate_serial_profile_defaults(drivers)
    assert (dxl['profile_velocity'], dxl['profile_acceleration']) == (120.0, 5000.0)
    assert (dxl['speed'], dxl['acceleration']) == (0.0, 0.0)
    assert (ft['profile_velocity'], ft['profile_acceleration']) == (100.0, 50.0)


def test_ac_and_unknown_drivers_are_not_touched():
    drivers = [
        {'id': 0, 'type': 'minas', 'profile_velocity': 100.0, 'acceleration': 703104.5},
        {'id': 1, 'type': 'cubemars', 'speed': 180.0},
        {'id': 2, 'driver_model': 'x', 'speed': 100.0},
        'not a dict',
    ]
    assert motor_config_build.migrate_serial_profile_defaults(drivers) == drivers


def test_same_save_screen_value_survives_the_migration():
    """옮기기는 오버라이드보다 먼저 · 화면에 옛 기본과 같은 100 을 적어도 그 저장에서는 100"""
    registry = _chicken2_registry(m0={'profile_velocity': 100.0, 'profile_acceleration': 2000.0})
    config = motor_config_build.motor_config_from_registry(WORKSPACE, registry, _chicken2_saved_config())
    crank = _driver_for(config, 0)
    assert crank['profile_velocity'] == 100.0
    assert (crank['profile_acceleration'], crank['profile_deceleration']) == (2000.0, 2000.0)
    assert crank['speed'] == 0.0
    assert _driver_for(config, 1)['profile_velocity'] == 0.0


def test_screen_can_set_zero_explicitly():
    registry = _chicken2_registry(m3={'profile_velocity': 0, 'acceleration': 0, 'profile_acceleration': 0})
    saved = _chicken2_saved_config()
    saved['drivers'][-1].update(profile_velocity=90.0, profile_acceleration=300.0, acceleration=300.0)
    config = motor_config_build.motor_config_from_registry(WORKSPACE, registry, saved)
    head = _driver_for(config, 3)
    assert {field: head[field] for field in FIELDS} == dict.fromkeys(FIELDS, 0.0)


def test_speed_limit_check_ignores_zero():
    motor = {'axis': 0, 'config': {'profile_velocity': 0, 'max_speed_rpm': 10,
                                   'profile_acceleration': 0, 'acceleration': 0}}
    assert motor_config_build.axis_speed_limit_error(motor) == ''


def _runtime_payload(driver):
    return {
        'masters': [{'id': 0, 'type': 'serial', 'serial_port': U2D2,
                     'slaves': [{'controller_index': 0, 'driver_id': 0, 'bus_id': 1}]}],
        'drivers': [{'id': 0, **driver}],
    }


@pytest.mark.parametrize('kind', ['dynamixel', 'feetech'])
def test_apply_accepts_zero_for_serial_servos(kind):
    validate_runtime_motor_profiles(_runtime_payload(
        {'type': kind, 'profile_velocity': 0, 'profile_acceleration': 0.0, 'profile_deceleration': 0},
    ))


@pytest.mark.parametrize('bad', [-1, None, 'fast', float('nan')])
def test_apply_still_refuses_negative_or_missing_serial_values(bad):
    driver = {'type': 'dynamixel', 'profile_velocity': 0, 'profile_acceleration': 0, 'profile_deceleration': 0}
    driver['profile_velocity'] = bad
    with pytest.raises(ValueError, match='0 이상'):
        validate_runtime_motor_profiles(_runtime_payload(driver))


def test_apply_still_refuses_zero_for_ac_servos():
    payload = {
        'masters': [{'id': 0, 'type': 'ethercat', 'slaves': [{'controller_index': 0, 'driver_id': 0}]}],
        'drivers': [{'id': 0, 'type': 'minas', 'profile_velocity': 0,
                     'profile_acceleration': 180000, 'profile_deceleration': 180000}],
    }
    with pytest.raises(ValueError, match='0보다 크게'):
        validate_runtime_motor_profiles(payload)
