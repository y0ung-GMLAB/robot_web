"""드라이브 파라미터 고급 보기·쓰기 · 수정 목록 109 · 114 (2026-10-13)"""

from types import SimpleNamespace

import pytest

from motion_web_bridge.drive_params import CATALOG, DriveParams, parse_object, write_block_reason


def _params(values=None, *, blocker='', boot=None, fail_download=False):
    values = dict(values or {})
    calls = []
    records = []

    def runner(command, **_kwargs):
        calls.append(' '.join(command[1:]))
        index = int(command[-2 if command[1] == 'upload' else -3], 16)
        sub = int(command[-1 if command[1] == 'upload' else -2])
        if command[1] == 'download':
            if fail_download:
                return SimpleNamespace(returncode=1, stdout='', stderr='SDO abort')
            values[(index, sub)] = int(command[-1])
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if (index, sub) not in values:
            return SimpleNamespace(returncode=1, stdout='', stderr='SDO upload aborted')
        value = values[(index, sub)]
        return SimpleNamespace(returncode=0, stdout=f'0x{value & 0xFFFF:04x} {value}\n', stderr='')

    service = DriveParams(
        runner=runner, target=lambda axis: {'master': 0, 'position': axis},
        boot_values=lambda axis: dict(boot or {}), safety_blocker=lambda: blocker, record=records.append,
    )
    return service, calls, records, values


@pytest.mark.parametrize('text, expected', [
    ('Pr5.04', (0x3504, 0)), ('5.12', (0x3512, 0)), ('Pr6.31', (0x3631, 0)), ('Pr4.7', (0x3407, 0)),
    ('0x3504', (0x3504, 0)), ('3504h', (0x3504, 0)), ('0x607D:2', (0x607D, 2)),
])
def test_object_numbers_are_parsed_like_the_manual(text, expected):
    assert parse_object(text) == expected


def test_table_shows_drive_boot_and_factory_and_marks_differences():
    service, _calls, _records, _values = _params(
        {(0x3003, 0): 12, (0x3512, 0): 50, (0x3437, 0): 150}, boot={(0x3512, 0): 0, (0x3437, 0): 150},
    )
    rows = {row['number']: row for row in service.table(1)['rows']}
    assert rows['Pr0.03']['drive'] == 12 and rows['Pr0.03']['differs_factory'] is True
    assert rows['Pr5.12']['boot'] == 0 and rows['Pr5.12']['differs_boot'] is True     # EEPROM 에 50 이 남은 경우
    assert rows['Pr4.37']['differs_boot'] is False
    assert rows['0x607D:1']['boot'] == 'auto'                                        # 모터 설정에서 계산
    assert rows['Pr0.02']['drive'] is None and rows['Pr0.02']['error']               # 못 읽음 · 막지 않음
    assert len(service.table(1)['rows']) == len(CATALOG)


def test_write_reads_back_and_warns_when_boot_will_overwrite():
    service, calls, records, values = _params({(0x3504, 0): 1}, boot={(0x3437, 0): 150})
    result = service.write({'axis': 1, 'object': 'Pr5.04', 'type': 'int16', 'value': '0', 'confirmed': True})
    assert result['success'] is True and result['after'] == 0
    assert 'download -m 0 -p 1 -t int16 0x3504 0 0' in calls
    assert records[0]['event_type'] == 'minas_param_write' and records[0]['before'] == 1
    values[(0x3437, 0)] = 150
    warned = service.write({'axis': 1, 'object': 'Pr4.37', 'type': 'int16', 'value': '0', 'confirmed': True})
    assert '부팅 때 150' in warned['notes'][0]


@pytest.mark.parametrize('obj', ['0x1010:1', 'Pr0.15', '0x60B2', '0x6040', '0x1600', '0x1C12'])
def test_dangerous_or_dedicated_objects_cannot_be_written_here(obj):
    service, calls, _records, _values = _params()
    result = service.write({'axis': 1, 'object': obj, 'type': 'int16', 'value': '0', 'confirmed': True})
    assert result['success'] is False
    assert not [c for c in calls if c.startswith('download')]


def test_write_needs_confirmation_range_and_no_motion():
    service, _c, _r, _v = _params()
    assert service.write({'axis': 1, 'object': 'Pr5.04', 'value': '0'})['success'] is False
    assert '범위' in service.write({'axis': 1, 'object': 'Pr5.04', 'type': 'int16', 'value': '40000', 'confirmed': True})['message']
    moving, _c, _r, _v = _params(blocker='재생 중입니다')
    assert '재생 중' in moving.write({'axis': 1, 'object': 'Pr5.04', 'type': 'int16', 'value': '0', 'confirmed': True})['message']


def test_command_filters_are_in_the_catalog_so_drive_read_shows_them():
    """2026-10-16 · Pr2.22 지령 스무딩 · Pr2.23 지령 FIR · 「드라이브에서 읽기」 표에 · 0.1 ms 단위"""
    assert parse_object('Pr2.22') == (0x3222, 0) and parse_object('Pr2.23') == (0x3223, 0)
    service, _calls, _records, _values = _params({(0x3222, 0): 92, (0x3223, 0): 10})
    rows = {row['number']: row for row in service.table(1)['rows']}
    assert rows['Pr2.22']['drive'] == 92 and rows['Pr2.22']['differs_factory'] is False
    assert rows['Pr2.23']['drive'] == 10 and rows['Pr2.23']['group'] == '지령 필터'
    assert '0.1 ms' in rows['Pr2.22']['unit']


def test_0x60b2_reason_is_the_user_decision():
    assert '사용자 결정' in write_block_reason(0x60B2)


def test_table_and_write_are_refused_while_the_motor_program_configures_the_bus(monkeypatch):
    """수정 목록 125 · 모터 프로그램이 드라이브를 설정하는 동안엔 SDO 를 안 보낸다 · 표·쓰기에 이유"""
    from motion_common import ethercat_mailbox
    monkeypatch.setattr(ethercat_mailbox, 'configuring', lambda **_kw: True)
    service, calls, _records, _values = _params({(0x3003, 0): 12})
    rows = service.table(1)['rows']
    assert calls == []
    assert all('버스 설정 중' in row['error'] for row in rows)
    result = service.write({'confirmed': True, 'axis': 1, 'object': 'Pr0.03', 'type': 'int16', 'value': 13})
    assert calls == [] and result['success'] is False and '버스 설정 중' in result['message']
