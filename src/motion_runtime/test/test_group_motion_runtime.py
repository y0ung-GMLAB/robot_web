import threading
import time

from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.motion_player import MotionPlayer
from motion_runtime.plan_builder import PlanBuilder
from motion_runtime.group_session import GroupSession
from motion_runtime import motion_run_rules


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError('condition timeout')


def _group_manager():
    manager = MotionRunManager.__new__(MotionRunManager)
    manager._player = MotionPlayer(manager)
    manager._plan_builder = PlanBuilder(manager)
    manager._run_lock = threading.RLock()
    # 그룹 세션은 별도 객체가 갖는다 (§6-29)
    manager._group = GroupSession(manager, run_lock=manager._run_lock)
    manager._group.session = {
        'active': True, 'execution_id': 'exec-a', 'state': 'preparing',
        'cycle_number': 0, 'next_cycle_number': 0, 'next_start_at': 0.0,
        'stop_after_cycle': False,
    }
    manager._stop_event = threading.Event()
    manager._graceful_stop_event = threading.Event()
    manager.period_sec = 0.02
    manager._status = {}
    manager.status = lambda: dict(manager._status)
    manager._set_status = lambda value: setattr(manager, '_status', dict(value))
    manager._update_status = lambda value: manager._status.update(dict(value))
    manager.get_logger = lambda: type('Logger', (), {
        'error': lambda self, _message: None,
    })()
    return manager


def test_one_start_at_runs_exactly_one_motion_then_waits_for_next_cycle():
    manager = _group_manager()
    manager._plan_builder.build = lambda payload, **kwargs: {
        'run_mode': payload.get('run_mode', 'once'),
        'repeat_mode': 'direct', 'dwell_sec': 0.0,
        'group_execution': True,
        'capabilities': {'continuous_run': {'available': True}},
    }
    manager._wait_group_deadline = lambda *_args, **_kwargs: None
    manager._player._run_initialization = lambda _plan: manager._status.update({
        'state': 'initialized', 'phase': 'initialized',
    })
    calls = []

    def run_motion(plan):
        calls.append(int(plan['group_cycle_number']))
        manager._status.update({
            'state': 'completed', 'phase': 'completed',
            'lifecycle': {
                'motion_started_at': time.time(),
                'motion_started_monotonic': time.monotonic(),
            },
        })

    manager._player._run_motion = run_motion
    worker = threading.Thread(target=manager._group._run, args=({
        'execution_id': 'exec-a',
        'initialize_monotonic': time.monotonic() + 1.0,
    }, [{}]))
    worker.start()
    _wait_until(lambda: manager._group.session.get('state') == 'armed')

    first = manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'start_monotonic': time.monotonic() + 1.0,
    })
    assert first['success'] is True
    _wait_until(lambda: manager._group.session.get('state') == 'motion_completed')
    initialize = manager._group.schedule_initialization({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'initialize_monotonic': time.monotonic() + 0.05,
    })
    assert initialize['success'] is True
    _wait_until(lambda: manager._group.session.get('state') == 'cycle_ready')
    assert calls == [1]
    time.sleep(0.03)
    assert calls == [1]

    second = manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 2,
        'start_monotonic': time.monotonic() + 1.0,
    })
    assert second['success'] is True
    _wait_until(lambda: calls == [1, 2])
    manager._group.cancel({'execution_id': 'exec-a'})
    worker.join(timeout=1.0)
    assert not worker.is_alive()


def test_duplicate_start_at_does_not_schedule_a_second_local_cycle():
    manager = _group_manager()
    manager._group.session['state'] = 'armed'
    scheduled_at = time.monotonic() + 1.0
    first = manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'start_monotonic': scheduled_at,
    })
    duplicate = manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'start_monotonic': scheduled_at,
    })
    assert first['success'] is True
    assert duplicate['duplicate'] is True
    assert manager._group.session['next_cycle_number'] == 1


