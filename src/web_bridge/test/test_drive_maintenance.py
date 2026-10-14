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
    parse_upload_value,
    verify_command,
)


def test_command_plans_follow_the_manual():
    assert command_plan(EEPROM_SAVE, 0, 3) == [
        ['ethercat', 'download', '-m', '0', '-p', '3', '-t', 'uint32', '0x1010', '1', '0x65766173'],
    ]
    mode = command_plan(ABSOLUTE_MODE, 0, 3, 0)
    assert mode[0][-4:] == ['int16', '0x3015', '0', '0']
    assert mode[1][-3:] == ['0x1010', '1', '0x65766173']      # 속성 C · 저장해야 재투입 때 읽힌다
    clear = command_plan(ABSOLUTE_CLEAR, 1, 2)
    assert [command[-4:] for command in clear] == [
        ['uint16', '0x4D01', '0', '0x0031'],
        ['uint32', '0x4D00', '1', '0'],          # 0 을 먼저 · bit9 를 0→1 로 올린다
        ['uint32', '0x4D00', '1', '0x0200'],     # 0x4D00:01 은 uint32 · 수정 목록 66
    ]
    with pytest.raises(ValueError):
        command_plan(ABSOLUTE_MODE, 0, 3, 7)


def _service(*, servo_on=False, vendor=0x066F, blocker='', returncodes=None, active=True,
             upload_stdout='0x00000200 512\n'):
    calls = []
    returncodes = list(returncodes or [])

    def runner(command, **_kwargs):
        calls.append(('cli', ' '.join(command[1:])))
        code = returncodes.pop(0) if returncodes else 0
        stdout = upload_stdout if command[1] == 'upload' and not code else ''
        return SimpleNamespace(returncode=code, stdout=stdout, stderr='SDO 거부' if code else '')

    records = []
    cleared = []
    service = DriveMaintenance(
        runner=runner,
        read_slaves=lambda: [{'master_index': 0, 'slave_position': 2, 'vendor_id': vendor, 'serial_number': 77}],
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
        record_clear=lambda drives: (cleared.extend(drives), calls.append(('marker',))),
    )
    service.test_cleared = cleared
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
    assert '모든 프로젝트의 이 축 기준점이 무효' in done['message'] and '다시 지정' in done['message']
    # 클리어만 하는 길도 PC 단위 표시를 **명령 전에** 남긴다 · 수정 목록 140 ④
    assert calls[0] == ('marker',)
    assert service.test_cleared == [{
        'axis': 1, 'serial': 77, 'master_index': 0, 'slave_position': 2, 'source': 'drive_maintenance',
    }]
    # 쓰기 3번 뒤 되읽기 1번 · 수정 목록 66
    assert [call[1] for call in calls if call[0] == 'cli'] == [
        'download -m 0 -p 2 -t uint16 0x4D01 0 0x0031',
        'download -m 0 -p 2 -t uint32 0x4D00 1 0',
        'download -m 0 -p 2 -t uint32 0x4D00 1 0x0200',
        'upload -m 0 -p 2 -t uint32 0x4D00 1',
    ]
    assert done['commands'][-1]['value'] == 0x0200


def test_verify_only_for_absolute_clear():
    assert verify_command(EEPROM_SAVE, 0, 3) is None
    assert verify_command(ABSOLUTE_MODE, 0, 3) is None
    assert verify_command(ABSOLUTE_CLEAR, 1, 2) == [
        'ethercat', 'upload', '-m', '1', '-p', '2', '-t', 'uint32', '0x4D00', '1',
    ]
    assert parse_upload_value('0x00000200 512\n') == 0x200
    assert parse_upload_value('') is None
    assert parse_upload_value('SDO upload aborted') is None


@pytest.mark.parametrize('upload_stdout, returncodes, text', [
    ('0x00000000 0\n', None, 'bit9가 1이 아닙니다'),
    ('', None, '되읽기 실패'),
    ('', [0, 0, 0, 1], '되읽기 실패'),
])
def test_absolute_clear_readback_failure_is_a_failure(upload_stdout, returncodes, text):
    service, calls, records = _service(upload_stdout=upload_stdout, returncodes=returncodes)

    result = service.run({'action': ABSOLUTE_CLEAR, 'axis': 1, 'confirmed': True})

    assert result['success'] is False and text in result['message']
    assert result['power_cycle_required'] is False
    assert ('service', 'start') in calls
    assert records[0]['success'] is False


def test_a_failed_write_stops_the_sequence_but_still_restores_motor_manager():
    service, calls, _records = _service(returncodes=[0, 1])

    result = service.run({'action': ABSOLUTE_MODE, 'axis': 1, 'value': 0, 'confirmed': True})

    assert result['success'] is False and 'SDO 거부' in result['message']
    assert [call for call in calls if call[0] == 'cli'] == [
        ('cli', 'download -m 0 -p 2 -t int16 0x3015 0 0'),
        ('cli', 'download -m 0 -p 2 -t uint32 0x1010 1 0x65766173'),
    ]
    assert ('service', 'start') in calls


