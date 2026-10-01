"""드라이버는 **모터마다 하나**다 · 운전 한계를 모터별로 다르게 둘 수 있어야 한다.

전에는 같은 모델이면 첫 드라이버를 여러 모터가 공유했다 · 한 모터의 상한을
고치면 같은 모델 전부가 같이 움직였다 · 목(1:150)과 눈(1:35)이 같은 한계를
쓰게 된다.

registry `motor.config` 의 오버라이드(lower/upper/speed/…)는 그 모터의
드라이버에만 얹힌다 · motion_system 이 읽는 YAML 스키마는 그대로다
(slaves[j].driver_id → drivers[k]).
"""

from pathlib import Path

from motion_web_bridge.motor_config_build import (
    AXIS_PROFILE_OVERRIDE_FIELDS,
    default_motor_config,
    motor_config_from_registry,
)

WORKSPACE = Path(__file__).resolve().parents[3]


def _motor(axis, *, name=None, model='MADLN05BE', **config_overrides):
    return {
        'id': f'ac-{axis}',
        'enabled': True,
        'axis': axis,
        'name': name or f'모터 {axis}',
        'motor_type': 'ac_servo',
        'driver_family': 'minas',
        'transport': 'ethercat',
        'identity': {
            'ethercat_master_index': 0,
            'ethercat_alias': 0,
            'slave_position': axis,
        },
        'profile': {'driver_model': model, 'model_confirmed': True},
        'config': {'controller_index': axis, **config_overrides},
    }


def _build(motors, current=None):
    registry = {'motors': motors}
    return motor_config_from_registry(
        WORKSPACE, registry, current or default_motor_config(WORKSPACE),
    )


def _slave(config, axis):
    for master in config['masters']:
        for slave in master.get('slaves', []):
            if slave.get('controller_index') == axis:
                return slave
    raise AssertionError(f'축 {axis} 슬레이브가 없다')


def _driver(config, driver_id):
    return next(d for d in config['drivers'] if d.get('id') == driver_id)


def test_same_model_axes_get_their_own_drivers():
    config = _build([_motor(0), _motor(1), _motor(2)])
    ids = [_slave(config, axis)['driver_id'] for axis in (0, 1, 2)]
    assert len(set(ids)) == 3, f'드라이버가 공유된다: {ids}'
    # 모델 사실은 전부 같다
    assert {_driver(config, i)['driver_model'] for i in ids} == {'MADLN05BE'}


def test_axis_overrides_land_only_on_that_axis_driver():
    config = _build([
        _motor(0, lower=-1200.0, upper=1200.0, profile_velocity=9000.0),
        _motor(1),
    ])
    driver0 = _driver(config, _slave(config, 0)['driver_id'])
    driver1 = _driver(config, _slave(config, 1)['driver_id'])
    assert driver0['lower'] == -1200.0
    assert driver0['upper'] == 1200.0
    assert driver0['profile_velocity'] == 9000.0
    assert driver1['lower'] != -1200.0 or driver1['profile_velocity'] != 9000.0
    assert driver1['profile_velocity'] == 18000.0   # 기본값 그대로


def test_hand_tuned_existing_driver_values_survive_for_its_axis():
    """첫 모터는 기존 드라이버(손으로 다듬은 값)를 그대로 물려받는다."""
    current = default_motor_config(WORKSPACE)
    current['drivers'][0]['speed'] = 123456.0
    current['drivers'][0]['driver_model'] = 'MADLN05BE'
    config = _build([_motor(0, driver_id=0), _motor(1, driver_id=0)], current)
    driver0 = _driver(config, _slave(config, 0)['driver_id'])
    driver1 = _driver(config, _slave(config, 1)['driver_id'])
    assert driver0['speed'] == 123456.0
    # 둘째 모터는 복제본 · 본보기 값은 이어받는다
    assert driver1['speed'] == 123456.0
    assert driver0 is not driver1
    assert _slave(config, 0)['driver_id'] != _slave(config, 1)['driver_id']


def test_rebuilding_from_the_split_config_is_stable():
    """저장을 두 번 해도 드라이버가 또 불어나지 않는다."""
    first = _build([_motor(0, driver_id=0), _motor(1, driver_id=0)])
    ids = {axis: _slave(first, axis)['driver_id'] for axis in (0, 1)}
    motors = [
        _motor(0, driver_id=ids[0]),
        _motor(1, driver_id=ids[1]),
    ]
    second = _build(motors, first)
    assert _slave(second, 0)['driver_id'] == ids[0]
    assert _slave(second, 1)['driver_id'] == ids[1]
    assert len(second['drivers']) == len(first['drivers'])


def test_override_field_list_matches_the_editable_screen_fields():
    assert set(AXIS_PROFILE_OVERRIDE_FIELDS) == {
        'lower', 'upper', 'speed', 'acceleration', 'deceleration',
        'profile_velocity', 'profile_acceleration', 'profile_deceleration',
    }
