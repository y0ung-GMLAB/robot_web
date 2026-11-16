"""회차 맞춤 그룹 회차 끝 · 장벽 전 틈에 끝난 상태를 내지 않는다 · 상태 표시 · 수정 목록 199 (2026-11-16)

실물 NY 2026-11-11 14:31 · 플레이어가 회차 애니를 끝내고 그룹 세션이 다음 재생 목록 항목을 기다리는 동안
{completed · completed}(「모션 실행 완료」)를 냈다 · 시간표 구동부가 사람 정지로 읽고 다음 회차를 쉬었다 ·
195 는 「끝남이 5 s 이어져야」 로 덮었다 · 이제 그 틈은 {motion_completed · group_motion_finishing}.
"""

import threading
from unittest import mock

import pytest

from motion_common.run_state import GROUP_CYCLE_FINISHING_PHASE, STATUS_STAMP_KEY, is_running, status_stamp
from motion_runtime import motion_run_rules
from motion_runtime.motion_group_display import resolve_display_step
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.motion_run_manager import MotionRunManager


@pytest.fixture(autouse=True)
def _stop_patches():
    yield
    mock.patch.stopall()


class _Logger:
    def error(self, _message):
        pass

    warn = warning = info = debug = error


def _manager():
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager.period_sec = 0.001
    manager._run_lock = threading.RLock()
    manager._stop_event = threading.Event()
    manager._graceful_stop_event = threading.Event()
    manager._status = motion_run_rules._empty_status()
    manager._execution_context = {}
    manager._execution_context_ready = True
    manager._live_overrides = {}
    manager._live_override_lock = threading.Lock()
    manager._publish_status = lambda: None
    manager._player._require_playback_command_allowed = lambda axes=None: None
    manager._current_motors = lambda: []
    manager._player._prepare_motion_stream = lambda _motors, _axes: None
    manager._player._publish_motion_setpoints = lambda *_args, **_kwargs: None
    manager._player._trace_begin = lambda _plan, _cycle: None
    manager._player._current_servo_alarm_grade = lambda: 0
    mock.patch.object(motion_run_rules, '_sleep_until', lambda _deadline: None).start()
    manager.get_logger = lambda: _Logger()
    seen = []
    real_set = manager._set_status

    def recording_set(status):
        real_set(status)
        seen.append((manager._status['state'], manager._status.get('phase')))

    manager._set_status = recording_set
    return manager, seen


def _plan(**extra):
    return {
        'project_id': 'project', 'request_source': 'group_control', 'motion_file_id': 'a.json',
        'mapping_file_id': 'm.yaml', 'run_mode': 'once', 'automation_run': False, 'repeat_mode': 'reinitialize',
        'dwell_sec': 0.0, 'synchronized_repeat_count': 0, 'axes': [],
        'samples': [{'time_sec': 0.0, 'positions': {}, 'motion_values': {}}],
        'warnings': [], 'capabilities': {},
        'summary': {'duration_sec': 0.0, 'sample_count': 1, 'target_cycle_count': 0},
        **extra,
    }


def test_a_lockstep_group_cycle_never_shows_completed_before_the_barrier():
    """고치기 전에는 마지막 상태가 {completed · completed} 라 이 시험이 실패한다"""
    manager, seen = _manager()
    plan = _plan(group_execution=True, execution_id='tt-s1', group_cycle_number=23)

    manager._player._run_motion(plan)

    assert ('completed', 'completed') not in seen, seen
    status = manager.status()
    assert status['state'] == 'motion_completed'
    assert status['phase'] == GROUP_CYCLE_FINISHING_PHASE
    assert status['group_execution'] is True and status['execution_id'] == 'tt-s1'
    assert '23회차' in status['message']
    assert not is_running(status['state']), '도는 것으로도 보지 않는다(스케줄 점검 · 주차 판정 그대로)'
    assert resolve_display_step(status) == '회차 완료'


def test_a_solo_run_and_an_independent_group_run_still_end_completed():
    manager, _ = _manager()
    manager._player._run_motion(_plan(request_source='motion_run'))
    assert (manager.status()['state'], manager.status()['phase']) == ('completed', 'completed')
    manager, _ = _manager()
    manager._player._run_motion(_plan(group_execution=True, execution_id='e1', independent_group=True))
    assert (manager.status()['state'], manager.status()['phase']) == ('completed', 'completed'), '각자 재생 · 이 PC 혼자 끝'


def test_every_status_change_carries_an_increasing_stamp_and_progress_does_not():
    """명령을 보낸 쪽(시간표 구동부)이 「응답 뒤의 상태인가」 를 시간 기다림 없이 가린다"""
    manager, _ = _manager()
    manager._set_status({**motion_run_rules._empty_status(), 'state': 'preparing'})
    first = status_stamp(manager.status())
    assert first > 0.0
    manager._update_status({'state': 'armed'})
    second = status_stamp(manager.status())
    assert second >= first and STATUS_STAMP_KEY in manager.status()
    manager._update_progress('running', 1.0, 2.0, 1, 0)
    assert status_stamp(manager.status()) == second, '진행만 바뀌면 그대로'
