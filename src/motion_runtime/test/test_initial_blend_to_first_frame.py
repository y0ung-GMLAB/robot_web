"""초기 위치 → 첫 프레임 블렌딩 · 수정 목록 13-1 (2026-10-06)

`reference`·`manual` 은 초기 위치와 첫 프레임이 다를 수 있다 · 전에는 재생 첫 틱
(20 ms)에 그 차이를 한 번에 뛰었다.
"""

import threading

from motion_runtime import motion_run_rules
from motion_runtime.motion_player import MotionPlayer


def _axis(axis, initial, first, motion_first):
    return {
        'motion_id': f'j{axis}', 'motor_axis': axis, 'motor_type': 'ac_servo',
        'initial_motor_target_rad': initial, 'first_frame_motor_target_rad': first,
        'initial_motion_position_rad': 0.0, 'loop_start_motion_rad': motion_first,
        'initial_move_time_sec': 5.0,
    }


class _Manager:
    period_sec = 0.02

    def __init__(self):
        self._stop_event = threading.Event()
        self._run_lock = threading.RLock()
        self.statuses = []
        self.status_value = {}

    def status(self):
        return dict(self.status_value)

    def _set_status(self, status):
        self.status_value = dict(status)
        self.statuses.append(status.get('message'))

    def _update_status(self, values):
        self.status_value.update(values)
        self.statuses.append(values.get('message'))

    def _current_lifecycle(self):
        return {}

    def _motor_for_axis(self, axis, motors):
        return {'controller_index': axis, 'state': 'detected', 'servo_on': True, 'position_deg': 0.0}

    def get_logger(self):
        return type('L', (), {'error': lambda *_a: None})()


def _player(manager, streams, published):
    player = MotionPlayer(manager)
    player._wait_for_current_motors = lambda: [{'controller_index': 0}, {'controller_index': 1}]
    player._run_initial_position_stream = lambda motors, axes, starts, targets, durations, longest: streams.append(
        (dict(starts), dict(targets))
    )
    player._wait_for_targets = lambda axes, targets, timeout: (True, 'ok')
    player._publish_motion_values = published.update
    player._target_tolerance = lambda _axis: 0.05
    player._target_settle_timeout_sec = lambda: 1.0
    return player


def _plan(blend):
    plan = {
        'axes': [_axis(0, 0.0, 600.0, 4.0), _axis(1, 10.0, 10.0, 0.0)],
        'summary': {}, 'warnings': [], 'capabilities': {},
    }
    if blend:
        plan['blend_to_first_frame'] = True
    return plan


def _patch(monkeypatch):
    monkeypatch.setattr(motion_run_rules, '_motor_ready_error', lambda _motor: '')
    monkeypatch.setattr(motion_run_rules, '_motor_position', lambda _motor: 0.0)
    monkeypatch.setattr(motion_run_rules, '_status_from_plan', lambda state, message, _plan: {
        'state': state, 'message': message,
    })


def test_motion_preceding_initial_move_continues_to_the_first_frame(monkeypatch):
    _patch(monkeypatch)
    manager, streams, published = _Manager(), [], {}
    player = _player(manager, streams, published)

    player._run_initialization(_plan(blend=True))

    assert len(streams) == 2
    assert streams[0][1] == {0: 0.0, 1: 10.0}               # 초기 위치
    assert streams[1] == ({0: 0.0, 1: 10.0}, {0: 600.0, 1: 10.0})   # 다른 축만 첫 프레임으로
    assert '초기 위치 → 첫 프레임으로 잇는 중' in manager.statuses
    assert published == {'j0': 4.0, 'j1': 0.0}
    assert manager.status()['state'] == 'initialized'


def test_initial_move_alone_stops_at_the_initial_pose(monkeypatch):
    _patch(monkeypatch)
    manager, streams, published = _Manager(), [], {}

    _player(manager, streams, published)._run_initialization(_plan(blend=False))

    assert len(streams) == 1
    assert published == {'j0': 0.0, 'j1': 0.0}


def test_no_blend_when_the_first_frame_is_already_the_initial_pose():
    player = MotionPlayer(_Manager())
    player._target_tolerance = lambda _axis: 0.05
    plan = {'blend_to_first_frame': True}
    axes = [_axis(0, 5.0, 5.01, 0.0)]

    assert player._first_frame_targets(plan, axes, {0: 5.0}) == {}
