"""연동 노드가 묻는 로컬 상태에 운전 모드를 싣는다 · 수정 목록 30-6 (2026-10-06)

마스터는 하트비트로 받은 모드를 보고 오프·수동 PC 를 그룹 시작에서 뺀다 ·
50ms 마다 불리므로 파일은 1초에 한 번만 읽는다.
"""

import threading

from motion_web_bridge import run_mode_gate
from motion_web_bridge.bridge_node import MotionWebBridge


def _bridge():
    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge._coordination_poll_lock = threading.Lock()
    bridge._motion_run_lock = threading.Lock()
    bridge._safety_status_lock = threading.Lock()
    bridge._motion_run_status = {}
    bridge._safety_status = {}
    return bridge


def test_local_status_carries_the_mode_and_reads_it_once_per_second(monkeypatch):
    reads = []
    monkeypatch.setattr(
        run_mode_gate, 'current_run_mode', lambda _bridge: reads.append(1) or 'off',
    )
    bridge = _bridge()

    first = bridge.coordination_local_status()
    second = bridge.coordination_local_status()

    assert first['operation_mode'] == 'off'
    assert second['operation_mode'] == 'off'
    assert len(reads) == 1


def test_unreadable_mode_is_empty_not_an_error(monkeypatch):
    def broken(_bridge):
        raise ValueError('schedule_store.json 깨짐')

    monkeypatch.setattr(run_mode_gate, 'current_run_mode', broken)

    assert _bridge().coordination_local_status()['operation_mode'] == ''
