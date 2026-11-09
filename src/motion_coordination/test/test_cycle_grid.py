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
    # 운영시간은 진행 PC 가 명령에 실어 보낸 값 · 이 PC 는 스케줄도 스케줄 모드도 없다 · 수정 목록 182
    node._execution.operating_until = time.time() + 3600.0 if operating else 0.0
    node._local_status = {
        'operation_mode': 'manual',
        'schedule_window_open': False,
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


def test_no_autonomy_once_the_masters_operating_time_has_passed_or_in_off_mode():
    """182 · 진행 PC 가 알려 준 운영시간 끝이 지났거나 · 이 PC 가 끔 모드면 잇지 않는다"""
    node, calls = _participant(phase='group_motion_completed')
    node._execution.operating_until = time.time() - 1.0
    node._drive_autonomous_cycle()
    assert calls == []
    node, calls = _participant(phase='group_motion_completed')
    node._local_status['operation_mode'] = 'off'
    node._drive_autonomous_cycle()
    assert calls == []


def test_no_autonomy_before_the_period_is_known():
    node, calls = _participant(phase='group_motion_completed', period=0.0)
    node._drive_autonomous_cycle()
    assert calls == []


def test_when_the_master_returns_the_participant_keeps_the_run_and_waits_at_the_barrier(monkeypatch):
    """183 · 진행 PC 가 다시 보이면 놓지 않는다 · 새 회차는 스스로 잡지 않고 장벽에서 합류를 기다린다

    전에는(178 ④) 회차를 마치고 놓아 다시 들어오기까지 1회차 이상 쉬었다.
    """
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
    count = len(calls)
    node._drive_autonomous_cycle()

    assert node._execution.execution_id == 'exec-a', '놓지 않는다 · 진행 PC 가 경계에서 다시 넣는다'
    assert node._autonomy is None, '새 회차는 스스로 잡지 않는다'
    assert len(calls) == count, '정지도 회차 초기화도 하지 않는다'


def test_an_already_scheduled_cycle_still_starts_when_the_master_returns():
    """183 · 회차 초기화를 이미 잡았으면 그 회차는 마저 시작한다(초기 자세에 서 있지 않게)"""
    node, calls = _participant(phase='group_motion_completed')
    node._drive_autonomous_cycle()
    node._registry.status = lambda pc_id, **_kwargs: 'online'
    node._local_status['motion_run_status']['phase'] = 'group_cycle_initialized'

    node._drive_autonomous_cycle()

    assert calls[-1]['command'] == 'group_start_at'
    assert node._autonomy['stage'] == 'started'


def test_after_operating_hours_the_participant_finishes_and_releases(monkeypatch):
    """운영시간이 끝나면(진행 PC 는 여전히 안 보임) 전처럼 회차를 마치고 놓는다"""
    import motion_coordination.coordination_node as coordination_node
    from test_coordination_node import _InlineThread
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node, calls = _participant(phase='group_motion_completed')
    node._drive_autonomous_cycle()
    node._execution.operating_until = time.time() - 1.0
    node._local_status['motion_run_status']['phase'] = 'group_motion_completed'
    node._local_status['motion_run_status']['current_cycle'] = 5

    node._drive_autonomous_cycle()

    assert node._execution.execution_id == ''
    # 끊김 시험 P · 세운 뒤 평소 운영 종료처럼 기준점 주차 → 서보 OFF(진행 PC 없이도)
    assert [call['command'] for call in calls[-2:]] == ['stop_now', 'stop_after_cycle']
    assert calls[-1]['reason'] == 'schedule_end' and calls[-1]['execution_id'] == ''


# --------------------------------------------------------------------------- #
# 수정 목록 182 · 진행 PC 가 운영시간 끝을 명령에 싣고 · 참가 PC 는 그 값을 기억한다
# --------------------------------------------------------------------------- #

def _master_with_status(window_ends_at):
    node = _node()
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a', 'pc-b'), run_mode='continuous')
    node._local_status = {'schedule_window_ends_at': window_ends_at}
    return node


def test_the_master_puts_its_operating_end_on_every_command():
    ends = time.time() + 7200.0
    node = _master_with_status(ends)
    command = node._new_command(
        command='prepare', execution_id=node._execution.execution_id,
        cycle_number=0, participants=('pc-a', 'pc-b'),
    )
    assert command.operating_until_unix_sec == pytest.approx(ends)
    assert node._execution.operating_until == pytest.approx(ends)


def test_outside_operating_hours_the_master_sends_zero():
    """사람이 운영시간 밖에 시작(시험 · 지켜봄) · 진행 PC 가 사라지면 참가 PC 는 회차를 마치고 기다린다"""
    for ends in (0.0, time.time() - 5.0):
        node = _master_with_status(ends)
        command = node._new_command(
            command='start_at', execution_id=node._execution.execution_id,
            cycle_number=1, participants=('pc-a', 'pc-b'),
        )
        assert command.operating_until_unix_sec == 0.0


def test_a_participant_remembers_the_masters_operating_end():
    node, _calls = _participant(phase='running', operating=False)
    ends = time.time() + 600.0
    node._note_operating_until(GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='start_at', command_id='cmd-1', participant_ids=['pc-a', 'pc-b'],
        operating_until_unix_sec=ends,
    ))
    assert node._execution.operating_until == pytest.approx(ends)
    # 다른 실행 · 다른 진행 PC 의 값은 받지 않는다
    node._note_operating_until(GroupCommand(
        group_id='stage-a', execution_id='exec-other', coordinator_id='pc-a',
        command='start_at', command_id='cmd-2', participant_ids=['pc-a', 'pc-b'],
        operating_until_unix_sec=1.0,
    ))
    assert node._execution.operating_until == pytest.approx(ends)


