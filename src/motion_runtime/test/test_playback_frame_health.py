"""재생 프레임 버림·지연 · 수정 목록 12 (2026-10-06)

12-1 supervisor 가 프레임을 통째로 버리면 0.5초 안에 재생을 멈추고 오류로 남긴다
12-2 마감 초과를 회차 기록에 남긴다
12-3 밀린 프레임을 몰아 쏘지 않고 건너뛴다
"""

import threading

import pytest

from motion_runtime import motion_run_rules
from motion_runtime.motion_run_rules import PlaybackTiming


def test_on_time_frames_wait_for_the_next_deadline():
    timing = PlaybackTiming(0.02)
    index, deadline = timing.next_index(0, cycle_started=100.0, now=100.005)
    assert (index, deadline) == (1, pytest.approx(100.02))
    timing.note(0.005)
    assert timing.as_dict() == {'late_count': 0, 'max_late_ms': 5.0, 'skipped_samples': 0}


def test_a_long_stall_skips_to_the_current_frame_instead_of_bursting():
    timing = PlaybackTiming(0.02)
    # 0번을 보낸 뒤 0.1초 멈췄다 · 1~4번은 이미 지났다
    index, deadline = timing.next_index(0, cycle_started=100.0, now=100.1)
    assert deadline is None
    assert index == 5
    timing.note(0.1)
    assert timing.as_dict() == {'late_count': 1, 'max_late_ms': 100.0, 'skipped_samples': 4}


def test_one_tick_late_is_sent_without_skipping():
    timing = PlaybackTiming(0.02)
    index, deadline = timing.next_index(3, cycle_started=100.0, now=100.09)
    assert index == 4 and deadline is not None


@pytest.mark.parametrize('status, started, expected', [
    ({'stamp': 50.0, 'motion_run_drop': {'continuous_sec': 0.8, 'reason': '2등급 서보 에러'}}, 40.0, '2등급 서보 에러'),
    ({'stamp': 50.0, 'motion_run_drop': {'continuous_sec': 0.3, 'reason': 'x'}}, 40.0, ''),
    # 재생 시작보다 오래된 상태 · 지난 재생의 기록이다
    ({'stamp': 30.0, 'motion_run_drop': {'continuous_sec': 5.0, 'reason': 'x'}}, 40.0, ''),
    ({}, 40.0, ''),
    (None, 40.0, ''),
])
def test_supervisor_drop_stops_playback_only_when_fresh_and_long(status, started, expected):
    error = motion_run_rules._supervisor_drop_error(status, started)
    if expected:
        assert expected in error and '멈춥니다' in error
    else:
        assert error == ''


def test_player_raises_on_a_fresh_drop_report():
    from motion_runtime.motion_player import MotionPlayer

    manager = type('M', (), {})()
    manager._safety_status_lock = threading.Lock()
    manager._latest_safety_status = {
        'stamp': 9e9, 'motion_run_drop': {'continuous_sec': 1.0, 'reason': '긴급정지 잠김'},
    }
    player = MotionPlayer(manager)

    error = motion_run_rules._supervisor_drop_error(player._latest_safety_status(), 1.0)

    assert '긴급정지 잠김' in error
