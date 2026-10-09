"""연속 재생 자동 복구 · 가벼운 오류는 스스로 다시 · 한도 넘으면 최종 오류 · 수정 목록 73"""

import threading
from types import SimpleNamespace

from motion_common import cycle_failure
from motion_runtime import motion_player
from motion_runtime.motion_player import MotionPlayer


class Manager:
    def __init__(self, *, blocked=''):
        self._stop_event = threading.Event()
        self.statuses = []
        self.blocked = blocked
        self.cycle_count = 0
        self.automation_failures = []

    def status(self):
        return {'cycle_count': self.cycle_count}

    def _set_status(self, status):
        self.statuses.append(dict(status))

    def _playback_ownership_error(self, axes=None):
        return self.blocked

    def _current_motors(self):
        return [{'controller_index': 0}]

    def _automation_failure(self, text):
        self.automation_failures.append(text)

    def get_logger(self):
        return SimpleNamespace(warning=lambda *_: None, error=lambda *_: None)


def _player(manager, outcomes, monkeypatch):
    player = MotionPlayer(manager)
    calls = []

    def once(mode, payload, motors):
        calls.append(mode)
        return outcomes.pop(0) if outcomes else None

    player._prepare_and_run_once = once
    monkeypatch.setattr(motion_player, 'AUTO_RECOVERY_DELAY_SEC', 0.0)
    return player, calls


LIGHT = RuntimeError(cycle_failure.tagged('모션 최종 위치 도달 확인 실패: 2번 모터 오차 3.5'))
CONTINUOUS = {'run_mode': 'continuous'}


def test_light_error_is_retried_then_continues(monkeypatch):
    manager = Manager()
    player, calls = _player(manager, [LIGHT, LIGHT, None], monkeypatch)

    player._prepare_and_run('start', dict(CONTINUOUS), [])

    assert len(calls) == 3
    states = [status['state'] for status in manager.statuses]
    assert states == ['recovering', 'recovering']
    assert manager.statuses[1]['auto_recovery']['attempt'] == 2


def test_more_than_limit_failures_end_in_final_error_marked_exhausted(monkeypatch):
    manager = Manager()
    player, calls = _player(manager, [LIGHT] * 10, monkeypatch)

    player._prepare_and_run('start', dict(CONTINUOUS), [])

    assert len(calls) == motion_player.AUTO_RECOVERY_LIMIT + 1
    final = manager.statuses[-1]
    assert final['state'] == 'error' and final['auto_recovery_exhausted'] is True
    assert '자동 복구 3번 실패' in final['message'] and '서보는 켠 채 제자리' in final['message']


def test_successful_cycles_reset_the_count(monkeypatch):
    manager = Manager()
    outcomes = [LIGHT, LIGHT, LIGHT, LIGHT, None]
    player, calls = _player(manager, outcomes, monkeypatch)
    original = player._prepare_and_run_once

    def once(mode, payload, motors):
        # 셋째 시도에서 회차가 충분히 돌았다
        if len(calls) == 2:
            manager.cycle_count = motion_player.AUTO_RECOVERY_RESET_CYCLES
        else:
            manager.cycle_count = 0
        return original(mode, payload, motors)

    player._prepare_and_run_once = once
    player._prepare_and_run('start', dict(CONTINUOUS), [])
    assert all(status['state'] != 'error' for status in manager.statuses)


def test_once_mode_and_heavy_errors_stop_right_away(monkeypatch):
    manager = Manager()
    player, calls = _player(manager, [LIGHT], monkeypatch)
    player._prepare_and_run('start', {'run_mode': 'once'}, [])
    assert len(calls) == 1 and manager.statuses[-1]['state'] == 'error'

    manager = Manager()
    heavy = RuntimeError('통신이 끊긴 모터가 있어 재생을 멈춥니다')
    player, calls = _player(manager, [heavy], monkeypatch)
    player._prepare_and_run('start', dict(CONTINUOUS), [])
    assert len(calls) == 1 and manager.statuses[-1]['state'] == 'error'
    assert 'auto_recovery_exhausted' not in manager.statuses[-1]


def test_safety_block_prevents_retry(monkeypatch):
    manager = Manager(blocked='2등급 서보 에러 · 전체 모터 동작 차단')
    player, calls = _player(manager, [LIGHT], monkeypatch)
    player._prepare_and_run('start', dict(CONTINUOUS), [])
    assert len(calls) == 1
    assert '자동 복구 안 함(2등급 서보 에러' in manager.statuses[-1]['message']


def test_stop_during_wait_ends_quietly(monkeypatch):
    manager = Manager()
    player, calls = _player(manager, [LIGHT, None], monkeypatch)
    manager._stop_event.set()
    player._prepare_and_run('start', dict(CONTINUOUS), [])
    assert len(calls) == 1 and manager.statuses == []


# ---- 실물 2026-10-09 · 재생 도중(회차 사이 초기 이동) 실패도 자동 복구로 · 실물 확인 대기 68 ----

def _failing_run(plan, monkeypatch):
    manager = Manager()
    player = MotionPlayer(manager)

    def refuse(_axes):
        raise RuntimeError('초기 위치 이동 실패: ' + cycle_failure.tagged('초기 위치 도달 확인 실패 · 2번 모터 오차 0.094°'))

    player._require_playback_command_allowed = refuse
    player._playback_axes = lambda _plan, _t: []
    manager._current_lifecycle = lambda: {}
    return manager, player


def test_a_light_failure_during_continuous_play_goes_up_to_auto_recovery(monkeypatch):
    plan = {'run_mode': 'continuous', 'axes': []}
    manager, player = _failing_run(plan, monkeypatch)
    try:
        player._run_motion(plan)
    except RuntimeError as exc:
        assert cycle_failure.is_cycle_failure(str(exc))
    else:
        raise AssertionError('위로 넘겨야 자동 복구가 받는다')
    assert not [s for s in manager.statuses if s.get('state') == 'error'], '오류 상태는 복구 쪽이 정한다'


def test_once_group_and_heavy_failures_still_end_in_error_right_there(monkeypatch):
    for plan in ({'run_mode': 'once', 'axes': []},
                 {'run_mode': 'continuous', 'group_execution': True, 'axes': []}):
        manager, player = _failing_run(plan, monkeypatch)
        player._run_motion(plan)                     # 넘기지 않는다
        assert manager.statuses[-1]['state'] == 'error'
    assert MotionPlayer._hand_to_auto_recovery({'run_mode': 'continuous'}, RuntimeError('서보 알람')) is False
