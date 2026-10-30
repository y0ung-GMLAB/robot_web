"""직렬 서보 설정 · param 파일 · 직렬 마스터 · 한 포트 한 종류 · Feetech 한 바퀴 · 검색 → 목록 · 수정 목록 158"""

from pathlib import Path

import pytest
import yaml

from motion_web_bridge import (
    bridge_helpers,
    mapping_motor_limits,
    motor_config_build,
    motor_config_rules,
    scan_axis_rows,
    scan_proposal,
    serial_params,
)

WORKSPACE = Path(__file__).resolve().parents[3]
U2D2 = '/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT1-if00-port0'
U2D2_B = '/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FT2-if00-port0'


@pytest.fixture(autouse=True)
def _generated_files_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(serial_params, 'output_root', lambda _root: tmp_path / 'serial_params')
    from motion_web_bridge import minas_params

    monkeypatch.setattr(minas_params, 'OUTPUT_DIR', str(tmp_path / 'minas_params'))


def _serial(axis, kind, model, bus_id, *, port=U2D2, baudrate=1000000, model_number=None):
    return {
        'id': f'{kind}-{axis}', 'enabled': True, 'axis': axis, 'name': f'모터 {axis}',
        'motor_type': kind, 'driver_family': kind, 'transport': 'serial',
        'identity': {'serial_port': port, 'serial_baudrate': baudrate, 'bus_id': bus_id,
                     'model_number': model_number},
        'profile': {'driver_model': model, 'model_confirmed': True},
        'config': {'controller_index': axis},
    }


def _build(motors):
    return motor_config_build.motor_config_from_registry(
        WORKSPACE, {'motors': motors}, motor_config_build.default_motor_config(WORKSPACE),
    )


def _param(config, axis):
    for master in config['masters']:
        for slave in master.get('slaves', []):
            if slave['controller_index'] == axis:
                driver = next(d for d in config['drivers'] if d['id'] == slave['driver_id'])
                return driver, yaml.safe_load(Path(driver['param_file']).read_text(encoding='utf-8')), master
    raise AssertionError(axis)


def test_p_series_xl330_and_sts3215_param_files():
    config = _build([
        _serial(0, 'dynamixel', 'PH42-020-S300', 1, model_number=2000),
        _serial(1, 'dynamixel', 'XL330-M288', 2, model_number=1200),
        _serial(2, 'dynamixel', 'XL430-W250', 3, model_number=1060),
        _serial(3, 'feetech', 'STS3215', 1, port=U2D2_B, model_number=777),
    ])
    driver, ph, _ = _param(config, 0)
    assert ph['extended_position_raw_limit'] == 2147483647 and ph['acceleration_unit'] == 0.1
    assert Path(ph['model_file']).name == 'ph42_020_s300.model' and Path(ph['model_file']).is_absolute()
    assert driver['profile_position_value'] == 4 and driver['pulse_per_revolution'] == 607500
    assert driver['unit_effort'] == 0.001

    driver, xl330, _ = _param(config, 1)
    assert Path(xl330['model_file']).name == 'xl330_m288.model'
    assert 'acceleration_unit' not in xl330 and xl330['extended_position_raw_limit'] == 1048575
    assert driver['unit_effort'] == 0.001

    _driver, xl430, _ = _param(config, 2)
    optional = {e['name'] for e in xl430['interfaces'] if e.get('optional')}
    assert optional == {'Goal Current', 'Present Current'}   # 전류 없는 모델

    driver, sts, master = _param(config, 3)
    assert driver['type'] == 'feetech' and driver['profile_position_value'] == 0
    assert driver['profile_velocity'] == 0 and driver['profile_acceleration'] == 0   # 0 = 서보 최대 · 수정 목록 163
    assert (driver['lower'], driver['upper']) == (-180.0, 180.0)
    assert sts['protocol']['packet'] == 'scs' and sts['protocol']['reboot'] == 0
    assert sts['protocol']['sync_read'] == 130 and sts['protocol']['sync_write'] == 131
    assert sts['byte_order'] == 'little' and sts['acceleration_unit'] == 8.7890625
    assert (sts['position_raw_min'], sts['position_raw_max']) == (0, 4095)
    assert sts['model_file'].replace('\\', '/').endswith('hardware/feetech/control_table/sts.model')
    torque = [e for e in sts['interfaces'] if e.get('name') == 'Goal Position']
    assert torque[0]['sign_bit'] == 15
    assert master['serial_port'] == U2D2_B and master['serial_baudrate'] == 1000000
    header = Path(driver['param_file']).read_text(encoding='utf-8').splitlines()[0]
    assert '손으로 고치지 말 것' in header


def test_unsupported_dynamixel_model_is_refused_at_save():
    with pytest.raises(ValueError, match='XL320'):
        _build([_serial(0, 'dynamixel', 'XL320', 1, model_number=350)])