def test_duplicate_cycle_initialize_does_not_start_another_worker():
    manager = _group_manager()
    manager._group.session.update({
        'state': 'motion_completed',
        'cycle_number': 1,
    })
    scheduled_at = time.monotonic() + 1.0
    first = manager._group.schedule_initialization({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'initialize_monotonic': scheduled_at,
    })
    duplicate = manager._group.schedule_initialization({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'initialize_monotonic': scheduled_at,
    })
    assert first['success'] is True
    assert duplicate['duplicate'] is True
    assert manager._group.session['next_initialize_cycle_number'] == 1


def test_group_stop_after_cycle_does_not_interrupt_running_cycle():
    manager = _group_manager()
    manager._status = {'state': 'running', 'group_execution': True}
    result = manager._handle_stop_after_cycle()
    assert result['success'] is True
    assert manager._group.session['stop_after_cycle'] is True
    assert manager._graceful_stop_event.is_set()
    assert not manager._stop_event.is_set()


def test_group_stop_after_cycle_before_motion_prevents_next_start():
    manager = _group_manager()
    manager._status = {'state': 'armed', 'group_execution': True}
    result = manager._handle_stop_after_cycle()
    assert result['success'] is True
    assert manager._stop_event.is_set()


def test_playback_cycle_number_uses_group_cycle_for_network_motion():
    plan = {'group_execution': True, 'group_cycle_number': 36}
    assert motion_run_rules._playback_cycle_number(plan, 0) == 36
    assert motion_run_rules._playback_cycle_number(plan, 2) == 36


def test_playback_cycle_number_uses_local_counter_for_standalone_motion():
    plan = {'group_execution': False}
    assert motion_run_rules._playback_cycle_number(plan, 0) == 1
    assert motion_run_rules._playback_cycle_number(plan, 2) == 3


# 도는 그룹 복귀 · 수정 목록 30-3 ------------------------------------------- #

def test_rejoining_pc_waits_without_moving_then_joins_from_the_next_cycle():
    manager = _group_manager()
    manager._group.session = {
        'active': True, 'execution_id': 'exec-a', 'state': 'join_preparing',
        'cycle_number': 3, 'join_cycle_number': 3, 'join_committed_cycle': 0,
        'next_cycle_number': 0, 'next_start_at': 0.0,
        'next_initialize_at': 0.0, 'next_initialize_cycle_number': 0,
        'stop_after_cycle': False,
    }
    manager._plan_builder.build = lambda payload, **kwargs: {
        'run_mode': payload.get('run_mode', 'once'), 'repeat_mode': 'reinitialize',
        'dwell_sec': 0.0, 'group_execution': True,
        'capabilities': {'continuous_run': {'available': True}},
    }
    manager._wait_group_deadline = lambda *_args, **_kwargs: None
    initializations = []

    def run_initialization(plan):
        initializations.append(int(plan.get('group_cycle_number') or 0))
        manager._status.update({'state': 'initialized', 'phase': 'initialized'})

    manager._player._run_initialization = run_initialization
    cycles = []

    def run_motion(plan):
        cycles.append(int(plan['group_cycle_number']))
        manager._status.update({
            'state': 'completed', 'phase': 'completed',
            'lifecycle': {'motion_started_at': time.time()},
        })

    manager._player._run_motion = run_motion
    worker = threading.Thread(target=manager._group._run, args=({
        'execution_id': 'exec-a', 'join_cycle_number': 3,
    }, [{}]))
    worker.start()
    _wait_until(lambda: manager._group.session.get('state') == 'join_ready')
    assert manager.status()['phase'] == 'group_join_ready'
    time.sleep(0.03)
    assert initializations == [] and cycles == []          # 확정 전에는 안 움직인다

    committed = manager._group.commit_join({'execution_id': 'exec-a', 'cycle_number': 3})
    assert committed['success'] is True
    # 확정 직후 다른 PC 와 같은 회차 초기화를 받는다
    manager._group.schedule_initialization({
        'execution_id': 'exec-a', 'cycle_number': 3,
        'initialize_monotonic': time.monotonic() + 0.05,
    })
    _wait_until(lambda: manager._group.session.get('state') == 'cycle_ready')
    assert initializations == [3]
    assert manager.status()['phase'] == 'group_cycle_initialized'

    manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 4,
        'start_monotonic': time.monotonic() + 1.0,
    })
    _wait_until(lambda: cycles == [4])
    manager._group.cancel({'execution_id': 'exec-a'})
    worker.join(timeout=1.0)
    assert not worker.is_alive()


