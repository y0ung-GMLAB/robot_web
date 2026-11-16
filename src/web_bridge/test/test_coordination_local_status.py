import threading
import time

from motion_web_bridge.bridge_node import MotionWebBridge


def test_coordination_local_status_contains_only_runtime_and_safety_fields():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._safety_status_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = 0.0
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


def test_coordination_watchdog_stops_group_run_after_the_alive_signal_disappears():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = time.monotonic() - 3.0
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


def test_coordination_watchdog_waits_out_a_short_gap():
    """「살아 있음」 이 1.2초 밀린 것만으로 이 PC 혼자 서지 않는다 · 수정 목록 172 · 209"""
    from motion_web_bridge import bridge_node
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = time.monotonic() - 1.2
    bridge._coordination_watchdog_stop_execution_id = ''
    bridge._motion_run_status = {
        'group_execution': True,
        'execution_id': 'exec-a',
        'phase': 'running',
    }
    bridge.coordination_stop_now = lambda: (_ for _ in ()).throw(
        AssertionError('a short gap must not stop the run')
    )

    bridge._coordination_watchdog_callback()

    assert bridge._coordination_watchdog_stop_execution_id == ''
    assert bridge_node.COORDINATION_ALIVE_TIMEOUT_SEC > 1.5


def test_the_web_fields_poll_is_not_a_sign_of_life_but_the_alive_topic_is():
    """수정 목록 209 · 연동 노드는 웹을 0.5 s 마다(웹 쪽 칸만) 묻는다 · 웹이 바빠 그 질문이 밀려도 · 반대로 연동 노드가
    멈췄는데 다른 무엇이 웹을 물어도 · 그것으로 생사를 가르지 않는다 · 생사는 연동 노드가 로컬 DDS 로 낸 「살아 있음」"""
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._safety_status_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = 0.0
    bridge._motion_run_status = {}
    bridge._safety_status = {}
    bridge._operation_mode_cache = (time.monotonic(), 'manual')
    bridge._start_blocker_cache = (time.monotonic(), '')
    bridge._schedule_own_window_open = lambda: False
    bridge._schedule_own_window_ends_at = lambda: 0.0
    bridge._timetable_fields = lambda: {}

    bridge.coordination_local_status()
    assert bridge._coordination_alive_monotonic == 0.0

    bridge._coordination_alive_callback(None)
    assert time.monotonic() - bridge._coordination_alive_monotonic < 1.0


def test_the_poll_counts_as_alive_only_while_the_coordination_node_has_no_local_link(monkeypatch):
    """되돌리기 길(연동 노드가 로컬 연결을 못 엶 · `?link=down`) · 「살아 있음」 토픽을 낼 수 없다 · 그 질문을 살아 있음으로 ·
    안 그러면 웹 역감시가 그 PC 의 그룹 재생(시간표 회차 명령을 웹 길로 받은 것 포함)을 바로 세웠다 · 206 · 209 잇기"""
    from motion_web_bridge import bridge_node
    monkeypatch.setattr(bridge_node.process_alive, 'coordination_alive', lambda *_args, **_kwargs: True)
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._safety_status_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = 0.0
    bridge._coordination_watchdog_stop_execution_id = ''
    bridge._motion_run_status = {'group_execution': True, 'execution_id': 'tt-s1', 'phase': 'running'}
    bridge._safety_status = {}
    bridge._operation_mode_cache = (time.monotonic(), 'schedule')
    bridge._start_blocker_cache = (time.monotonic(), '')
    bridge._schedule_own_window_open = lambda: True
    bridge._schedule_own_window_ends_at = lambda: 0.0
    bridge._timetable_fields = lambda: {}
    bridge.coordination_stop_now = lambda: (_ for _ in ()).throw(
        AssertionError('되돌리기 길에서 묻고 있는 연동 노드는 살아 있다'),
    )

    bridge.coordination_local_status(link_down=True)
    bridge._coordination_watchdog_callback()

    assert bridge._coordination_watchdog_stop_execution_id == ''
    assert time.monotonic() - bridge._coordination_alive_monotonic < 1.0


def test_coordination_watchdog_does_not_affect_standalone_run():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = 0.0
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
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = 0.0
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


# --------------------------------------------------------------------------- #
# 끊김 시험 E (2026-11-08) · 연동 노드가 살아 있으면(잠깐 멈춤) 10 s 까지 기다린다 · 죽었으면 2 s
# --------------------------------------------------------------------------- #

def _watched_bridge(quiet_sec, *, alive, monkeypatch):
    from motion_web_bridge import bridge_node
    monkeypatch.setattr(bridge_node.process_alive, 'coordination_alive', lambda *_args, **_kwargs: alive)
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = time.monotonic() - quiet_sec
    bridge._coordination_watchdog_stop_execution_id = ''
    bridge._motion_run_status = {'group_execution': True, 'execution_id': 'exec-a', 'phase': 'running'}
    stopped = threading.Event()
    bridge.coordination_stop_now = lambda: stopped.set() or {'success': True}
    return bridge, stopped


def test_a_live_but_stalled_coordination_node_does_not_stop_the_run(monkeypatch):
    bridge, stopped = _watched_bridge(2.7, alive=True, monkeypatch=monkeypatch)

    bridge._coordination_watchdog_callback()

    assert not stopped.wait(0.2)
    assert bridge._coordination_watchdog_stop_execution_id == ''


def test_a_dead_coordination_node_still_stops_after_two_seconds(monkeypatch):
    bridge, stopped = _watched_bridge(2.1, alive=False, monkeypatch=monkeypatch)

    bridge._coordination_watchdog_callback()

    assert stopped.wait(0.5)


def test_a_live_coordination_node_silent_too_long_stops(monkeypatch):
    from motion_web_bridge import bridge_node
    bridge, stopped = _watched_bridge(
        bridge_node.COORDINATION_SLOW_TIMEOUT_SEC + 0.5, alive=True, monkeypatch=monkeypatch,
    )

    bridge._coordination_watchdog_callback()

    assert stopped.wait(0.5)
    assert bridge_node.COORDINATION_SLOW_TIMEOUT_SEC < 15.0, 'systemd 감시(WatchdogSec 15)보다 짧게'


def test_the_pid_file_tells_alive_from_dead(tmp_path):
    from motion_common import process_alive

    path = process_alive.coordination_pid_path(tmp_path)
    assert process_alive.coordination_alive(path) is False, '파일 없음 = 모름 = 죽음'
    assert process_alive.write_pid_file(path, 4321)
    proc = tmp_path / 'proc' / '4321'
    proc.mkdir(parents=True)
    (proc / 'cmdline').write_bytes(b'/usr/bin/python3\0/ws/install/motion_coordination/lib/motion_coordination_node\0')
    (proc / 'stat').write_text('4321 (motion_coordin) S 1 2 3', encoding='utf-8')
    assert process_alive.coordination_alive(path, proc_root=tmp_path / 'proc') is True
    (proc / 'stat').write_text('4321 (motion_coordin) Z 1 2 3', encoding='utf-8')
    assert process_alive.coordination_alive(path, proc_root=tmp_path / 'proc') is False, '좀비'
    (proc / 'stat').write_text('4321 (bash) S 1 2 3', encoding='utf-8')
    (proc / 'cmdline').write_bytes(b'bash\0')
    assert process_alive.coordination_alive(path, proc_root=tmp_path / 'proc') is False, 'PID 재사용'
