"""supervisor 가 재생 프레임을 통째로 버린 기록 · 수정 목록 12-1 (2026-10-06)"""

import time
from types import SimpleNamespace

from motion_supervisor.supervisor_node import MotionSupervisor


def _supervisor():
    supervisor = MotionSupervisor.__new__(MotionSupervisor)
    supervisor.get_logger = lambda: SimpleNamespace(
        error=lambda *_a, **_k: None, warning=lambda *_a, **_k: None,
    )
    return supervisor


def test_continuous_drops_are_reported_with_reason_and_duration():
    supervisor = _supervisor()
    supervisor._note_motion_run_drop('2등급 서보 에러')
    supervisor._motion_run_drop_since -= 0.6          # 0.6초째 버리는 중

    snapshot = supervisor._motion_run_drop_snapshot()

    assert snapshot['count'] == 1
    assert snapshot['reason'] == '2등급 서보 에러'
    assert snapshot['continuous_sec'] >= 0.6


def test_old_drops_do_not_count_as_dropping_now():
    supervisor = _supervisor()
    supervisor._note_motion_run_drop('x')
    supervisor._motion_run_drop_last_at = time.monotonic() - 1.0   # 마지막 버림이 1초 전

    assert supervisor._motion_run_drop_snapshot()['continuous_sec'] == 0.0


def test_malformed_command_counts_as_a_drop():
    supervisor = _supervisor()
    supervisor._motor_command_shape_error = lambda _msg: 'short'

    supervisor._motion_run_command_callback(object())

    assert supervisor._motion_run_drop_snapshot()['count'] == 1
    assert '형식 오류' in supervisor._motion_run_drop_reason
