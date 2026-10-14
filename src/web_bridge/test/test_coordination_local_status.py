import threading
import time

from motion_web_bridge.bridge_node import MotionWebBridge


def test_coordination_local_status_contains_only_runtime_and_safety_fields():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._safety_status_lock = threading.Lock()
    bridge._coordination_poll_lock = threading.Lock()
    bridge._coordination_poll_received_monotonic = 0.0
    bridge._coordination_watchdog_stop_execution_id = ''
    bridge._motion_run_status = {
        'group_execution': True, 'execution_id': 'exec-a', 'phase': 'running',
    }
    bridge._safety_status = {'servo_alarm_grade': 0}

    result = bridge.coordination_local_status()

    assert result['bridge_state'] == 'ok'
    assert result['motion_run_status']['execution_id'] == 'exec-a'
    assert result['safety_status']['servo_alarm_grade'] == 0
    assert 'motion_state' not in result
    assert 'execution_context' not in result


def test_coordination_watchdog_stops_group_run_after_local_poll_disappears():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._coordination_poll_lock = threading.Lock()
    bridge._coordination_poll_received_monotonic = time.monotonic() - 2.0
    bridge._coordination_watchdog_stop_execution_id = ''
    bridge._motion_run_status = {
        'group_execution': True,
        'execution_id': 'exec-a',
        'phase': 'running',
    }
    stopped = threading.Event()
    bridge.coordination_stop_now = lambda: stopped.set() or {'success': True}

    bridge._coordination_watchdog_callback()

    assert stopped.wait(0.5)
    assert bridge._coordination_watchdog_stop_execution_id == 'exec-a'


def test_coordination_watchdog_does_not_affect_standalone_run():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._coordination_poll_lock = threading.Lock()
    bridge._coordination_poll_received_monotonic = 0.0
    bridge._coordination_watchdog_stop_execution_id = ''
    bridge._motion_run_status = {
        'group_execution': False,
        'execution_id': '',
        'phase': 'running',
    }
    bridge.coordination_stop_now = lambda: (_ for _ in ()).throw(
        AssertionError('standalone run must not be stopped')
    )

    bridge._coordination_watchdog_callback()


def test_coordination_stop_publishes_safety_before_motion_run_stop():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    events = []
    bridge.publish_safety_stop = (
        lambda emergency: events.append(('safety', emergency)) or 'safety-a'
    )
    bridge.motion_run_stop = (
        lambda: events.append('motion_run_stop') or {'success': True}
    )

    result = bridge.coordination_stop_now()

    assert events == [('safety', False), 'motion_run_stop']
    assert result['success'] is True
    assert result['safety_stop']['request_id'] == 'safety-a'
    assert result['safety_stop']['acknowledgement_pending'] is True


def test_coordination_stop_still_stops_motion_when_safety_publish_fails():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    events = []
    bridge.publish_safety_stop = lambda _emergency: (_ for _ in ()).throw(
        RuntimeError('publisher unavailable')
    )
    bridge.motion_run_stop = (
        lambda: events.append('motion_run_stop') or {'success': True}
    )

    result = bridge.coordination_stop_now()

    assert events == ['motion_run_stop']
    assert result['success'] is False
    assert result['safety_stop']['success'] is False


def _status_bridge(*, terminal='', runtime=''):
    from types import SimpleNamespace

    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._safety_status_lock = threading.Lock()
    bridge._coordination_poll_lock = threading.Lock()
    bridge._coordination_poll_received_monotonic = 0.0
    bridge._motion_run_status = {}
    bridge._safety_status = {}
    bridge._operation_mode_cache = (time.monotonic(), 'manual')
    calls = []
    bridge._execution_context = SimpleNamespace(
        terminal_block_reason=lambda: calls.append('context') or terminal,
    )
    bridge.motor_runtime_control_blocker = lambda: calls.append('motor') or runtime
    return bridge, calls


def test_local_status_says_why_this_pc_cannot_start_a_group():
    """수정 목록 136 ⑤ · floating1~3 (모터 설정 없음) · 하트비트로 마스터에게 · 선택 때 미리 뺀다"""
    bridge, _calls = _status_bridge(terminal='모터 설정과 조인트 매핑을 저장해 확정하세요')

    result = bridge.coordination_local_status()

    assert result['start_blocker'] == '실행 준비 안 됨 · 모터 설정과 조인트 매핑을 저장해 확정하세요'


def test_local_status_names_a_motor_problem_when_the_settings_are_fine():
    bridge, _calls = _status_bridge(runtime='연결되지 않은 모터가 있습니다: 2')

    assert bridge.coordination_local_status()['start_blocker'] == '실행 준비 안 됨 · 연결되지 않은 모터가 있습니다: 2'


def test_local_status_start_blocker_is_empty_when_ready_and_read_once_a_second():
    """50 ms 마다 불린다 · 1초에 한 번만 본다"""
    bridge, calls = _status_bridge()

    for _ in range(5):
        assert bridge.coordination_local_status()['start_blocker'] == ''

    assert calls == ['context', 'motor']
