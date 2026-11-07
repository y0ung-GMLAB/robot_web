"""회차 눈금 · 진행 PC 가 없어도 같은 순간에 · 수정 목록 178 (2026-11-08)

진행 PC 는 2회차부터 「앞 시작 + 주기」 에 시작한다(주기 = 10 s 올림 · 줄이지 않음) · 참가 PC 는 시작 둘의
간격으로 주기를 알고, 진행 PC 가 안 보이면 「마지막 시작 + n × 주기」 에 스스로 시작한다.
"""

import time

import pytest
from motion_coordination_interfaces.msg import GroupCommand

from motion_coordination.cycle_grid import (
    GRID_STEP_SEC, aligned_start, next_grid_start, round_up_period,
)
from motion_coordination.group_execution import GroupExecution
from test_coordination_node import _node, _Publisher


# --------------------------------------------------------------------------- #
# 계산
# --------------------------------------------------------------------------- #

def test_the_period_is_the_cycle_plus_a_margin_rounded_up_to_ten_seconds():
    # 사용자 예 · 920 s 애니 + 초기 이동 7 s → 930 s 대 · 여유 2 s 를 더해 올림
    assert round_up_period(927.0) == 930.0
    assert round_up_period(928.5) == 940.0
    assert round_up_period(0.0) == GRID_STEP_SEC


def test_the_second_cycle_sets_the_period_and_later_cycles_keep_it():
    start, period = aligned_start(natural=1927.3, last_start=1000.0, period=0.0)
    assert (start, period) == (1930.0, 930.0)
    start, period = aligned_start(natural=2855.0, last_start=1930.0, period=930.0)
    assert (start, period) == (2860.0, 930.0), '눈금이 자연스러운 시작보다 뒤 · 그대로'


def test_an_overrun_grows_the_period_and_never_shrinks_it():
    start, period = aligned_start(natural=2865.0, last_start=1930.0, period=930.0)
    assert period == 940.0 and start == 2870.0
    start, period = aligned_start(natural=3700.0, last_start=2870.0, period=940.0)
    assert period == 940.0 and start == 3810.0


def test_the_next_slot_skips_slots_that_are_already_too_close():
    assert next_grid_start(last_start=1000.0, period=930.0, earliest=1500.0) == (1, 1930.0)
    assert next_grid_start(last_start=1000.0, period=930.0, earliest=1935.0) == (2, 2860.0)
    with pytest.raises(ValueError):
        next_grid_start(last_start=0.0, period=0.0, earliest=1.0)


# --------------------------------------------------------------------------- #
# 진행 PC · 2회차부터 눈금에
# --------------------------------------------------------------------------- #

def test_the_master_puts_later_cycles_on_the_grid():
    node = _node()
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a', 'pc-b'), run_mode='continuous')
    first = node._execution.start_action  # 손으로 만든 시작 · 1회차
    from motion_coordination.group_execution import ScheduledAction
    eid = node._execution.execution_id
    one = node._align_start_to_grid(ScheduledAction('start_at', eid, 1, 1000.0))
    two = node._align_start_to_grid(ScheduledAction('start_at', eid, 2, 1927.3))
    three = node._align_start_to_grid(ScheduledAction('start_at', eid, 3, 2856.0))
    assert one.scheduled_at == 1000.0
    assert two.scheduled_at == 1930.0
    assert three.scheduled_at == 2860.0
    assert three.command_id != two.command_id and first is not None


def test_once_and_independent_runs_are_not_put_on_a_grid():
    from motion_coordination.group_execution import ScheduledAction
    for overrides in ({'run_mode': 'once'}, {'sync_mode': 'independent'}):
        node = _node()
        node._execution = GroupExecution()
        node._execution.begin('pc-a', ('pc-a',), run_mode='continuous')
        for key, value in overrides.items():
            setattr(node._execution, key, value)
        eid = node._execution.execution_id
        node._align_start_to_grid(ScheduledAction('start_at', eid, 1, 1000.0))
        two = node._align_start_to_grid(ScheduledAction('start_at', eid, 2, 1927.3))
        assert two.scheduled_at == 1927.3, overrides


# --------------------------------------------------------------------------- #
# 참가 PC · 진행 PC 가 안 보이면 스스로
# --------------------------------------------------------------------------- #

