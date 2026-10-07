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