def test_join_commit_before_the_plan_is_ready_is_refused():
    manager = _group_manager()
    manager._group.session = {
        'active': True, 'execution_id': 'exec-a', 'state': 'join_preparing',
        'cycle_number': 3, 'join_committed_cycle': 0,
    }
    try:
        manager._group.commit_join({'execution_id': 'exec-a', 'cycle_number': 3})
    except ValueError as exc:
        assert '복귀 준비가 끝나지 않아' in str(exc)
    else:
        raise AssertionError('commit before ready must fail')


def test_join_prepare_needs_no_initialize_time_but_a_normal_prepare_does():
    from motion_runtime.group_session import GroupSession
    session = GroupSession.__new__(GroupSession)
    try:
        session.prepare({'execution_id': 'exec-a'})
    except ValueError as exc:
        assert '트리거' in str(exc)
    else:
        raise AssertionError('normal prepare needs initialize_monotonic')


def test_release_after_a_finished_once_run_stays_completed():
    """수정 목록 112 마 · 끝까지 돈 그룹 1회를 마스터가 세션 정리(group_cancel)할 때 「취소」 로 덮지 않는다"""
    manager = _group_manager()
    manager._run_thread = None
    manager._status = {'state': 'completed', 'message': '모션 실행 완료'}
    result = manager._group.cancel({'execution_id': 'exec-a'})
    assert result['success'] is True
    assert manager._status['state'] == 'completed'
    assert '완료' in manager._status['message']


def test_cancel_before_the_motion_finished_is_still_a_cancel():
    manager = _group_manager()
    manager._run_thread = None
    manager._status = {'state': 'initializing'}
    manager._group.cancel({'execution_id': 'exec-a'})
    assert manager._status['state'] == 'stopped'
    assert manager._status['message'] == '그룹 실행 취소'


# 회차 후 정지 뒤 세션 정리 · 수정 목록 141 ------------------------------------ #

def test_schedule_end_release_after_the_cycle_says_window_end_not_cancel():
    """실물 S-11 · 구간 끝 회차 후 정지 → 마스터의 세션 정리가 「그룹 실행 취소」 로 덮었다"""
    manager = _group_manager()
    manager._run_thread = None
    manager._status = {'state': 'running', 'group_execution': True}
    assert manager._handle_stop_after_cycle({'reason': 'schedule_end'})['success'] is True
    assert manager._group.session['stop_reason'] == 'schedule_end'
    manager._status = {'state': 'stopped', 'message': '구간 끝 · 회차 후 정지'}
    result = manager._group.cancel({'execution_id': 'exec-a'})
    assert result['success'] is True
    assert manager._status['state'] == 'stopped'
    assert manager._status['message'] == '구간 끝 · 회차 후 정지'
    assert '취소' not in result['message']


def test_human_stop_after_cycle_release_is_not_a_cancel_either():
    manager = _group_manager()
    manager._run_thread = None
    manager._status = {'state': 'running', 'group_execution': True}
    manager._handle_stop_after_cycle({})
    manager._status = {'state': 'stopped'}
    manager._group.cancel({'execution_id': 'exec-a'})
    assert manager._status['message'] == '현재 그룹 모션 회차 완료 후 정지'


