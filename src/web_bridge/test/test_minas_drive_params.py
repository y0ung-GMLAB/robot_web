"""MINAS 드라이브 파라미터 생성 · 브레이크 타이밍 · 앱솔루트 모드 · P8

드라이버 yaml 키가 아니라 `param_file`(부팅 때 쓰는 SDO 목록)로 들어간다 ·
오버라이드가 있는 모터만 제 param 파일을 받고, 없는 모터는 플랫폼 경로
그대로다 · 객체 번호는 Pr X.YY → 0x3XYY (0x3511 = Pr5.11 로 확인).
"""

from pathlib import Path

import yaml

from motion_web_bridge import minas_params
from motion_web_bridge.motor_config_build import (
    default_motor_config,
    motor_config_from_registry,
)

WORKSPACE = Path(__file__).resolve().parents[3]


def test_field_table_pins_the_minas_objects():
    assert minas_params.PARAM_FIELDS['encoder_absolute_mode'][0] == 0x3015   # Pr0.15
    assert minas_params.PARAM_FIELDS['brake_delay_stop_ms'][0] == 0x3437    # Pr4.37
    assert minas_params.PARAM_FIELDS['brake_delay_run_ms'][0] == 0x3438     # Pr4.38
    assert minas_params.PARAM_FIELDS['limit_switch_mode'][0] == 0x3504      # Pr5.04


def test_out_of_range_drive_values_never_reach_the_drive():
    """화면이 먼저 막지만 · 파일을 손으로 고친 경우에도 이상한 값은 버린다.

    특히 리밋 스위치 · 스위치 없는 축에 0/2 가 가면 못 움직이거나 알람이다 ·
    그 판단은 사람이 하되, 정해진 0/1/2 밖의 숫자는 아예 보내지 않는다.
    """
    motor = {'config': {
        'limit_switch_mode': 5,          # 0/1/2 밖
        'encoder_absolute_mode': -1,     # 0/1/2 밖
        'brake_delay_stop_ms': -50,      # 음수
        'brake_delay_run_ms': 999999,    # 과대
    }}
    assert minas_params.param_overrides(motor) == {}


def test_limit_switch_mode_values_pass_through():
    for value in (0, 1, 2):
        motor = {'config': {'limit_switch_mode': value}}
        assert minas_params.param_overrides(motor) == {'limit_switch_mode': value}


def test_blank_limit_switch_leaves_the_drive_alone(tmp_path):
    """빈 칸 = 드라이브에 있는 값 그대로 · 항목 자체를 넣지 않는다."""
    motor = {'config': {'brake_delay_stop_ms': 100}}   # 리밋 스위치는 안 적음
    overrides = minas_params.param_overrides(motor)
    path = minas_params.write_param_file(tmp_path, 4, overrides)
    payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    indexes = {int(item['index']) for item in payload['items']}
    assert 0x3504 not in indexes, '안 적었는데 리밋 스위치 항목이 들어갔다'


def test_overrides_are_appended_to_the_item_list(tmp_path):
    path = minas_params.write_param_file(
        tmp_path, 7,
        {'encoder_absolute_mode': 1, 'brake_delay_stop_ms': 150},
    )
    assert Path(path).is_absolute()
    payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    by_index = {int(item['index']): item for item in payload['items']}
    assert by_index[0x3015]['value'] == 1
    assert by_index[0x3437]['value'] == 150
    assert by_index[0x3437]['type'] == 's16'
    # 기반 목록(운전 모드 등)은 그대로 실려 있다
    assert by_index[0x6060]['value'] == 1
    # PDO 배선 구획도 함께 복사된다 · 없으면 드라이버가 못 뜬다
    assert isinstance(payload.get('interfaces'), list) and payload['interfaces']
    # 항목 id 는 겹치지 않게 이어 붙인다
    ids = [int(item['id']) for item in payload['items'] if int(item.get('index') or 0) in (0x3015, 0x3437)]
    assert all(new_id > 58 for new_id in ids)


def test_an_existing_object_is_overwritten_not_duplicated(tmp_path):
    first = minas_params.write_param_file(tmp_path, 1, {'encoder_absolute_mode': 1})
    # 같은 드라이버를 다시 쓰면(설정 변경) 값만 바뀐다
    second = minas_params.write_param_file(tmp_path, 1, {'encoder_absolute_mode': 2})
    assert first == second
    payload = yaml.safe_load(Path(second).read_text(encoding='utf-8'))
    hits = [item for item in payload['items'] if int(item['index']) == 0x3015]
    assert len(hits) == 1 and hits[0]['value'] == 2


def _motor(axis, **config_overrides):
    return {
        'id': f'ac-{axis}', 'enabled': True, 'axis': axis,
        'name': f'모터 {axis}', 'motor_type': 'ac_servo',
        'driver_family': 'minas', 'transport': 'ethercat',
        'identity': {
            'ethercat_master_index': 0, 'ethercat_alias': 0,
            'slave_position': axis,
        },
        'profile': {'driver_model': 'MADLN05BE', 'model_confirmed': True},
        'config': {'controller_index': axis, **config_overrides},
    }


def test_only_motors_with_drive_params_get_their_own_param_file(tmp_path):
    registry = {'motors': [
        _motor(0, brake_delay_stop_ms=200, encoder_absolute_mode=1),
        _motor(1),
    ]}
    config = motor_config_from_registry(
        tmp_path, registry, default_motor_config(WORKSPACE),
    )
    slaves = [
        slave for master in config['masters']
        for slave in master.get('slaves', [])
    ]
    driver_of = {slave['controller_index']: slave['driver_id'] for slave in slaves}
    drivers = {driver['id']: driver for driver in config['drivers']}
    with_params = drivers[driver_of[0]]['param_file']
    assert 'minas_params' in with_params and with_params.endswith('.yaml')
    payload = yaml.safe_load(Path(with_params).read_text(encoding='utf-8'))
    values = {int(item['index']): item['value'] for item in payload['items']}
    assert values[0x3437] == 200 and values[0x3015] == 1
    # 오버라이드 없는 모터는 플랫폼 param 경로 그대로
    assert 'minas_params' not in str(drivers[driver_of[1]]['param_file'])


def test_the_generated_file_warns_against_hand_edits(tmp_path):
    path = minas_params.write_param_file(tmp_path, 3, {'brake_delay_run_ms': 0})
    text = Path(path).read_text(encoding='utf-8')
    assert '다시 만들어진다' in text
    assert 'brake_delay_run_ms=0' in text