# --------------------------------------------------------------------------- #
# 끊김 시험 A (2026-11-08) · 스케줄 시작은 초기 이동 시간을 0(= PC마다 매핑 값)으로 보낸다
#
# 실물 · 마스터 Wi-Fi 150 s 끊음 · 참가 PC 3대가 스스로 잇다가 초기 이동(5 s)을 시작 2 s 전에 걸어
# 3 s 늦게 준비 · 「트리거가 이미 지났습니다」 → 3대 모두 빠지고 섬.
# --------------------------------------------------------------------------- #

def _late_start_reply(payload):
    if payload['command'] == 'group_start_at':
        return {'success': False, 'message': '그룹 모션 시작 트리거가 이미 지났습니다'}
    return {'success': True}


def test_zero_initial_move_time_uses_this_pcs_actual_initialization_time():
    node, calls = _participant(phase='group_motion_completed')
    node._execution.initial_move_time_sec = 0.0
    node._local_status['motion_run_status']['summary'] = {'initialization_duration_sec': 5.0}
    started = node._grid_seen['start']

    node._drive_autonomous_cycle()

    [init] = calls
    start = node._autonomy['start']
    assert start == pytest.approx(started + 930.0, abs=0.01)
    assert init['initialize_monotonic'] <= start - 7.0 + 0.01, '초기 이동 5 s + 여유 2 s 전에 출발'


def test_zero_initial_move_time_without_a_local_value_falls_back_to_ten_seconds():
    node, calls = _participant(phase='group_motion_completed')
    node._execution.initial_move_time_sec = 0.0

    node._drive_autonomous_cycle()

    [init] = calls
    assert init['initialize_monotonic'] == pytest.approx(node._autonomy['start'] - 10.0 - 2.0, abs=0.01)


def test_a_missed_start_is_moved_to_the_next_grid_slot_once():
    node, calls = _participant(phase='group_motion_completed')
    node._drive_autonomous_cycle()
    # 초기화가 늦게 끝났다 · 잡은 시작이 1 s 전에 지났다
    node._grid_seen['start'] = time.monotonic() - 931.0
    first = node._autonomy['start'] = node._grid_seen['start'] + 930.0
    replies = [
        {'success': False, 'message': '그룹 모션 시작 트리거가 이미 지났습니다'},
        {'success': True},
    ]
    node._call_local_control = lambda payload, **_kwargs: calls.append(dict(payload)) or replies.pop(0)
    node._local_status['motion_run_status']['phase'] = 'group_cycle_initialized'

    node._drive_autonomous_cycle()

    retry = calls[-1]
    assert [call['command'] for call in calls[-2:]] == ['group_start_at', 'group_start_at']
    assert retry['start_monotonic'] > first, '다음 눈금으로'
    assert retry['cycle_number'] == calls[-2]['cycle_number'], '회차 번호는 그대로'
    assert node._execution.execution_id == 'exec-a', '빠지지 않는다'
    assert node._autonomy['stage'] == 'started'
    assert node._autonomy['start'] == pytest.approx(retry['start_monotonic'])


def test_a_second_missed_start_leaves_but_accepts_the_masters_invite(monkeypatch):
    """다음 눈금도 못 잡으면 전처럼 빠진다 · 그 실행의 복귀 권유는 받는다(끊김 시험 C)"""
    import motion_coordination.coordination_node as coordination_node
    from test_coordination_node import _InlineThread
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node, calls = _participant(phase='group_motion_completed')
    node._drive_autonomous_cycle()
    node._grid_seen['start'] = time.monotonic() - 931.0
    node._autonomy['start'] = node._grid_seen['start'] + 930.0
    node._call_local_control = lambda payload, **_kwargs: calls.append(dict(payload)) or _late_start_reply(payload)
    node._local_status['motion_run_status']['phase'] = 'group_cycle_initialized'

    node._drive_autonomous_cycle()

    assert [call['command'] for call in calls[-3:]] == ['group_start_at', 'group_start_at', 'stop_now']
    assert node._execution.execution_id == ''
    assert 'exec-a' in node._cancelled_execution_ids
    assert 'exec-a' in node._drop_released(), '복귀 권유(join)는 받는다'


