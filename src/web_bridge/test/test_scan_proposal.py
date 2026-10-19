"""검색 결과 → 모터 설정 제안 · 서버 한 곳에서 · 수정 목록 100

짝 맞추기는 `scan_axis_rows`(test_the_server_pairs_the_scan) · 여기서는 「그래서 목록을 어떻게 바꾸나」.
옛 화면(adoptScanIntoDraft)과 달라진 것 · 검색한 통로만 바꿈 · 짝지은 모터의 이름·드라이브 연결을 지킴 ·
이름표는 서버 규칙 하나 · 번호는 빈칸 없이(바뀐 번호는 알림).
"""

from motion_web_bridge.motor_config_rules import motor_id_for
from motion_web_bridge.scan_proposal import proposed_registry

from test_the_server_pairs_the_scan import _device, _dynamixel, _scan, _servo, _slave


def _propose(motors, scan):
    return proposed_registry({'motors': motors}, scan)


def _by_axis(result):
    return {m['axis']: m for m in result['registry']['motors']}


def test_matched_motor_keeps_name_enabled_and_driver_link():
    servo = _servo(axis=0)
    servo['name'] = '목 상하'
    servo['enabled'] = False
    servo['config'].update({'driver_id': 4, 'master_id': 0})
    result = _propose([servo], _scan(slaves=[_slave()], dynamixel=False))
    motor = _by_axis(result)[0]
    assert motor['name'] == '목 상하'
    assert motor['enabled'] is False
    assert motor['config']['driver_id'] == 4, '드라이브 연결(속도·가속·브레이크 값)을 지킨다'
    assert motor['id'] == 'ac_servo_ethercat_master_0_alias_103'
    assert motor['profile'] == {'driver_model': 'MADLN05BE', 'model_confirmed': True, 'model_source': 'physical_sii'}
    assert motor['identity']['sii_order_number'] == 'MADLN05BE'
    assert result['summary']['matched'] == 1


def test_ac_only_scan_keeps_dynamixel_motors_untouched():
    servo = _servo(axis=0)
    dxl = _dynamixel(axis=1)
    result = _propose([servo, dxl], _scan(slaves=[_slave()], dynamixel=False))
    motors = _by_axis(result)
    assert motors[1]['id'] == dxl['id'], '검색 안 한 통로는 이름표도 그대로'
    assert motors[1]['name'] == dxl['name']
    assert result['summary']['kept'] == 1
    assert result['summary']['scanned_transports'] == ['ethercat']


def test_missing_motor_is_removed_with_a_note_and_numbers_close_up():
    first = _servo(axis=0, alias=101, slave=0, serial=1)
    second = _servo(axis=1, alias=102, slave=1, serial=2)
    third = _servo(axis=2, alias=103, slave=2, serial=3)
    scan = _scan(slaves=[_slave(alias=101, slave=0, serial=1), _slave(alias=103, slave=1, serial=3)], dynamixel=False)
    result = _propose([first, second, third], scan)
    motors = _by_axis(result)
    assert sorted(motors) == [0, 1]
    assert motors[1]['identity']['ethercat_alias'] == 103
    assert any('1번 · alias 102 · 검색되지 않아' in note for note in result['notes'])
    assert any('모터 번호가 바뀝니다 · 2번 → 1번' in note for note in result['notes'])
    assert result['summary'] == {'matched': 2, 'added': 0, 'removed': 1, 'kept': 0, 'renumbered': 1, 'scanned_transports': ['ethercat']}


def test_new_devices_come_after_and_get_server_ids():
    servo = _servo(axis=0)
    scan = _scan(slaves=[_slave(), _slave(alias=404, slave=1, serial=9)], devices=[_device(bus_id=5)])
    result = _propose([servo], scan)
    motors = _by_axis(result)
    assert [motors[i]['id'] for i in range(3)] == [
        'ac_servo_ethercat_master_0_alias_103',
        'ac_servo_ethercat_master_0_alias_404',
        motor_id_for(motor_type='dynamixel', transport='serial', axis=2, serial_port='/dev/ttyUSB0', bus_id=5),
    ]
    assert motors[1]['name'] == '모터 1', '새 모터 기본 이름 = 모터 번호 · 사용자 2026-10-13'
    assert motors[2]['name'] == '모터 2'
    assert motors[0]['name'] == servo['name'], '저장된 이름은 그대로'
    assert motors[2]['profile']['driver_model'] == 'XM540-W150'
    assert motors[2]['config']['serial_baudrate'] == 1_000_000
    assert result['summary']['added'] == 2


def test_changed_alias_gets_the_new_server_id_but_keeps_the_name():
    """alias 가 바뀐 드라이브 · 제조번호로 짝 · 이름은 남고 이름표는 새 alias 로 (전엔 이름이 풀렸다)"""
    servo = _servo(axis=0, alias=103)
    servo['name'] = '눈 좌우'
    result = _propose([servo], _scan(slaves=[_slave(alias=404)], dynamixel=False))
    motor = _by_axis(result)[0]
    assert motor['name'] == '눈 좌우'
    assert motor['id'] == 'ac_servo_ethercat_master_0_alias_404'
    assert any('바뀐 값 alias' in note for note in result['notes'])


def test_position_only_match_is_adopted_with_a_warning():
    servo = _servo(axis=0, alias=0, slave=2, serial=None)
    servo['identity'].pop('serial_number')
    result = _propose([servo], _scan(slaves=[_slave(alias=0, slave=2, serial=None)], dynamixel=False))
    assert result['summary']['matched'] == 1
    assert any('위치만 같아서 연결했습니다' in note for note in result['notes'])


def test_unknown_scanned_model_keeps_the_saved_one():
    servo = _servo(axis=0)
    servo['profile'] = {'driver_model': 'MBDLN25SE', 'model_confirmed': True, 'model_source': 'user_nameplate'}
    result = _propose([servo], _scan(slaves=[_slave(model='')], dynamixel=False))
    assert _by_axis(result)[0]['profile']['driver_model'] == 'MBDLN25SE'


def test_empty_project_gets_every_device_from_zero():
    result = _propose([], _scan(slaves=[_slave()], devices=[_device()]))
    assert [m['axis'] for m in result['registry']['motors']] == [0, 1]
    assert result['notes'] == []


def test_new_drives_in_front_of_the_chain_join_the_proposal():
    """floating4 2026-10-19 · 눈 3대(위치 0~2) 앞에 목 2대 · 제안에 5대 · 수정 목록 157"""
    from test_the_server_pairs_the_scan import _floating4

    saved, scanned = _floating4()
    result = _propose(saved, _scan(slaves=scanned, dynamixel=False))
    motors = result['registry']['motors']
    assert len(motors) == 5
    assert result['summary']['matched'] == 3
    assert sorted(m['identity']['serial_number'] for m in motors) == sorted(s['serial_number'] for s in scanned)
