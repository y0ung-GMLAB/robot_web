"""그대로 재생하던 PC 를 회차 끝에서 다시 합친다 · 로컬 재생 쪽 · 수정 목록 183

「연락 끊김」 동안 이 PC 는 제 회차를 계속 돌았고(진행 PC 가 안 보이면 스스로 이어) 회차 번호를 하나씩
셌다 · 진행 PC 가 경계에서 넣으면 계획은 그대로 · 회차 번호만 진행 PC 것으로 맞춘다.
"""

import threading
import time

import pytest

from test_group_motion_runtime import _group_manager, _wait_until


def _playing_manager():
    manager = _group_manager()
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
        'execution_id': 'exec-a', 'initialize_monotonic': time.monotonic() + 1.0,
    }, [{}]))
    worker.start()
    _wait_until(lambda: manager._group.session.get('state') == 'armed')
    manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 1, 'start_monotonic': time.monotonic() + 1.0,
    })
    _wait_until(lambda: manager._group.session.get('state') == 'motion_completed')
    return manager, worker, initializations, cycles


def test_a_merge_takes_the_masters_cycle_number_and_keeps_the_plan():
    manager, worker, initializations, cycles = _playing_manager()
    assert cycles == [1], '이 PC 가 혼자 센 회차'

    merged = manager._group.commit_join({'execution_id': 'exec-a', 'cycle_number': 7, 'merge': True})

    assert merged['success'] is True
    assert '1회차 → 그룹 7회차' in merged['message']
    assert manager.status()['phase'] == 'group_join_committed', '회차 끝 사건을 다시 내지 않는다'
    assert manager.status()['current_cycle'] == 7
    # 진행 PC 의 회차 초기화 · 시작이 그대로 받아진다
    manager._group.schedule_initialization({
        'execution_id': 'exec-a', 'cycle_number': 7,
        'initialize_monotonic': time.monotonic() + 0.05,
    })
    _wait_until(lambda: manager._group.session.get('state') == 'cycle_ready')
    assert manager._group.session['cycle_number'] == 7
    assert manager.status()['current_cycle'] == 7
    started = manager._group.schedule_cycle({
        'execution_id': 'exec-a', 'cycle_number': 8, 'start_monotonic': time.monotonic() + 1.0,
    })
    assert started['success'] is True
    _wait_until(lambda: cycles == [1, 8])
    manager._group.cancel({'execution_id': 'exec-a'})
    worker.join(timeout=1.0)
    assert not worker.is_alive()


def test_a_merge_is_refused_away_from_the_barrier():
    manager = _group_manager()
    manager._group.session.update({'state': 'start_scheduled', 'cycle_number': 4})

    with pytest.raises(ValueError, match='회차 끝 장벽'):
        manager._group.commit_join({'execution_id': 'exec-a', 'cycle_number': 9, 'merge': True})
    assert manager._group.session['cycle_number'] == 4


def test_a_plain_commit_still_needs_a_ready_join():
    manager = _group_manager()
    manager._group.session.update({'state': 'motion_completed', 'cycle_number': 4})

    with pytest.raises(ValueError, match='복귀 준비가 끝나지 않아'):
        manager._group.commit_join({'execution_id': 'exec-a', 'cycle_number': 9})
