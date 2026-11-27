"""하트비트는 실행기와 따로 · 끊김 시험 N (2026-11-08)"""

import threading
import time
from pathlib import Path

from motion_coordination.heartbeat_pump import HeartbeatPump


def test_heartbeats_keep_going_while_the_executor_waits_four_seconds_on_the_local_web():
    sent = []
    pump = HeartbeatPump(0.05, lambda: sent.append(time.monotonic()), lambda _text: None)
    executor_busy = threading.Event()

    def slow_local_call():                     # 실행기 · 4 s 늦게 답하는 가짜 로컬 호출(시험은 0.6 s)
        executor_busy.set()
        time.sleep(0.6)

    pump.start()
    try:
        worker = threading.Thread(target=slow_local_call)
        worker.start()
        executor_busy.wait(1.0)
        before = len(sent)
        worker.join()
        during = len(sent) - before
    finally:
        pump.close()

    assert during >= 8, f'실행기가 막힌 0.6 s 동안 하트비트 {during}번'
    gaps = [b - a for a, b in zip(sent, sent[1:])]
    assert max(gaps) < 0.3


def test_one_failure_does_not_stop_the_heartbeats():
    calls = []
    warned = []

    def tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('publisher gone')

    pump = HeartbeatPump(0.02, tick, warned.append)
    pump.start()
    time.sleep(0.2)
    pump.close()

    assert len(calls) >= 3
    assert warned and 'publisher gone' in warned[0]


def test_the_node_no_longer_sends_heartbeats_from_an_executor_timer():
    source = (Path(__file__).resolve().parents[1] / 'motion_coordination' / 'coordination_node.py').read_text(
        encoding='utf-8',
    )
    assert 'create_timer(\n            self._config.heartbeat_sec, self._heartbeat_tick' not in source
    assert 'HeartbeatPump(' in source