def test_stop_now_after_a_stop_after_cycle_is_still_a_cancel():
    """회차 후 정지를 받은 뒤 사람이 즉시 정지 · 회차 후 정지 문구로 덮지 않는다"""
    manager = _group_manager()
    manager._run_thread = None
    manager._status = {'state': 'running', 'group_execution': True}
    manager._handle_stop_after_cycle({'reason': 'schedule_end'})
    manager._group.mark_stopping()
    manager._status = {'state': 'stopping'}
    manager._group.cancel({'execution_id': 'exec-a'})
    assert manager._status['message'] == '그룹 실행 취소'


def test_schedule_end_after_the_last_cycle_finishes_with_the_window_end_text():
    manager = _group_manager()
    manager._plan_builder.build = lambda payload, **kwargs: {
        'run_mode': payload.get('run_mode', 'once'),
        'repeat_mode': 'direct', 'dwell_sec': 0.0,
        'group_execution': True,
        'capabilities': {'continuous_run': {'available': True}},
    }
    manager._wait_group_deadline = lambda *_args, **_kwargs: None
    manager._player._run_initialization = lambda _plan: manager._status.update({
        'state': 'initialized', 'phase': 'initialized',
    })
    stop_sent = threading.Event()

    def run_motion(plan):
        # 회차 도중 구간 끝 · 회차 후 정지가 온다
        manager._status.update({'state': 'running', 'group_execution': True})
        manager._handle_stop_after_cycle({'reason': 'schedule_end'})
        stop_sent.set()
        manager._status.update({
            'state': 'completed', 'phase': 'completed',
            'lifecycle': {'motion_started_at': time.time()},
        })

    manager._player._run_motion = run_motion
    manager._run_thread = None
    worker = threading.Thread(target=manager._group._run, args=({
        'execution_id': 'exec-a',
        'initialize_monotonic': time.monotonic() + 1.0,
    }, [{}]))
    worker.start()
    _wait_until(lambda: manager._group.session.get('state') == 'armed')
    manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'start_monotonic': time.monotonic() + 1.0,
    })
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert stop_sent.is_set()
    assert manager._status['state'] == 'stopped'
    assert manager._status['message'] == '구간 끝 · 회차 후 정지'
    # 마스터의 세션 정리가 와도 그대로
    manager._group.cancel({'execution_id': 'exec-a'})
    assert manager._status['message'] == '구간 끝 · 회차 후 정지'


# 회차 맞춤 · 그룹 전체 회차 후 정지 · 장벽에서 풀기를 기다린다 · 수정 목록 154 · 155 ----------- #

def _cycle_worker(manager, *, stop_payload=None):
    """1회차를 돌린다 · `stop_payload` 가 있으면 회차 도중 회차 후 정지를 보낸다"""
    manager._plan_builder.build = lambda payload, **kwargs: {
        'run_mode': payload.get('run_mode', 'once'),
        'repeat_mode': 'reinitialize', 'dwell_sec': 0.0,
        'group_execution': True,
        'capabilities': {'continuous_run': {'available': True}},
    }
    manager._wait_group_deadline = lambda *_args, **_kwargs: None
    manager._player._run_initialization = lambda _plan: manager._status.update({
        'state': 'initialized', 'phase': 'initialized',
    })

    def run_motion(plan):
        manager._status.update({'state': 'running', 'phase': 'running', 'group_execution': True})
        if stop_payload is not None:
            manager._handle_stop_after_cycle(dict(stop_payload))
        manager._status.update({
            'state': 'completed', 'phase': 'completed',
            'lifecycle': {'motion_started_at': time.time()},
        })

    manager._player._run_motion = run_motion
    manager._run_thread = threading.Thread(target=manager._group._run, args=({
        'execution_id': 'exec-a',
        'initialize_monotonic': time.monotonic() + 1.0,
    }, [{}]))
    manager._run_thread.start()
    _wait_until(lambda: manager._group.session.get('state') == 'armed')
    manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 1,
        'start_monotonic': time.monotonic() + 1.0,
    })
    return manager._run_thread