def test_other_start_refusals_are_not_retried(monkeypatch):
    import motion_coordination.coordination_node as coordination_node
    from test_coordination_node import _InlineThread
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node, calls = _participant(phase='group_motion_completed')
    node._drive_autonomous_cycle()
    node._call_local_control = lambda payload, **_kwargs: calls.append(dict(payload)) or (
        {'success': False, 'message': '활성 그룹 실행 세션이 일치하지 않습니다'}
        if payload['command'] == 'group_start_at' else {'success': True}
    )
    node._local_status['motion_run_status']['phase'] = 'group_cycle_initialized'

    node._drive_autonomous_cycle()

    assert [call['command'] for call in calls].count('group_start_at') == 1
    assert node._execution.execution_id == ''


# --------------------------------------------------------------------------- #
# 끊김 시험 I (2026-11-08 · 사용자 「마스터 재시작돼도 슬레이브는 계속 재생」)
# --------------------------------------------------------------------------- #

def _master_restarted(node, held=''):
    from test_coordination_node import _member
    node._registry.update(_member('pc-a', is_master=True, boot_id='boot-a-new', execution_id=held))


def test_a_restarted_master_without_the_run_lets_the_participant_continue():
    node, calls = _participant(phase='group_motion_completed', master_offline=False)
    _master_restarted(node)

    node._drive_autonomous_cycle()
    assert calls == [], '5 s 는 지켜본다'
    node._lost_run_watch['since'] -= 6.0
    node._drive_autonomous_cycle()

    [init] = calls
    assert init['command'] == 'group_initialize_at'
    assert node._autonomy['stage'] == 'initializing'


def test_a_master_that_already_started_a_new_run_is_waited_for():
    node, calls = _participant(phase='group_motion_completed', master_offline=False)
    _master_restarted(node, held='exec-new')

    node._drive_autonomous_cycle()
    node._lost_run_watch = {'key': ('pc-a', 'exec-a'), 'since': time.monotonic() - 60.0}
    node._drive_autonomous_cycle()

    assert calls == [], '새 실행이 경계에서 이 PC 를 넣는다'


def test_a_master_still_holding_the_run_is_followed_as_before():
    node, calls = _participant(phase='group_motion_completed', master_offline=False)
    _master_restarted(node, held='exec-a')

    node._drive_autonomous_cycle()

    assert calls == []


def _new_master_with_an_old_runner(*, remaining=40.0):
    from test_coordination_node import _member, _node, _Publisher
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._registry.update(_member('pc-b'))
    node._registry.update(_member(
        'pc-c', execution_id='exec-old', motion_phase='running',
        motion_duration_sec=900.0, motion_elapsed_sec=900.0 - remaining,
    ))
    node._local_alarm_grade = lambda: 0
    node._self_exclusion_reason = lambda: ''
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._begin_trigger_sync = lambda _action: None
    node._local_readiness = lambda: {'success': True}
    return node


def test_a_new_master_waits_for_the_old_runs_cycle_end_instead_of_leaving_it_out():
    node = _new_master_with_an_old_runner()

    result = node._start_group_execution(request={'started_by': 'schedule'})

    assert result['deferred'] is True and result['holders'] == ['pc-c']
    assert node._execution.execution_id == '', '아직 시작하지 않는다 · 마스터만 기다린다'
    assert node.snapshot()['aligned_start']['holders'] == ('pc-c',)
    again = node._start_group_execution(request={'started_by': 'schedule'})
    assert again['deferred'] is True, '스케줄이 다시 보내도 같은 답'


def test_the_aligned_start_goes_when_the_old_run_reaches_its_cycle_end(monkeypatch):
    import motion_coordination.coordination_node as coordination_node
    from test_coordination_node import _InlineThread, _member
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _new_master_with_an_old_runner()
    node._start_group_execution(request={'started_by': 'schedule'})

    node._drive_aligned_start()
    assert node._execution.execution_id == ''

    node._registry.update(_member(
        'pc-c', sequence=5, execution_id='exec-old', motion_phase='group_motion_completed',
        motion_duration_sec=900.0, motion_elapsed_sec=900.0,
    ))
    node._drive_aligned_start()

    assert node._execution.execution_id, '회차 끝 · 다 같이 시작'
    assert 'pc-c' in node._execution.participants
    assert node._aligned_start is None


def test_a_far_away_cycle_end_is_not_waited_for():
    node = _new_master_with_an_old_runner(remaining=5000.0)

    result = node._start_group_execution(request={'started_by': 'schedule'})

    assert not result.get('deferred')
    assert result['excluded']['pc-c'] == '단독 재생 중'


# --------------------------------------------------------------------------- #
# 끊김 시험 L · 잰 주기의 시계 오차가 스스로 잇는 회차마다 쌓이지 않게 · 10 s 배수로 붙인다
# --------------------------------------------------------------------------- #

def test_a_measured_period_snaps_to_the_ten_second_grid():
    from motion_coordination.cycle_grid import snap_period

    assert snap_period(930.037) == 930.0
    assert snap_period(929.96) == 930.0
    assert snap_period(933.0) == 933.0, '배수에서 1 s 넘게 벗어나면 잰 값 그대로'


def test_the_participant_learns_a_snapped_period():
    node, _calls = _participant(phase='running')
    start = node._grid_seen['start']
    node._grid_seen['cycle'] = 4

    node._observe_group_start('exec-a', 5, start + 930.042)

    assert node._grid_seen['period'] == 930.0
