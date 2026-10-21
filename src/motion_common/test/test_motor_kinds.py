"""모터 종류 표 · Feetech 가 아닌 모터는 옛 판정과 결과가 같다 · 수정 목록 158

사용자 조건 · AC 로봇 동작 변화 없음 · `feetech` 로 밝혀진 모터만 새 동작.
옛 구현(main aa21f9f6)을 글자 그대로 아래에 두고, 옛 모양의 모터 dict 를 넓게 만들어
옛·새 결과를 표로 맞춘다.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List
from urllib.parse import quote

from motion_common import motor_kinds, motor_ref
from motion_common.values import optional_int


# --------------------------------------------------------------------------- #
# 옛 구현 (HEAD 사본 · 바꾸지 말 것)
# --------------------------------------------------------------------------- #
def old_motor_type(motor: Dict[str, Any]) -> str:
    values = [
        motor.get('motor_type'),
        motor.get('motor_type_label'),
        motor.get('driver_model'),
        motor.get('driver_name'),
        motor.get('transport'),
    ]
    text = ' '.join(str(value or '').lower() for value in values)
    if 'dynamixel' in text:
        return 'dynamixel'
    if 'minas' in text or 'ac servo' in text or 'ac_servo' in text:
        return 'ac_servo'
    return 'unknown'


def old_motor_ref_for_motor(motor: Dict[str, Any]) -> str:
    kind = old_motor_type(motor)
    if kind == 'ac_servo':
        alias = optional_int(motor.get('alias', motor.get('ethercat_alias')))
        master_index = optional_int(motor.get('ethercat_master_index'))
        if master_index is None:
            master_index = 0
        if alias is not None and alias > 0 and master_index >= 0:
            return f'ac_servo:master:{master_index}:alias:{alias}'
        slave_position = optional_int(motor.get('slave_position'))
        return (
            f'ac_servo:master:{master_index}:slave:{slave_position}'
            if slave_position is not None
            and slave_position >= 0
            and master_index >= 0
            else ''
        )
    if kind == 'dynamixel':
        bus_id = optional_int(motor.get('bus_id', motor.get('node_id')))
        serial_port = str(motor.get('serial_port') or '').strip()
        return (
            f'dynamixel:port:{quote(serial_port, safe="")}:id:{bus_id}'
            if bus_id is not None and bus_id >= 0 and serial_port else ''
        )
    return ''


def old_motor_refs_for_motor(motor: Dict[str, Any]) -> List[str]:
    canonical = old_motor_ref_for_motor(motor)
    kind = old_motor_type(motor)
    if kind == 'ac_servo':
        alias = optional_int(motor.get('alias', motor.get('ethercat_alias')))
        legacy = f'ac_servo:alias:{alias}' if alias is not None and alias > 0 else ''
    elif kind == 'dynamixel':
        bus_id = optional_int(motor.get('bus_id', motor.get('node_id')))
        legacy = f'dynamixel:id:{bus_id}' if bus_id is not None and bus_id >= 0 else ''
    else:
        legacy = ''
    return [item for item in (canonical, legacy) if item]


def old_is_ac_servo(motor: Dict[str, Any]) -> bool:
    """`motor_config_rules.is_ac_servo_motor` · `supervisor_node._is_ac_servo` (같은 글자)"""
    values = [
        motor.get('motor_type'),
        motor.get('motor_type_label'),
        motor.get('driver_model'),
        motor.get('driver_name'),
        motor.get('transport'),
    ]
    text = ' '.join(str(value or '').lower() for value in values)
    return 'minas' in text or 'ac servo' in text or 'ac_servo' in text


def old_is_dynamixel_motor(motor: Dict[str, Any]) -> bool:
    """`motor_config_rules.is_dynamixel_motor`"""
    values = [
        motor.get('motor_type'),
        motor.get('motor_type_label'),
        motor.get('driver_model'),
        motor.get('driver_name'),
        motor.get('transport'),
    ]
    text = ' '.join(str(value or '').lower() for value in values)
    return 'dynamixel' in text


def old_supervisor_is_dynamixel(motor: Dict[str, Any]) -> bool:
    """`supervisor_node._is_dynamixel` · `serial` + `xm` 규칙"""
    values = [
        motor.get('motor_type'),
        motor.get('motor_type_label'),
        motor.get('driver_model'),
        motor.get('driver_name'),
        motor.get('transport'),
    ]
    text = ' '.join(str(value or '').lower() for value in values)
    return 'dynamixel' in text or 'serial' in text and 'xm' in text


# --------------------------------------------------------------------------- #
# 옛 모양의 모터 dict · 넓게
# --------------------------------------------------------------------------- #
MOTOR_TYPES = [None, '', 'ac_servo', 'AC_SERVO', 'minas', 'dynamixel', 'Dynamixel', 'unknown',
               'cubemars', 'zeroerr', 'serial', 'xm']
LABELS = [None, 'AC Servo', 'Dynamixel', 'Unknown', 'ZeroErr Motor', 'CubeMars', 'Serial']
MODELS = [None, 'MADLN05BE', 'MCDLN35BE', 'UNVERIFIED_MINAS', 'XM540-W270-R', 'XM430-W350', 'minas-a6', 'AK80']
TRANSPORTS = [None, 'ethercat', 'serial', 'can', 'unknown', 'EtherCAT']
ADDRESSES = [
    {},
    {'alias': 103, 'ethercat_master_index': 0, 'slave_position': 2},
    {'ethercat_alias': 0, 'slave_position': 1, 'ethercat_master_index': 1},
    {'bus_id': 3, 'serial_port': '/dev/serial/by-id/usb-FTDI-if00'},
    {'node_id': 0, 'serial_port': '/dev/ttyUSB0'},
    {'bus_id': -1, 'serial_port': ''},
]


def old_style_motors():
    for motor_type, label, model, transport, address in itertools.product(
        MOTOR_TYPES, LABELS, MODELS, TRANSPORTS, ADDRESSES,
    ):
        motor = {'motor_type': motor_type, 'motor_type_label': label, 'driver_model': model,
                 'transport': transport, **address}
        yield motor
        # driver_name 만 있는 경우 (motion_state 모양)
        yield {**motor, 'driver_model': None, 'driver_name': model}


def test_the_generator_has_no_feetech_input():
    assert not any(motor_kinds.is_feetech(m) for m in old_style_motors())


def test_every_non_feetech_motor_keeps_its_old_kind_and_names():
    count = 0
    for motor in old_style_motors():
        count += 1
        assert motor_ref.motor_type(motor) == old_motor_type(motor), motor
        assert motor_ref.motor_ref_for_motor(motor) == old_motor_ref_for_motor(motor), motor
        assert motor_ref.motor_refs_for_motor(motor) == old_motor_refs_for_motor(motor), motor
        assert motor_kinds.is_ac_servo(motor) == old_is_ac_servo(motor), motor
        assert motor_kinds.is_dynamixel(motor) == old_is_dynamixel_motor(motor), motor
        assert motor_kinds.is_dynamixel(motor, serial_xm_is_dynamixel=True) == old_supervisor_is_dynamixel(motor), motor
        # 직렬 서보 공통 = 옛 다이나믹셀 판정 (Feetech 가 없으면)
        assert motor_kinds.is_serial_servo(motor, serial_xm_is_dynamixel=True) == old_supervisor_is_dynamixel(motor), motor
        assert motor_kinds.is_serial_servo(motor) == old_is_dynamixel_motor(motor), motor
    assert count > 10000


def test_driver_type_kind_keeps_the_old_dynamixel_test_for_every_non_feetech_type():
    """`state_publisher` · 옛 `motor_type == 'dynamixel'` = 새 `is_serial_servo(kind_for_driver_type)`"""
    for driver_type in ['minas', 'dynamixel', 'zeroerr', 'cubemars', 'unknown', '', 'Dynamixel', 'MINAS', 'serial']:
        old = driver_type.lower() == 'dynamixel'
        assert motor_kinds.is_serial_servo(motor_kinds.kind_for_driver_type(driver_type.lower())) == old, driver_type


def test_feetech_is_checked_first_and_never_falls_into_dynamixel_heuristics():
    feetech = {'motor_type': 'feetech', 'motor_type_label': 'Feetech', 'driver_model': 'STS3215',
               'transport': 'serial', 'bus_id': 1, 'serial_port': '/dev/ttyUSB1'}
    assert motor_kinds.motor_kind(feetech) == 'feetech'
    assert motor_kinds.is_feetech(feetech)
    assert not motor_kinds.is_dynamixel(feetech, serial_xm_is_dynamixel=True)
    assert not motor_kinds.is_ac_servo(feetech)
    assert motor_kinds.is_serial_servo(feetech)
    assert motor_ref.motor_ref_for_motor(feetech) == 'feetech:port:%2Fdev%2FttyUSB1:id:1'
    assert motor_ref.motor_refs_for_motor(feetech) == ['feetech:port:%2Fdev%2FttyUSB1:id:1']   # 옛 이름 없음
    # 모델 이름에 xm 이 있어도 (serial + xm 추측) Feetech 다
    odd = {**feetech, 'driver_model': 'xm-like'}
    assert motor_kinds.motor_kind(odd, serial_xm_is_dynamixel=True) == 'feetech'


def test_kind_table_rows():
    table = motor_kinds.kind_table_payload()
    assert list(table) == ['ac_servo', 'dynamixel', 'feetech']
    assert [table[k]['short_label'] for k in table] == ['AC', 'DXL', 'FT']
    assert table['dynamixel']['capabilities']['reboot'] is True
    assert table['feetech']['capabilities']['reboot'] is False
    assert table['feetech']['capabilities']['torque_toggle'] is True
    assert table['ac_servo']['capabilities']['drive_gains'] is True
    assert table['feetech']['packet'] == 'scs' and table['dynamixel']['packet'] == 'dxl2'
    assert motor_kinds.kind_info('stepper') == {}
    assert not motor_kinds.is_serial_servo('unknown') and not motor_kinds.is_serial_servo('ac_servo')
