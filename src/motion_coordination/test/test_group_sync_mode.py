"""그룹 PC 사이 맞춤 · 회차 맞춤 / 각자 재생 · 수정 목록 35 (2026-10-06)"""

import pytest

from motion_coordination.group_execution import GroupExecution


def _started(sync_mode, run_mode='continuous'):
    execution = GroupExecution()
    execution.begin(
        'pc-a', ['pc-a', 'pc-b'], run_mode=run_mode, sync_mode=sync_mode,
    )
    for pc_id in ('pc-a', 'pc-b'):
        execution.mark_ready(pc_id)
    execution.initialize_action(now=0.0)
    for pc_id in ('pc-a', 'pc-b'):
        execution.mark_armed(pc_id)
    execution.start_action(now=0.0)
    for pc_id in ('pc-a', 'pc-b'):
        execution.mark_triggered(pc_id, 1, 1.0)
    return execution


def test_lockstep_is_the_default_and_keeps_the_cycle_barrier():
    execution = _started('')
    assert execution.sync_mode == 'lockstep'
    assert execution.state == 'running'
    assert not execution.independent


def test_independent_drops_the_barrier_after_the_first_shared_start():
    execution = _started('independent')
    assert execution.state == 'running_independent'
    assert execution.independent
    assert execution.cycle_number == 1


def test_independent_one_shot_run_is_plain_running():
    assert _started('independent', run_mode='once').state == 'running'


def test_independent_release_waits_for_every_pc_to_stop():
    execution = _started('independent')
    execution.request_stop_after_cycle()
    assert execution.state == 'running_independent'
    assert execution.mark_independent_stopped('pc-b') is False
    assert execution.mark_independent_stopped('pc-a') is True
    with pytest.raises(ValueError):
        execution.mark_independent_stopped('pc-x')


def test_unknown_mode_reads_as_lockstep():
    execution = GroupExecution()
    execution.begin('pc-a', ['pc-a', 'pc-b'], sync_mode='free')
    assert execution.sync_mode == 'lockstep'