def test_serial_master_baudrate_comes_from_the_scan_and_1mbps_only_when_unknown():
    config = _build([
        _serial(0, 'dynamixel', 'XM430-W350', 1, baudrate=57600, model_number=1020),
        _serial(1, 'feetech', 'STS3215', 2, port=U2D2_B, baudrate=500000, model_number=777),
        _serial(2, 'dynamixel', 'XM430-W350', 3, port='/dev/ttyUSB7', baudrate=None, model_number=1020),
    ])
    bauds = {m['serial_port']: m['serial_baudrate'] for m in config['masters'] if m['type'] == 'serial'}
    assert bauds == {U2D2: 57600, U2D2_B: 500000, '/dev/ttyUSB7': 1000000}


def test_one_port_carries_one_kind_only():
    with pytest.raises(ValueError, match='한 포트에는 한 종류만'):
        _build([
            _serial(0, 'dynamixel', 'XM430-W350', 1, model_number=1020),
            _serial(1, 'feetech', 'STS3215', 2, model_number=777),
        ])
    masters = [{'type': 'serial', 'serial_port': U2D2, 'slaves': [{'driver_id': 1}, {'driver_id': 2}]}]
    drivers = [{'id': 1, 'type': 'dynamixel'}, {'id': 2, 'type': 'feetech'}]
    assert serial_params.port_kind_conflicts(masters, drivers)
    assert not serial_params.port_kind_conflicts(masters, [{'id': 1, 'type': 'dynamixel'}, {'id': 2, 'type': 'dynamixel'}])


def test_one_port_carries_one_baudrate_only():
    """chicken2 2026-10-29 · U2D2 한 포트에 1 Mbps 둘 · 57600 하나 → 마스터 둘(한 선을 두 번 열기) · 수정 목록 161"""
    chicken2 = [
        _serial(0, 'dynamixel', 'XM430-W350', 1, model_number=1020),
        _serial(1, 'dynamixel', 'XM430-W350', 2, model_number=1020),
        _serial(2, 'dynamixel', 'XM430-W350', 3, baudrate=57600, model_number=1020),
    ]
    with pytest.raises(ValueError, match='한 포트에는 한 속도만') as refused:
        _build(chicken2)
    assert U2D2 in str(refused.value)
    assert '57,600 bps · 2번 모터' in str(refused.value)

    # 속도 칸이 빈 다이나믹셀 = 1 Mbps · 1 Mbps 와 같이 있어도 된다
    _build([chicken2[0], _serial(1, 'dynamixel', 'XM430-W350', 2, baudrate=None, model_number=1020)])
    # 끈 모터 · 지운 모터는 보지 않는다
    off = dict(chicken2[2], enabled=False)
    gone = dict(chicken2[2], deleted=True)
    _build([chicken2[0], chicken2[1], off])
    _build([chicken2[0], chicken2[1], gone])
    # 다른 포트면 속도가 달라도 된다
    _build([chicken2[0], _serial(1, 'dynamixel', 'XM430-W350', 1, port=U2D2_B, baudrate=57600, model_number=1020)])


def test_a_hand_written_config_with_one_port_at_two_baudrates_is_refused_too():
    """설정 파일 저장 길 · 만든 설정의 직렬 마스터로 본다 · 수정 목록 161"""
    masters = [
        {'type': 'serial', 'serial_port': U2D2, 'serial_baudrate': 1000000,
         'slaves': [{'controller_index': 0}, {'controller_index': 1}]},
        {'type': 'serial', 'serial_port': U2D2, 'serial_baudrate': 57600, 'slaves': [{'controller_index': 2}]},
        {'type': 'ethercat', 'slaves': [{'controller_index': 3}]},
    ]
    conflicts = serial_params.port_baudrate_conflicts(masters)
    assert len(conflicts) == 1 and '1,000,000 bps · 0·1번 모터 / 57,600 bps · 2번 모터' in conflicts[0]
    assert not serial_params.port_baudrate_conflicts(masters[:1] + masters[2:])


def _mapping_row(ref, lower_deg, upper_deg, *, reference_deg=0.0, gear=1.0, scale=1.0):
    import math

    return {
        'motion_id': 'j', 'enabled': True, 'motor_ref': ref,
        'motion_lower_rad': math.radians(lower_deg), 'motion_upper_rad': math.radians(upper_deg),
        'reference_position_rad': math.radians(reference_deg), 'offset_rad': 0.0,
        'scale': scale, 'gear_ratio': gear, 'invert': False,
    }


