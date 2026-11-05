"""준비 검사 단계별 시간 · 느리거나 실패면 로그 한 줄 · 답에 `timing_ms` · 수정 목록 174

NY 실물 2026-11-05(humble) · 재부팅 뒤 첫 그룹 시작에서 「준비 거절 · 로컬 Web Bridge 응답 없음: timed out」 ·
어느 단계(파일 읽기 · 재샘플 · 속도 검사)가 느렸는지 기록이 없었다. jazzy 는 계획 캐시(164 · 170 · 171)가
아직 없어 미리 짓기는 옮기지 않고 시간 기록만 옮긴다.
"""

import threading
from unittest import mock

import pytest

from motion_runtime import motion_run_rules
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.plan_builder import PlanBuilder


@pytest.fixture(autouse=True)
def _patched_rules():
    mock.patch.object(motion_run_rules, '_target_range_limit_error', lambda _m, _l, _h: '').start()
    mock.patch.object(motion_run_rules, '_motor_type', lambda _motor: 'ac_servo').start()
    mock.patch.object(
        motion_run_rules, '_motors_for_ref',
        lambda ref, motors: [m for m in motors if m.get('motor_ref') == ref],
    ).start()
    yield
    mock.patch.stopall()


def _manager(alarm=False):
    mapping = {
        'motion_file_id': 'a.json',
        'mappings': [{
            'motion_id': '1-1', 'enabled': True, 'motor_ref': 'ac:0',
            'reference_enabled': True, 'reference_position_deg': 0.0,
            'motion_lower_deg': -180.0, 'motion_upper_deg': 180.0, 'range_confirmed': True,
            'initial_mode': 'first_frame', 'initial_move_time_sec': 5.0,
            'invert': False, 'offset_deg': 0.0, 'scale': 1.0, 'gear_ratio': 1.0,
        }],
    }
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager._run_lock = threading.RLock()
    manager.period_sec = 0.02
    manager._mapping_file_path = lambda _file_id: None
    manager._load_mapping = lambda _path: mapping
    manager._motion_file_path = lambda _file_id: 'a.json'
    manager._current_motors = lambda: [
        {'axis': 0, 'controller_index': 0, 'motor_ref': 'ac:0', 'alarm': alarm},
    ]
    manager._motor_for_axis = lambda axis, motors: motors[0]
    manager._multiturn_clear_state = lambda: {}
    manager._load_motion_records = lambda _path: [
        {'motion_id': '1-1', 'time_sec': round(0.02 * frame, 4), 'value': 0.0}
        for frame in range(1, 200)
    ]
    manager._status = motion_run_rules._empty_status()
    manager._set_status = lambda status: setattr(manager, '_status', status)
    manager.status = lambda: dict(manager._status)
    manager.logger = mock.Mock()
    manager.get_logger = lambda: manager.logger
    mock.patch.object(
        motion_run_rules, '_motor_ready_error',
        lambda motor: '알람 상태' if motor.get('alarm') else '',
    ).start()
    return manager


def _payload():
    return {
        'motion_file_id': 'a.json', 'mapping_file_id': 'map.yaml', 'run_mode': 'once',
        'request_source': 'network_readiness', 'initial_move_time_sec': None,
    }


def test_a_slow_check_logs_one_line_with_each_stage():
    manager = _manager()
    manager.CHECK_SLOW_LOG_MS = 0.0

    response = manager._handle_check(_payload())

    assert response['success'] is True
    assert {'records_ms', 'samples_ms', 'build_ms'} <= set(response['timing_ms'])
    (line,), _ = manager.logger.info.call_args
    assert line.startswith('[준비 검사 시간] a.json · network_readiness · 파일 ')
    assert ' · 재샘플 ' in line and ' · 계획 ' in line and line.endswith(' ms')


def test_a_fast_check_logs_nothing():
    manager = _manager()
    assert manager._handle_check(_payload())['success'] is True
    manager.logger.info.assert_not_called()
    manager.logger.warning.assert_not_called()


def test_a_failed_check_logs_how_far_it_got():
    manager = _manager(alarm=True)

    response = manager._handle_check(_payload())

    assert response['success'] is False and '알람 상태' in response['message']
    assert 'records_ms' in response['timing_ms'] and 'samples_ms' not in response['timing_ms']
    (line,), _ = manager.logger.warning.call_args
    assert line.startswith('[준비 검사 시간] a.json') and '실패: ' in line