def test_group_wide_stop_after_cycle_waits_at_the_barrier_until_released():
    """짧은 PC · 제 회차 끝 → 「정지」 대신 장벽에 선다 · 진행 PC 가 긴 PC 끝을 보고 푼다 · 154"""
    from motion_runtime.motion_group_display import resolve_display_step

    manager = _group_manager()
    worker = _cycle_worker(manager, stop_payload={'reason': 'schedule_end', 'group_wide': True})

    _wait_until(lambda: manager._status.get('phase') == 'group_motion_completed')
    time.sleep(0.05)
    assert worker.is_alive(), '장벽에서 기다린다 · 멈추지 않는다'
    assert manager._status['state'] == 'motion_completed', '장벽 보고 · 진행 PC 가 회차 끝으로 읽는다'
    assert manager._status['phase'] == 'group_motion_completed'
    assert not manager._stop_event.is_set()
    assert '회차 후 정지 대기' in manager._status['message']
    assert resolve_display_step({**manager._status, 'execution_id': 'exec-a'}) == '회차 후 정지 대기'

    result = manager._group.cancel({'execution_id': 'exec-a'})

    assert not worker.is_alive()
    assert result['success'] is True
    assert manager._status['state'] == 'stopped'
    assert manager._status['message'] == '구간 끝 · 회차 후 정지'


def test_group_wide_stop_received_at_the_barrier_shows_the_wait():
    """긴 PC 재생 중 · 짧은 PC 는 이미 장벽 · 그때 구간 끝 · 155"""
    manager = _group_manager()
    manager._group.session.update({'state': 'motion_completed', 'cycle_number': 2})
    manager._status = {
        'state': 'motion_completed', 'phase': 'group_motion_completed',
        'group_execution': True, 'message': '그룹 모션 2회차 완료',
    }

    assert manager._handle_stop_after_cycle({'reason': 'schedule_end', 'group_wide': True})['success'] is True

    assert not manager._stop_event.is_set()
    assert manager._status['state'] == 'motion_completed'
    assert manager._status['phase'] == 'group_motion_completed'
    assert manager._status['message'].startswith('그룹 모션 2회차 완료 · 회차 후 정지 대기')


def test_a_local_only_stop_after_cycle_still_finishes_at_the_cycle_end():
    """이 PC 만의 회차 후 정지(1등급 알람 · 단독 길) · 진행 PC 는 모른다 · 옛 그대로 멈춰 「먼저 정지」 로 알린다"""
    manager = _group_manager()
    worker = _cycle_worker(manager, stop_payload={'reason': 'schedule_end'})

    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert manager._status['state'] == 'stopped'
    assert manager._status['message'] == '구간 끝 · 회차 후 정지'


def test_stop_after_cycle_right_after_the_cycle_motion_does_not_cut_it():
    """회차 애니가 막 끝나 장벽 표시 직전(`completed`) · 즉시 정지로 읽지 않는다 · 154"""
    manager = _group_manager()
    manager._status = {'state': 'completed', 'group_execution': True}

    assert manager._handle_stop_after_cycle({'group_wide': True})['success'] is True

    assert not manager._stop_event.is_set()
    assert manager._graceful_stop_event.is_set()
    assert manager._group.session['stop_after_cycle_group'] is True


def test_group_wide_stop_between_cycles_still_stops_at_once():
    """회차 사이(초기 위치 · 시작 대기)에 받은 회차 후 정지는 옛 그대로 바로 선다 · 모든 PC 가 같은 단계"""
    manager = _group_manager()
    manager._status = {'state': 'waiting', 'group_execution': True}

    manager._handle_stop_after_cycle({'reason': 'schedule_end', 'group_wide': True})

    assert manager._stop_event.is_set()