def _participant(*, phase, operating=True, master_offline=True, period=930.0, cycle=4):
    node = _node()
    node._config = type(node._config)(**{**vars(node._config), 'pc_id': 'pc-b'}) \
        if not hasattr(node._config, '__dataclass_fields__') else node._config
    if hasattr(node._config, '__dataclass_fields__'):
        from dataclasses import replace
        node._config = replace(node._config, pc_id='pc-b')
    node._execution = GroupExecution()
    node._execution.activate_claim('exec-a', 'pc-a', ('pc-a', 'pc-b'))
    node._execution.run_mode = 'continuous'
    node._execution.sync_mode = 'lockstep'
    node._execution.initial_move_time_sec = 7.0
    now = time.monotonic()
    node._grid_seen = {
        'execution_id': 'exec-a', 'period': period, 'cycle': cycle,
        'start': now - 900.0,
    }
    node._local_status = {
        'operation_mode': 'schedule' if operating else 'manual',
        'schedule_window_open': operating,
        'motion_run_status': {
            'group_execution': True, 'execution_id': 'exec-a', 'phase': phase,
            'current_cycle': cycle,
        },
    }
    node._registry.status = lambda pc_id, **_kwargs: (
        'offline' if master_offline and pc_id == 'pc-a' else 'online'
    )
    calls = []
    node._call_local_control = lambda payload, **_kwargs: calls.append(dict(payload)) or {'success': True}
    node._command_pub = _Publisher()
    return node, calls


def test_a_participant_continues_on_the_grid_when_the_master_is_gone():
    node, calls = _participant(phase='group_motion_completed')
    started = node._grid_seen['start']

    node._drive_autonomous_cycle()

    [init] = calls
    assert init['command'] == 'group_initialize_at'
    assert init['cycle_number'] == 4, '끝낸 회차'
    expected_start = started + 930.0
    assert init['initialize_monotonic'] == pytest.approx(expected_start - 7.0 - 2.0, abs=0.01)
    assert node._autonomy['stage'] == 'initializing' and node._autonomy['cycle'] == 5

    node._local_status['motion_run_status']['phase'] = 'group_cycle_initialized'
    node._drive_autonomous_cycle()

    start = calls[-1]
    assert start['command'] == 'group_start_at'
    assert start['cycle_number'] == 5
    assert start['start_monotonic'] == pytest.approx(expected_start, abs=0.01)
    assert node._grid_seen['period'] == 930.0, '스스로 잇는 회차로 주기를 다시 재지 않는다'
    assert node._command_pub.messages == [], '그룹 명령은 내지 않는다'


def test_a_late_slot_is_skipped_but_the_cycle_number_steps_by_one():
    node, calls = _participant(phase='group_motion_completed')
    node._grid_seen['start'] = time.monotonic() - 925.0      # 다음 칸까지 5 s · 초기 이동 7 s 에 모자람

    node._drive_autonomous_cycle()

    [init] = calls
    assert init['cycle_number'] == 4
    assert node._autonomy['cycle'] == 5
    assert node._autonomy['start'] == pytest.approx(node._grid_seen['start'] + 2 * 930.0, abs=0.01)


def test_no_autonomy_while_the_master_is_seen_or_outside_operating_hours():
    for kwargs in ({'master_offline': False}, {'operating': False}):
        node, calls = _participant(phase='group_motion_completed', **kwargs)
        node._drive_autonomous_cycle()
        assert calls == [], kwargs
        assert getattr(node, '_autonomy', None) is None


def test_no_autonomy_before_the_period_is_known():
    node, calls = _participant(phase='group_motion_completed', period=0.0)
    node._drive_autonomous_cycle()
    assert calls == []


def test_when_the_master_returns_the_participant_finishes_and_releases(monkeypatch):
    import motion_coordination.coordination_node as coordination_node
    from test_coordination_node import _InlineThread
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node, calls = _participant(phase='group_motion_completed')
    node._drive_autonomous_cycle()                                   # 스스로 시작
    node._registry.status = lambda pc_id, **_kwargs: 'online'         # 진행 PC 다시 보임
    node._local_status['motion_run_status']['phase'] = 'running'
    node._drive_autonomous_cycle()
    assert node._execution.execution_id == 'exec-a', '회차 중에는 그대로'

    node._local_status['motion_run_status']['phase'] = 'group_motion_completed'
    node._drive_autonomous_cycle()

    assert node._execution.execution_id == '', '회차를 마치고 놓는다 · 진행 PC 가 다시 넣는다'
    assert calls[-1]['command'] == 'stop_now'
