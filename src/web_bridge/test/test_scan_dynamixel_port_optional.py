"""다이나믹셀 포트가 없다는 것만으로 「검색 일부 완료」 가 뜨던 것 · 수정 목록 120 (바)

실물 2026-10-13 S-2 · 새 프로젝트 · AC 서보 3대 · 「전체 검색」 → 「검색 일부 완료 · …
Dynamixel 직렬 포트를 찾지 못했습니다」 · 이 프로젝트는 다이나믹셀을 안 쓰는데 실패처럼 읽혔다.

프로젝트 모터 설정에 다이나믹셀이 없으면(새 프로젝트 = 빈 설정 포함) 포트 없음은 판정에서 빼고
문구에 정보로만 남긴다 · 다이나믹셀을 쓰는 프로젝트는 그대로 「일부 완료」.
"""

from motion_web_bridge import motor_config_rules


def _scan():
    return {
        'scan_id': 's2',
        'ethercat_scan': {
            'available': True, 'complete': True, 'slaves_count': 3,
            'masters': [{'master_index': 0, 'complete': True, 'slaves_count': 3}],
            'slaves': [{'master_index': 0, 'slave_position': p, 'direct_read_complete': True} for p in range(3)],
        },
        'dynamixel_scan': {
            'available': False, 'complete': False, 'devices_count': 0, 'devices': [], 'targets': [],
            'error': 'Dynamixel 직렬 포트를 찾지 못했습니다. /dev/serial/by-id, /dev/ttyUSB*, /dev/ttyACM* 경로를 확인했습니다.',
        },
        'scan_errors': [{'transport': 'dynamixel', 'message': 'Dynamixel 직렬 포트를 찾지 못했습니다.'}],
    }


def test_no_dynamixel_in_project_port_missing_is_success_with_info():
    scan = _scan()
    outcome = motor_config_rules.scan_operation_outcome(
        scan, operation_type='full_scan', fallback_success=False, dynamixel_expected=False,
    )
    assert outcome == 'success'
    message = motor_config_rules.scan_result_message(True, scan, 'raw')
    assert message.startswith('모터 검색 완료')
    assert 'AC 서보 3대' in message
    assert '다이나믹셀 직렬 포트 없음(정보' in message
    assert '일부' not in message


def test_project_with_dynamixel_keeps_partial():
    scan = _scan()
    assert motor_config_rules.scan_operation_outcome(
        scan, operation_type='full_scan', fallback_success=False, dynamixel_expected=True,
    ) == 'partial'
    # 기본값은 옛 판정 그대로
    assert motor_config_rules.scan_operation_outcome(
        scan, operation_type='full_scan', fallback_success=False,
    ) == 'partial'
    message = motor_config_rules.scan_result_message(False, scan, 'raw')
    assert message.startswith('모터 검색 일부 완료')
    assert '포트 없음(정보' not in message


def test_port_present_but_nothing_answers_is_not_excused():
    """포트가 있는데 응답이 없는 것은 다른 일이다 · 그대로 둔다"""
    scan = _scan()
    scan['dynamixel_scan'] = {'available': True, 'complete': False, 'devices_count': 0, 'devices': [], 'error': 'ping 응답 없음'}
    assert motor_config_rules.scan_operation_outcome(
        scan, operation_type='full_scan', fallback_success=False, dynamixel_expected=False,
    ) == 'partial'


def test_ethercat_failure_still_fails_without_dynamixel():
    scan = _scan()
    scan['ethercat_scan'] = {'available': True, 'complete': False, 'slaves_count': 0, 'slaves': [], 'error': '응답한 Slave 없음'}
    assert motor_config_rules.scan_operation_outcome(
        scan, operation_type='full_scan', fallback_success=False, dynamixel_expected=False,
    ) == 'failure'


def test_registry_uses_dynamixel():
    assert motor_config_rules.registry_uses_dynamixel({'motors': []}) is False
    assert motor_config_rules.registry_uses_dynamixel({}) is False
    assert motor_config_rules.registry_uses_dynamixel({'motors': [{'motor_type': 'ac_servo'}]}) is False
    assert motor_config_rules.registry_uses_dynamixel({'motors': [{'motor_type': 'Dynamixel'}]}) is True
    assert motor_config_rules.registry_uses_dynamixel({'motors': [{'motor_type': 'dynamixel', 'deleted': True}]}) is False


def test_orchestrator_passes_project_dynamixel_use():
    """판정에 프로젝트 모터 설정을 넘긴다 · rclpy 없는 곳에서도 읽히게 소스로 본다"""
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'motion_web_bridge' / 'scan_orchestrator.py').read_text(encoding='utf-8')
    assert 'dynamixel_expected=self._project_uses_dynamixel()' in source
    assert 'motor_config_rules.registry_uses_dynamixel(registry)' in source
