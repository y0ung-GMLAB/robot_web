"""MINAS 속도·가속 상한 · 운전값 2개 + 상한 2개 · 수정 목록 37 (2026-10-06)"""

import yaml

from motion_web_bridge import minas_params, motor_config_build


def _motor(**config):
    return {'axis': 0, 'motor_type': 'ac_servo', 'driver_family': 'minas', 'config': dict(config)}


def test_max_speed_rpm_goes_to_both_0x6080_and_0x607F(tmp_path):
    motor = _motor(max_speed_rpm=2000)

    overrides = motor_config_build._axis_profile_overrides(motor)
    params = minas_params.param_overrides(motor)
    path = minas_params.write_param_file(tmp_path, 0, params)
    items = yaml.safe_load(open(path, encoding='utf-8').read().split('\n', 3)[-1] if False else open(path, encoding='utf-8'))['items']

    assert overrides['speed'] == 2000.0                      # 0x6080 rpm
    by_index = {int(item['index']): item for item in items}
    assert by_index[0x607F]['value'] == round(2000 * 8388608 / 60)   # count/s
    assert by_index[0x607F]['value'] == 279620267


def test_one_profile_and_one_max_acceleration_field_set_both_directions():
    overrides = motor_config_build._axis_profile_overrides(
        _motor(profile_acceleration=90000, acceleration=180000),
    )
    assert overrides['profile_deceleration'] == 90000.0
    assert overrides['deceleration'] == 180000.0


def test_dynamixel_speed_meaning_is_left_alone():
    dxl = {'axis': 2, 'motor_type': 'dynamixel', 'driver_family': 'dynamixel', 'config': {'max_speed_rpm': 50}}
    assert 'speed' not in motor_config_build._axis_profile_overrides(dxl)


def test_max_must_not_be_below_profile():
    assert motor_config_build.axis_speed_limit_error(_motor(profile_velocity=18000, max_speed_rpm=2000)) != ''
    assert motor_config_build.axis_speed_limit_error(_motor(profile_velocity=12000, max_speed_rpm=2000)) == ''
    assert '최대 가속도' in motor_config_build.axis_speed_limit_error(
        _motor(profile_acceleration=200000, acceleration=180000),
    )
    assert motor_config_build.axis_speed_limit_error(_motor()) == ''


def test_out_of_range_rpm_is_not_sent_to_the_drive():
    assert 'max_profile_velocity_count' not in minas_params.param_overrides(_motor(max_speed_rpm=99999))
