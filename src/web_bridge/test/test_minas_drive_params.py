"""MINAS 드라이브 파라미터 생성 · 브레이크 타이밍 · 과부하율 · P8 · 수정 목록 34

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
    assert minas_params.PARAM_FIELDS['brake_delay_stop_ms'][0] == 0x3437    # Pr4.37
    assert minas_params.PARAM_FIELDS['brake_delay_run_ms'][0] == 0x3438     # Pr4.38


def test_absolute_mode_and_limit_switch_are_never_written_at_boot(tmp_path):
    """수정 목록 34 · 매뉴얼 SX-DSV03241 R10.0 · 2026-10-06.

    Pr0.15 는 속성 C (재투입 때 EEPROM 을 다시 읽어 RAM 쓰기는 반영 안 됨) 이고
    예전 화면은 0/1 뜻이 반대였다 · Pr5.04 「1 사용 안 함」은 실제로 CiA402 감속
    정지다 · 둘 다 registry 에 옛 값이 남아 있어도 드라이브로 보내지 않는다.
    """
    assert 'encoder_absolute_mode' not in minas_params.PARAM_FIELDS
    assert 'limit_switch_mode' not in minas_params.PARAM_FIELDS
    motor = {'config': {
        'encoder_absolute_mode': 1, 'limit_switch_mode': 1, 'brake_delay_stop_ms': 100,
    }}
    overrides = minas_params.param_overrides(motor)
    assert overrides == {'brake_delay_stop_ms': 100}
    path = minas_params.write_param_file(tmp_path, 4, overrides)
    payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    indexes = {int(item['index']) for item in payload['items']}
    assert 0x3015 not in indexes and 0x3504 not in indexes


def test_out_of_range_drive_values_never_reach_the_drive():
    """화면이 먼저 막지만 · 파일을 손으로 고친 경우에도 이상한 값은 버린다."""
    motor = {'config': {
        'brake_delay_stop_ms': -50,      # 음수
        'brake_delay_run_ms': 999999,    # 과대
    }}
    assert minas_params.param_overrides(motor) == {}


def test_overrides_are_appended_to_the_item_list(tmp_path):
    path = minas_params.write_param_file(
        tmp_path, 7,
        {'brake_delay_run_ms': 80, 'brake_delay_stop_ms': 150},
    )
    assert Path(path).is_absolute()
    payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    by_index = {int(item['index']): item for item in payload['items']}
    assert by_index[0x3438]['value'] == 80
    assert by_index[0x3437]['value'] == 150
    assert by_index[0x3437]['type'] == 's16'
    # 기반 목록(운전 모드 등)은 그대로 실려 있다
    assert by_index[0x6060]['value'] == 1
    # PDO 배선 구획도 함께 복사된다 · 없으면 드라이버가 못 뜬다
    assert isinstance(payload.get('interfaces'), list) and payload['interfaces']
    # 항목 id 는 겹치지 않게 이어 붙인다
    ids = [int(item['id']) for item in payload['items'] if int(item.get('index') or 0) in (0x3438, 0x3437)]
    assert all(new_id > 58 for new_id in ids)


def test_an_existing_object_is_overwritten_not_duplicated(tmp_path):
    first = minas_params.write_param_file(tmp_path, 1, {'brake_delay_stop_ms': 100})
    # 같은 드라이버를 다시 쓰면(설정 변경) 값만 바뀐다
    second = minas_params.write_param_file(tmp_path, 1, {'brake_delay_stop_ms': 200})
    assert first == second
    payload = yaml.safe_load(Path(second).read_text(encoding='utf-8'))
    hits = [item for item in payload['items'] if int(item['index']) == 0x3437]
    assert len(hits) == 1 and hits[0]['value'] == 200


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
        _motor(0, brake_delay_stop_ms=200, encoder_absolute_mode=1),   # 옛 키는 무시
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
    assert values[0x3437] == 200 and 0x3015 not in values
    # 오버라이드 없는 모터는 플랫폼 param 경로 그대로
    assert 'minas_params' not in str(drivers[driver_of[1]]['param_file'])


def test_the_generated_file_warns_against_hand_edits(tmp_path):
    path = minas_params.write_param_file(tmp_path, 3, {'brake_delay_run_ms': 0})
    text = Path(path).read_text(encoding='utf-8')
    assert '다시 만들어진다' in text
    assert 'brake_delay_run_ms=0' in text


# --------------------------------------------------------------------------- #
# 과부하율 읽기 · 4D29h 를 TxPDO 에 · 모터별 선택 · 기본 꺼짐 · 2026-10-02
# --------------------------------------------------------------------------- #

def _interfaces(path):
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))['interfaces']


def test_overload_monitor_is_off_unless_asked():
    """빈 칸·0 = 플랫폼 그대로 · 제 파일을 만들 이유가 아니다 ·
    Ver1.03 미만 드라이브에 매핑하면 motor_manager 가 안 뜬다."""
    assert minas_params.param_overrides({'config': {}}) == {}
    assert minas_params.param_overrides({'config': {'overload_monitor': 0}}) == {}
    assert minas_params.param_overrides({'config': {'overload_monitor': 7}}) == {}
    assert minas_params.param_overrides({'config': {'overload_monitor': 1}}) == {'overload_monitor': 1}


def test_overload_monitor_adds_only_the_pdo_entry(tmp_path):
    path = minas_params.write_param_file(tmp_path, 2, {'overload_monitor': 1})
    payload = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    interfaces = payload['interfaces']
    assert interfaces[-1] == {'id': 12, 'index': 0x4D29, 'subindex': 0, 'size': 2, 'type': 'u16'}
    # TxPDO 구획 안 · 0x1A00 머리 뒤
    headers = [i for i, item in enumerate(interfaces) if 'subindex' not in item]
    assert interfaces[headers[-1]]['index'] == 0x1A00
    # SDO 목록에는 아무것도 더하지 않는다
    assert all(int(item['index']) != 0x4D29 for item in payload['items'])


def test_overload_monitor_is_added_once(tmp_path):
    first = minas_params.write_param_file(tmp_path, 3, {'overload_monitor': 1, 'brake_delay_stop_ms': 100})
    indexes = [int(item['index']) for item in _interfaces(first)]
    assert indexes.count(0x4D29) == 1


def test_overload_entry_id_matches_motor_manager():
    """화면 설정 → yaml id 12 → motor_manager `ID_OVERLOAD_RATIO` · 어긋나면 예외로 멈춘다."""
    header = (WORKSPACE / 'src/motion_system/lib/motor_manager/core/motor_interface/include/'
              'motor_interface/motor_driver.hpp').read_text(encoding='utf-8')
    assert 'ID_OVERLOAD_RATIO = 12;' in header
    assert minas_params.MONITOR_FIELDS['overload_monitor'][0]['id'] == 12