def test_feetech_motor_range_must_fit_one_turn():
    config = _build([_serial(0, 'feetech', 'STS3215', 1, model_number=777)])
    ref = f'feetech:port:{__import__("urllib.parse").parse.quote(U2D2, safe="")}:id:1'
    inside, _ = mapping_motor_limits.apply_mapping_limits(config, {'mappings': [_mapping_row(ref, -90, 90, gear=2.0)]})
    assert mapping_motor_limits.single_turn_errors(inside) == []
    outside, changes = mapping_motor_limits.apply_mapping_limits(
        config, {'mappings': [_mapping_row(ref, -90, 90, gear=2.0, reference_deg=30)]},
    )
    assert changes
    errors = mapping_motor_limits.single_turn_errors(outside)
    assert errors and 'Feetech 한 바퀴' in errors[0]
    # AC · 다이나믹셀 드라이버는 이 검사와 무관
    dxl = _build([_serial(0, 'dynamixel', 'XM430-W350', 1, model_number=1020)])
    dxl['drivers'][-1]['lower'], dxl['drivers'][-1]['upper'] = -9000.0, 9000.0
    assert mapping_motor_limits.single_turn_errors(dxl) == []


def test_feetech_scan_becomes_registry_rows_and_feetech_motor_refs():
    scan = {
        'ethercat_scan': {'skipped': True},
        'dynamixel_scan': {'skipped': True},
        'feetech_scan': {
            'available': True, 'complete': True, 'devices_count': 2,
            'devices': [
                {'id': 1, 'bus_id': 1, 'port': U2D2_B, 'serial_port': U2D2_B, 'baudrate': 500000,
                 'model_number': 777, 'model_name': 'STS3215', 'model_confirm': False, 'source': 'id_ping'},
                {'id': 2, 'bus_id': 2, 'port': U2D2_B, 'serial_port': U2D2_B, 'baudrate': 500000,
                 'model_number': 1234, 'model_name': 'Feetech (버전 1234)', 'model_confirm': True, 'source': 'id_ping'},
            ],
        },
    }
    registry = {'motors': [
        {'id': 'ac', 'enabled': True, 'axis': 0, 'motor_type': 'ac_servo', 'driver_family': 'minas',
         'transport': 'ethercat', 'identity': {'slave_position': 0}, 'config': {'controller_index': 0}},
        _serial(1, 'dynamixel', 'XM430-W350', 1, model_number=1020),
    ]}
    rows = scan_axis_rows.axis_rows_from_scan(registry, scan)
    assert rows['scanned_kinds'] == ['feetech']
    assert rows['scanned_transports'] == []          # 다이나믹셀을 안 봤으므로 serial 은 전처럼 없음
    assert [row['state'] for row in rows['axes']] == ['not_scanned', 'not_scanned']
    assert [row['motor_type'] for row in rows['new_devices']] == ['feetech', 'feetech']
    proposal = scan_proposal.proposed_registry(registry, scan, rows)
    new = [m for m in proposal['registry']['motors'] if m['motor_type'] == 'feetech']
    assert [m['identity']['serial_baudrate'] for m in new] == [500000, 500000]
    assert [m['identity']['model_number'] for m in new] == [777, 1234]
    assert new[1]['profile']['model_confirmed'] is False
    assert new[0]['driver_family'] == 'feetech'
    # 그대로 저장해도 된다 · Feetech 포트에 다른 종류 없음
    config = motor_config_build.motor_config_from_registry(
        WORKSPACE, {'motors': [m for m in proposal['registry']['motors'] if m['transport'] == 'serial']},
        motor_config_build.default_motor_config(WORKSPACE),
    )
    kinds = {d['type'] for d in config['drivers']}
    assert 'feetech' in kinds


def test_full_scan_outcome_ignores_an_unused_feetech_bus():
    ethercat = {'available': True, 'complete': True, 'slaves_count': 2, 'slaves': [{}, {}]}
    no_dxl = {'available': False, 'complete': False, 'devices_count': 0, 'devices': []}
    no_ft = {'available': False, 'complete': False, 'devices_count': 0, 'devices': [], 'scan_rule': 'x'}
    old_shape = {'ethercat_scan': ethercat, 'dynamixel_scan': no_dxl}
    new_shape = {**old_shape, 'feetech_scan': no_ft}
    for scan in (old_shape, new_shape):
        assert motor_config_rules.scan_operation_outcome(
            scan, operation_type='full_scan', fallback_success=False, dynamixel_expected=False,
        ) == 'success'
    # 문구도 전과 같다 (Feetech 0대는 안 붙는다)
    assert motor_config_rules.scan_result_message(True, old_shape, '') == motor_config_rules.scan_result_message(
        True, new_shape, '')
    # Feetech 를 쓰는 프로젝트면 못 찾은 것은 부분 완료
    assert motor_config_rules.scan_operation_outcome(
        new_shape, operation_type='full_scan', fallback_success=False,
        dynamixel_expected=False, feetech_expected=True,
    ) == 'partial'


