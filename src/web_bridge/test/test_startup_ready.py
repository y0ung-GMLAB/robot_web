"""웹 서비스 「준비 끝」 · supervisor · 재생 관리자 첫 상태 · 시간 짐작 대신 · 수정 목록 202

전에는 연동 노드가 기동 뒤 90 s · 웹 다시 시작 뒤 120 s · supervisor 감시가 20 s 를 시간으로 짐작했다 ·
느린 PC(NY floating4 · RAM 4.7 GB · 스왑)는 그 시간을 넘겨 정상 기동이 고장으로 읽혔다.
"""

import json
import threading
from types import SimpleNamespace

from motion_web_bridge import startup_ready
from motion_web_bridge.bridge_node import MotionWebBridge
from motion_web_bridge.startup_ready import StartupReadiness


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_ready_only_after_both_first_statuses():
    clock = _Clock()
    startup = StartupReadiness(monotonic=clock)
    assert startup.ready is False
    assert startup.blocker() == '프로그램 시작 중입니다 (대기: supervisor, 재생 관리자)'
    clock.now += 40.0
    startup.mark('supervisor')
    assert startup.ready is False
    assert startup.blocker() == '프로그램 시작 중입니다 (대기: 재생 관리자)'
    clock.now += 80.0                                   # 느린 PC · 기동 120 s
    startup.mark('motion_run_manager')
    assert startup.ready is True and startup.blocker() == ''
    status = startup.status()
    assert status['ready'] is True and status['ready_after_sec'] == 120.0
    assert status['overdue'] is False and status['message'] == ''


def test_never_ready_is_a_notice_only_after_the_long_limit():
    clock = _Clock()
    startup = StartupReadiness(monotonic=clock)
    startup.mark('supervisor')
    clock.now += startup_ready.STARTUP_NOTICE_SEC - 1.0
    assert startup.status()['overdue'] is False
    clock.now += 2.0
    status = startup.status()
    assert status['overdue'] is True and status['waiting'] == ['재생 관리자']
    assert status['message'] == '재생 관리자 상태를 5분간 수신하지 못했습니다. 프로그램을 재시작하세요.'


def _bridge():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._motion_run_lock = threading.Lock()
    bridge._safety_status_lock = threading.Lock()
    bridge._coordination_alive_lock = threading.Lock()
    bridge._coordination_alive_monotonic = 0.0
    bridge._motion_run_status = {}
    bridge._safety_status = {}
    bridge._bridge_instance_id = '4242-1'
    bridge._startup = StartupReadiness()
    # 프로젝트가 안 맞는 재생 상태도 「재생 관리자가 떴다」 는 맞다
    bridge._project = SimpleNamespace(payload_matches_selected=lambda _payload: False)
    bridge._motor_event_log = SimpleNamespace(record_motion_run_transition=lambda _payload: None)
    bridge.motion_run_status_topic = 'motion_run/status'
    bridge.safety_status_topic = 'safety/status'
    return bridge


def test_local_status_carries_ready_and_the_instance_id():
    """연동 노드가 묻는 칸 · 준비 전 `ready` False · supervisor · 재생 관리자 상태가 오면 True"""
    bridge = _bridge()

    before = bridge.coordination_local_status()
    assert before['ready'] is False
    assert before['bridge_instance_id'] == '4242-1'

    bridge._safety_status_callback(SimpleNamespace(data=json.dumps({'servo_alarm_grade': 0})))
    assert bridge.coordination_local_status()['ready'] is False
    bridge._motion_run_status_callback(SimpleNamespace(data=json.dumps({'state': 'idle'})))

    after = bridge.coordination_local_status()
    assert after['ready'] is True and after['bridge_instance_id'] == '4242-1'


def test_starts_and_manual_moves_wait_while_the_program_starts():
    """준비 전 · 시작 · 조그 · 하트비트 `start_blocker` 가 「시작 중」 · 진행 PC 는 그룹 시작 때 이 PC 만 뺀다"""
    bridge = _bridge()
    bridge.supervisor_watchdog = SimpleNamespace(unresponsive_reason=lambda: '')
    assert bridge.motor_runtime_control_blocker().startswith('프로그램 시작 중입니다')

    bridge._startup.mark('supervisor')
    bridge._startup.mark('motion_run_manager')
    assert bridge.motor_runtime_control_blocker() == '모터 상태를 아직 수신하지 못했습니다'


def test_a_group_prepare_is_refused_with_the_reason_while_starting():
    """준비 검사 · 재생 관리자 응답 시간 초과를 기다리지 않고 「시작 중」 으로 바로 거절 · 진행 PC 가 이 PC 만 뺀다"""
    from motion_web_bridge.coordination_bridge import _local_motion_readiness

    bridge = _bridge()
    bridge._startup.mark('supervisor')
    result = _local_motion_readiness(bridge, {}, 6.0, {})
    assert result == {'success': False, 'message': '프로그램 시작 중입니다 (대기: 재생 관리자)'}


def test_a_supervisor_fault_text_wins_over_starting():
    bridge = _bridge()
    bridge.supervisor_watchdog = SimpleNamespace(
        unresponsive_reason=lambda: 'supervisor 시작 안 됨 · 301초 동안 상태를 한 번도 받지 못함',
    )
    assert bridge.motor_runtime_control_blocker().startswith('supervisor 시작 안 됨')
