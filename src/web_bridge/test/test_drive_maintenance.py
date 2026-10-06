"""MINAS 드라이브 정비 · EEPROM 저장 · 앱솔루트 방식 · 다회전 클리어 · 수정 목록 15 + 34-3"""

import threading
from types import SimpleNamespace

import pytest

from motion_web_bridge.drive_maintenance import (
    ABSOLUTE_CLEAR,
    ABSOLUTE_MODE,
    EEPROM_SAVE,
    DriveMaintenance,
    command_plan,
)


def test_command_plans_follow_the_manual():
    assert command_plan(EEPROM_SAVE, 0, 3) == [
        ['ethercat', 'download', '-m', '0', '-p', '3', '-t', 'uint32', '0x1010', '1', '0x65766173'],
    ]
    mode = command_plan(ABSOLUTE_MODE, 0, 3, 0)
    assert mode[0][-4:] == ['int16', '0x3015', '0', '0']
    assert mode[1][-3:] == ['0x1010', '1', '0x65766173']      # 속성 C · 저장해야 재투입 때 읽힌다
    clear = command_plan(ABSOLUTE_CLEAR, 1, 2)
    assert [command[-3:] for command in clear] == [
        ['0x4D01', '0', '0x0031'],
        ['0x4D00', '1', '0'],          # 0 을 먼저 · bit9 를 0→1 로 올린다
        ['0x4D00', '1', '0x0200'],
    ]
    with pytest.raises(ValueError):
        command_plan(ABSOLUTE_MODE, 0, 3, 7)


def _service(*, servo_on=False, vendor=0x066F, blocker='', returncodes=None, active=True):
    calls = []
    returncodes = list(returncodes or [])

    def runner(command, **_kwargs):
        calls.append(('cli', ' '.join(command[2:])))
        code = returncodes.pop(0) if returncodes else 0
        return SimpleNamespace(returncode=code, stdout='', stderr='SDO 거부' if code else '')

    records = []
    service = DriveMaintenance(
        runner=runner,
        read_slaves=lambda: [{'master_index': 0, 'slave_position': 2, 'vendor_id': vendor}],
        registry_motor=lambda axis: {'axis': axis, 'identity': {'slave_position': 2, 'ethercat_master_index': 0}}
        if axis == 1 else None,
        current_motor=lambda axis: {'controller_index': axis, 'servo_on': servo_on},
        safety_blocker=lambda: blocker,
        lifecycle_lock=threading.Lock(),
        motor_service=lambda: 'motion-motor.service',
        service_active=lambda _service: active,
        run_service=lambda action, _service: calls.append(('service', action)),
        wait_release=lambda: calls.append(('release',)),
        wait_recovery=lambda _service, axes: calls.append(('recovery', tuple(axes))) or {'service_active': True},
        expected_axes=lambda: [0, 1],
        record=records.append,
    )
    return service, calls, records


def test_eeprom_save_stops_writes_then_restores_motor_manager():
    service, calls, records = _service()

    result = service.run({'action': EEPROM_SAVE, 'axis': 1, 'confirmed': True})

    assert result['success'] is True
    assert [call[0] for call in calls] == ['service', 'release', 'cli', 'service', 'recovery']
    assert calls[0] == ('service', 'stop') and calls[3] == ('service', 'start')
    assert calls[4] == ('recovery', (0, 1))
    assert result['power_cycle_required'] is False
    assert records[0]['event_type'] == 'minas_eeprom_save' and records[0]['slave_position'] == 2


def test_absolute_clear_needs_servo_off_and_asks_for_power_cycle():
    service, calls, _records = _service(servo_on=True)
    refused = service.run({'action': ABSOLUTE_CLEAR, 'axis': 1, 'confirmed': True})
    assert refused['success'] is False and '서보를 먼저 끄세요' in refused['message']
    assert calls == []

    service, calls, _records = _service(servo_on=False)
    done = service.run({'action': ABSOLUTE_CLEAR, 'axis': 1, 'confirmed': True})
    assert done['success'] is True and done['power_cycle_required'] is True
    assert '기준점을 다시 캡처' in done['message']


def test_a_failed_write_stops_the_sequence_but_still_restores_motor_manager():
    service, calls, _records = _service(returncodes=[0, 1])

    result = service.run({'action': ABSOLUTE_MODE, 'axis': 1, 'value': 0, 'confirmed': True})

    assert result['success'] is False and 'SDO 거부' in result['message']
    assert [call for call in calls if call[0] == 'cli'] == [
        ('cli', '-m 0 -p 2 -t int16 0x3015 0 0'),
        ('cli', '-m 0 -p 2 -t uint32 0x1010 1 0x65766173'),
    ]
    assert ('service', 'start') in calls


@pytest.mark.parametrize('kwargs, payload, text', [
    ({}, {'action': EEPROM_SAVE, 'axis': 1}, '확인이 필요'),
    ({}, {'action': 'reboot', 'axis': 1, 'confirmed': True}, '지원하지 않는'),
    ({}, {'action': EEPROM_SAVE, 'axis': 9, 'confirmed': True}, '모터 설정에 없습니다'),
    ({'vendor': 0x0002}, {'action': EEPROM_SAVE, 'axis': 1, 'confirmed': True}, 'MINAS 가 아닙니다'),
    ({'blocker': '모션이 실행 중입니다'}, {'action': EEPROM_SAVE, 'axis': 1, 'confirmed': True}, '모션이 실행 중'),
])
def test_refusals_touch_nothing(kwargs, payload, text):
    service, calls, records = _service(**kwargs)

    result = service.run(payload)

    assert result['success'] is False and text in result['message']
    assert calls == [] and records == []
