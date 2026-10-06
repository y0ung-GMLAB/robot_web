"""통신이 끊긴 축이 있으면 재생을 멈춘다 · 수정 목록 3-1 (2026-10-06)

전에는 모터 상태 메시지가 도착만 하면 계속 보냈다 · 랜선이 빠진 축에도 목표를
보내며 재생이 끝까지 정상으로 기록됐다.
"""

import threading

import pytest

from motion_runtime import motion_run_rules
from motion_runtime.motion_player import MotionPlayer


def _motor(axis, state='detected'):
    return {'controller_index': axis, 'state': state}


@pytest.mark.parametrize('state, text', [
    ('disconnected', '응답 없음'),
    ('ethercat_down', 'EtherCAT 끊김'),
])
def test_lost_axes_are_named(state, text):
    error = motion_run_rules._communication_lost_error(
        [0, 1], [_motor(0), _motor(1, state)],
    )
    assert '1번 모터' in error and text in error
    assert '0번' not in error


def test_healthy_or_unrelated_axes_pass():
    motors = [_motor(0), _motor(1), _motor(4, 'ethercat_down')]
    # 4번은 이 재생의 축이 아니다 · 다른 PC·다른 재생의 일
    assert motion_run_rules._communication_lost_error([0, 1], motors) == ''
    assert motion_run_rules._communication_lost_error([], motors) == ''


def test_axis_missing_from_motor_state_counts_as_lost():
    assert '모터 상태에 없음' in motion_run_rules._communication_lost_error([2], [_motor(0)])


class _Manager:
    def __init__(self, motors):
        self.motors = motors
        self._run_lock = threading.RLock()

    def _playback_ownership_error(self, axes=None):
        return ''

    def _current_motors(self):
        return self.motors


def test_player_guard_raises_during_playback_and_initial_move():
    manager = _Manager([_motor(0), _motor(1, 'disconnected')])
    player = MotionPlayer(manager)

    with pytest.raises(RuntimeError, match='통신이 끊긴 모터'):
        player._require_playback_command_allowed([{'motor_axis': 0}, {'motor_axis': 1}])

    manager.motors = [_motor(0), _motor(1)]
    player._require_playback_command_allowed([{'motor_axis': 0}, {'motor_axis': 1}])
    # 축을 주지 않으면(전체 소유권 확인만) 통신은 보지 않는다
    manager.motors = []
    player._require_playback_command_allowed(None)