@pytest.mark.parametrize('kwargs, payload, text', [
    ({}, {'action': EEPROM_SAVE, 'axis': 1}, '확인이 필요'),
    ({}, {'action': 'reboot', 'axis': 1, 'confirmed': True}, '지원하지 않는'),
    ({}, {'action': EEPROM_SAVE, 'axis': 9, 'confirmed': True}, '모터 설정에 없습니다'),
    ({'vendor': 0x0002}, {'action': EEPROM_SAVE, 'axis': 1, 'confirmed': True}, 'MINAS가 아닙니다'),
    ({'blocker': '모션이 실행 중입니다'}, {'action': EEPROM_SAVE, 'axis': 1, 'confirmed': True}, '모션이 실행 중'),
])
def test_refusals_touch_nothing(kwargs, payload, text):
    service, calls, records = _service(**kwargs)

    result = service.run(payload)

    assert result['success'] is False and text in result['message']
    assert calls == [] and records == []


# -- 수정 목록 108 (다) · 게인 쓰기(재시작 없이) · 모든 축 EEPROM 저장(재시작 한 번) ---------------- #

def test_gain_write_does_not_stop_motor_manager_and_reads_back():
    service, calls, records = _service(upload_stdout='0x000c 12\n')
    result = service.write_gains({'axis': 1, 'values': {'stiffness': 12}, 'confirmed': True})
    assert result['success'] is True, result
    assert ('service', 'stop') not in calls                      # 토크가 풀리지 않게 재시작 없음
    assert ('cli', 'download -m 0 -p 2 -t int16 0x3003 0 12') in calls
    assert ('cli', 'upload -m 0 -p 2 -t int16 0x3003 0') in calls
    assert records[0]['event_type'] == 'minas_gain_write' and records[0]['read_back'] == {'stiffness': 12}


def test_gain_write_reports_a_readback_mismatch():
    service, _calls, _records = _service(upload_stdout='0x000d 13\n')
    result = service.write_gains({'axis': 1, 'values': {'stiffness': 12}, 'confirmed': True})
    assert result['success'] is False
    assert '되읽기 13 ≠ 12' in result['message']


@pytest.mark.parametrize('values, text', [
    ({'stiffness': 32}, '0~31'),
    ({'auto_tuning': 5}, '0~4'),            # 5 부하 특성 측정 · 6 사용자 정의는 안 엶
    ({'inertia_ratio': 200}, '바꿀 수 없는'),   # 관성비는 자동조정이 정함
])
def test_gain_write_refuses_out_of_range_or_closed_fields(values, text):
    service, calls, _records = _service()
    result = service.write_gains({'axis': 1, 'values': values, 'confirmed': True})
    assert result['success'] is False and text in result['message']
    assert not [c for c in calls if c[0] == 'cli' and c[1].startswith('download')]


def test_gain_write_needs_confirmation_and_no_motion():
    service, _calls, _records = _service()
    assert service.write_gains({'axis': 1, 'values': {'stiffness': 12}})['success'] is False
    moving, _c, _r = _service(blocker='재생 중입니다')
    assert '재생 중' in moving.write_gains({'axis': 1, 'values': {'stiffness': 12}, 'confirmed': True})['message']


def test_eeprom_save_all_restarts_motor_manager_once():
    service, calls, _records = _service()
    result = service.save_eeprom_all({'axes': [1], 'confirmed': True})
    assert result['success'] is True, result
    assert calls.count(('service', 'stop')) == 1 and calls.count(('service', 'start')) == 1
    assert ('cli', 'download -m 0 -p 2 -t uint32 0x1010 1 0x65766173') in calls


def test_message_says_when_servos_are_still_turning_on():
    """수정 목록 109 메모 · 온라인만 보고 「복구됨」 · 서보가 켜지기 전 재생을 누르면 거절됐다"""
    service, _calls, _records = _service()
    service._wait_recovery = lambda _service, axes: {'service_active': True, 'recovered': True, 'servo_waiting_axes': [0]}
    result = service.run({'action': EEPROM_SAVE, 'axis': 1, 'confirmed': True})
    assert '0번 서보가 아직 켜지는 중' in result['message']


def test_wait_for_servo_on_returns_when_all_ac_axes_are_on():
    from types import SimpleNamespace as NS
    from motion_web_bridge.motor_runtime_service import MotorRuntimeService
    states = iter([
        {'motors': [{'controller_index': 0, 'servo_on': False}, {'controller_index': 1, 'servo_on': True}]},
        {'motors': [{'controller_index': 0, 'servo_on': True}, {'controller_index': 1, 'servo_on': True}]},
    ])
    runtime = MotorRuntimeService.__new__(MotorRuntimeService)
    runtime.bridge = NS(motion_state=lambda: next(states))
    result = runtime.wait_for_servo_on([0, 1], timeout_sec=2.0)
    assert result['servo_on_axes'] == [0, 1] and result['servo_waiting_axes'] == []
