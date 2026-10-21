"""직렬 서보 상태 · Feetech 오류 글 · 설정 대기(0xFFFE) · AC 축 모양은 그대로 · 수정 목록 158"""

from types import SimpleNamespace

from motion_state_monitor.connection_state import build_scan_connection_rows
from motion_state_monitor.monitor_node import MotionStateMonitor
from motion_state_monitor.motor_values import feetech_error_text, normalized_errorcode
from motion_state_monitor.state_publisher import StatePublisher


def _motor(motor_type, errorcode, statusword=0x01):
    monitor = object.__new__(MotionStateMonitor)
    monitor._motor_metadata = {1: {'motor_type': motor_type}}
    state = StatePublisher(monitor)
    state._metadata_for = lambda _axis: {'motor_type': motor_type}
    message = SimpleNamespace(
        statusword=[statusword], position=[0.0], velocity=[0.0], effort=[12.0],
        errorcode=[errorcode], controlword=[1],
    )
    return state._motor_from_status(message, 0, 1, 10.0)


def test_feetech_uses_the_serial_servo_path_and_its_own_error_text():
    motor = _motor('feetech', 0x24)
    assert motor['servo_on'] is True and motor['fault'] is True
    assert motor['current'] == 12.0 and motor['torque'] is None
    assert 'Overheating' in motor['error_text'] and 'Overload' in motor['error_text']
    assert '실물 미검증' in motor['error_text']
    assert motor['config_pending'] is False
    assert feetech_error_text(0) == 'No error'


def test_config_pending_code_is_shown_for_serial_servos():
    motor = _motor('feetech', 0xFFFE)
    assert motor['config_pending'] is True and '설정 대기' in motor['error_text']
    assert motor['state'] == 'detected'
    lost = _motor('feetech', 0xFFFF)
    assert lost['state'] == 'disconnected' and lost['error_text'] == 'Communication unavailable'


def test_ac_servo_axis_shape_is_unchanged():
    motor = _motor('minas', 0x0000, statusword=0x0027)
    assert 'config_pending' not in motor
    assert motor['torque'] == 12.0 and motor['current'] is None
    # MINAS 0xFFxx 알람 정규화는 전과 같다 (0xFFFE 는 AC 에서 알람 0xFE)
    assert normalized_errorcode(0xFFFE, {'motor_type': 'minas'}) == 0xFE
    assert 'config_pending' not in _motor('minas', 0xFFFE, statusword=0x0008)


def test_feetech_rows_match_only_the_feetech_scan():
    feetech = {'controller_index': 2, 'motor_type': 'feetech', 'motor_type_label': 'Feetech',
               'transport': 'serial', 'bus_id': 3}
    dxl = {'controller_index': 1, 'motor_type': 'dynamixel', 'transport': 'serial', 'bus_id': 3}
    rows = build_scan_connection_rows(
        [feetech, dxl],
        {'skipped': True, 'slaves': []},
        {'available': True, 'devices': [{'id': 3}]},
        scan_ethercat=False,
        scan_dynamixel=True,
        feetech_scan={'available': True, 'devices': []},
        scan_feetech=True,
    )
    assert rows[0]['discovery_state'] == 'missing'     # 다이나믹셀 ID 3 과 짝짓지 않는다
    assert rows[1]['discovery_state'] == 'detected'
