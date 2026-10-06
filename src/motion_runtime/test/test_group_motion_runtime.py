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