def test_serial_scan_outcome_judges_only_the_kinds_in_use():
    """직렬 서보 검색(다이나믹셀 + Feetech 한 번에) · 안 쓰고 못 찾은 종류는 판정에서 뺀다 · 수정 목록 158"""
    none = {'available': False, 'complete': False, 'devices_count': 0, 'devices': []}
    dxl = {'available': True, 'complete': True, 'devices_count': 1, 'devices': [{'id': 3}]}
    ft = {'available': True, 'complete': True, 'devices_count': 1, 'devices': [{'id': 1}]}
    skipped = {'skipped': True}

    def outcome(dynamixel, feetech, **expected):
        scan = {'ethercat_scan': skipped, 'dynamixel_scan': dynamixel, 'feetech_scan': feetech}
        return motor_config_rules.scan_operation_outcome(
            scan, operation_type='dynamixel_scan', fallback_success=False, **expected)

    # 다이나믹셀만 쓰는 PC · Feetech 응답 없음은 상관없음 (전과 같음)
    assert outcome(dxl, none, dynamixel_expected=True, feetech_expected=False) == 'success'
    assert outcome(none, none, dynamixel_expected=True, feetech_expected=False) == 'failure'
    # Feetech 만 쓰는 PC
    assert outcome(none, ft, dynamixel_expected=False, feetech_expected=True) == 'success'
    # 둘 다 쓰는데 하나만 찾음 → 일부
    assert outcome(dxl, none, dynamixel_expected=True, feetech_expected=True) == 'partial'
    assert outcome(dxl, ft, dynamixel_expected=True, feetech_expected=True) == 'success'
    # 아직 모터 설정 없음 · 찾은 쪽만으로
    assert outcome(none, ft, dynamixel_expected=False, feetech_expected=False) == 'success'
    assert outcome(none, none, dynamixel_expected=False, feetech_expected=False) == 'failure'
    # 옛 노드(Feetech 구획 없음) · 전과 같음
    assert motor_config_rules.scan_operation_outcome(
        {'dynamixel_scan': dxl}, operation_type='dynamixel_scan', fallback_success=False) == 'success'

    # 문구 · 직렬 서보 검색이면 두 종류 수를 다 보여 준다 · 다이나믹셀 포트 없음 안내는 Feetech 를 찾았으면 안 붙인다
    message = motor_config_rules.scan_result_message(
        True, {'ethercat_scan': skipped, 'dynamixel_scan': none, 'feetech_scan': ft}, '')
    assert '다이나믹셀 0대' in message and 'Feetech 1대' in message
    assert '직렬 포트 없음' not in message
    assert 'Feetech 0대' in motor_config_rules.scan_result_message(
        True, {'ethercat_scan': skipped, 'dynamixel_scan': dxl, 'feetech_scan': none}, '')


def test_monitoring_refs_are_unchanged_for_old_motors_and_new_for_feetech():
    old = {'motor_type': 'dynamixel', 'bus_id': 3, 'serial_port': '/dev/ttyUSB0'}
    assert bridge_helpers._monitoring_motor_refs(old) == ['dynamixel:port:%2Fdev%2FttyUSB0:id:3', 'dynamixel:id:3']
    ac = {'motor_type': 'minas', 'alias': 103, 'ethercat_master_index': 0}
    assert bridge_helpers._monitoring_motor_refs(ac) == ['ac_servo:master:0:alias:103', 'ac_servo:alias:103']
    ft = {'motor_type': 'feetech', 'bus_id': 1, 'serial_port': '/dev/ttyUSB1'}
    assert bridge_helpers._monitoring_motor_refs(ft) == ['feetech:port:%2Fdev%2FttyUSB1:id:1']


def test_param_files_point_at_real_control_tables_from_any_workspace(tmp_path):
    # 따로 둔 작업 폴더(제어표 없음)에서도 설치된 저장소의 제어표를 가리킨다 · 빈 model_file 은
    # motor_manager 시작을 멈춘다(가짜 서보 시험에서 잡음 · 2026-10-21)
    workspace = tmp_path / 'workspace'
    (workspace / 'config').mkdir(parents=True)
    for kind, model, number in (('dynamixel', 'XM540-W270-R', 1120), ('feetech', 'STS3215', 777)):
        document, _info = serial_params.build_document(workspace, kind, model, number)
        assert Path(document['model_file']).is_file(), (kind, document['model_file'])


def test_missing_control_table_refuses_the_save(monkeypatch):
    real = serial_params.model_info

    def without_table(*args, **kwargs):
        info = dict(real(*args, **kwargs))
        info['model_file'] = '/nonexistent/sts.model'
        return info

    monkeypatch.setattr(serial_params, 'model_info', without_table)
    with pytest.raises(ValueError, match='제어표'):
        serial_params.build_document(WORKSPACE, 'feetech', 'STS3215', 777)
