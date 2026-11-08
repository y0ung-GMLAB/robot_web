"""Wi-Fi 가 잠깐 끊겨도 재생은 계속 · 돌아오면 회차 경계에서 다시 합침 · 수정 목록 183 (2026-11-08)

실물 NY 2026-11-07 15:08:15 · 공유기가 4대 Wi-Fi 를 약 112 s 끊음 · 마스터 floating1 이 하트비트 3 s 로
floating2·3·4 를 빼고 풀기(drop release)를 보냄 · 끊긴 동안 헤드는 계속 돌다가 망이 돌아온 순간 쌓인 풀기가
도착해 **재생 중인 헤드를 세움** · 그 뒤 다음 경계까지(920 s 애니 · 940 s 눈금) 쉼 · 마스터의 Wi-Fi 만
끊겨도 같음 · 마스터가 스스로 잇던 슬레이브 앞에 다시 보이면 슬레이브는 회차를 마치고 놓아 1회차 이상 쉼.

사용자 2026-11-08 「Wi-Fi 가 가끔 잠깐 끊겼다 금방 붙는다 · 그런 끊김과 상관없이 재생은 그냥 계속 ·
마스터의 다음 회차가 조금 더 기다리더라도 다 같이 시작」.
"""

import itertools
import time
from types import SimpleNamespace

from motion_coordination_interfaces.msg import GroupCommand, GroupEvent

import motion_coordination.coordination_node as coordination_node
from motion_coordination.group_execution import GroupExecution, MemberRegistry, drop_release_command_id
from test_coordination_node import _InlineThread, _member, _node, _Publisher
from test_group_rejoin import _commands, _event, _running_master


_SEQUENCE = itertools.count(10)


def _silent(node, pc_id='pc-c'):
    """그 PC 의 하트비트가 3 s 넘게 없다"""
    node._registry._members[pc_id] = _member(
        pc_id, sequence=next(_SEQUENCE), received_monotonic=time.monotonic() - 10.0,
    )


def _lost_master(*, cycle=3, participants=('pc-a', 'pc-b', 'pc-c')):
    """1회차 뒤 도는 회차 맞춤 연속 재생 · pc-c 의 하트비트가 끊겼다"""
    node = _running_master(cycle=cycle, participants=participants)
    node._note_excluded = lambda *args, **kwargs: None
    node._note_group = lambda *args, **kwargs: None
    _silent(node)
    return node


def _back(node, pc_id='pc-c', **overrides):
    """그 PC 가 다시 보인다 · 하트비트에 같은 실행 번호"""
    values = dict(execution_id=node._execution.execution_id, motion_phase='running')
    values.update(overrides)
    node._registry.update(_member(pc_id, sequence=next(_SEQUENCE), **values))


# --------------------------------------------------------------------------- #
# 진행 PC · 하트비트 끊김은 풀지 않는다
# --------------------------------------------------------------------------- #

def test_heartbeat_loss_sends_no_release_and_remembers_the_pc():
    node = _lost_master()

    node._enforce_execution_membership()

    assert node._execution.participants == ('pc-a', 'pc-b')
    assert _commands(node, 'cancel_before_start') == [], '풀기를 보내지 않는다 · 그 헤드는 계속 돈다'
    [update] = _commands(node, 'update_participants')
    assert update.participant_ids == ['pc-a', 'pc-b']
    assert 'pc-c' in node._execution.lost
    assert '연락 끊김' in node._execution.excluded['pc-c']
    assert 'pc-c' in node.snapshot()['execution']['lost']


def test_heartbeat_loss_before_the_first_cycle_still_releases():
    """1회차 전(준비 · 초기 위치)이면 그 PC 는 아직 돌지 않는다 · 전처럼 풀기"""
    node = _lost_master(cycle=0)
    node._execution.state = 'armed'

    node._enforce_execution_membership()

    assert node._execution.lost == {}
    [release] = _commands(node, 'cancel_before_start')
    assert release.participant_ids == ['pc-a', 'pc-c']


def test_other_drop_reasons_still_release(monkeypatch):
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _lost_master()
    _event(node, 'pc-b', 'error', success=False, message='모터 상태에 없음')

    [release] = _commands(node, 'cancel_before_start')
    assert release.participant_ids == ['pc-a', 'pc-b']
    assert 'pc-b' not in node._execution.lost


def test_the_lost_pc_is_not_waited_for_at_the_boundary():
    node = _lost_master()
    node._enforce_execution_membership()
    synced = []
    node._begin_trigger_sync = synced.append

    _event(node, 'pc-a', 'motion_completed')
    _event(node, 'pc-b', 'motion_completed')

    assert synced == ['cycle_initialize'], '끊긴 PC 는 장벽에서 기다리지 않는다'


# --------------------------------------------------------------------------- #
# 돌아오면 · 같은 실행이면 세우지 않고 다음 경계에서 합침
# --------------------------------------------------------------------------- #

def _merging(node):
    node._enforce_execution_membership()
    _back(node)
    node._manage_rejoiners()
    [join] = _commands(node, 'join')
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id='pc-c',
        event='join_accepted', success=True, state='merging',
        cycle_number=node._execution.cycle_number,
    ))
    return join


def test_a_returning_pc_holding_the_run_is_invited_to_merge_without_a_release():
    node = _lost_master()
    join = _merging(node)

    assert join.participant_ids == ['pc-a', 'pc-c']
    assert node._execution.joining['pc-c']['warm'] is True
    assert node._execution.joining['pc-c']['state'] == 'merging'
    # 회차 하나(920 s)가 걸려도 준비 제한시간(30 s)으로 접지 않는다
    node._execution.joining['pc-c']['since'] -= 600.0
    node._manage_rejoiners()
    assert 'pc-c' in node._execution.joining
    assert _commands(node, 'cancel_before_start') == []


def test_a_returning_pc_is_invited_even_between_cycles():
    node = _lost_master()
    node._enforce_execution_membership()
    node._execution.state = 'cycle_initializing'
    _back(node, motion_phase='group_motion_completed')

    node._manage_rejoiners()

    assert len(_commands(node, 'join')) == 1


def test_the_merged_pc_joins_at_the_next_boundary_with_the_masters_cycle_number():
    node = _lost_master(cycle=12)
    _merging(node)
    _event(node, 'pc-c', 'join_ready')
    synced = []
    node._begin_trigger_sync = synced.append

    _event(node, 'pc-a', 'motion_completed')
    _event(node, 'pc-b', 'motion_completed')

    [update] = _commands(node, 'update_participants')[-1:]
    assert update.participant_ids == ['pc-a', 'pc-b', 'pc-c']
    assert update.cycle_number == 12, '진행 PC 의 회차 번호가 이긴다'
    assert synced == ['cycle_initialize'], '시계 맞춤 · 회차 초기화 · 시작을 다 같이'
    action = node._execution.cycle_initialize_action(now=time.monotonic())
    assert action.cycle_number == 12
    assert 'pc-c' in node._execution.lost, '같이 시작할 때까지 기억'
    node._execution.state = 'start_scheduled'
    node._execution.cycle_number = 12
    _event_started = GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id='pc-c',
        event='motion_started', success=True, cycle_number=13,
        triggered_monotonic_ns=int(time.monotonic() * 1e9),
    )
    node._event_callback(_event_started)
    assert 'pc-c' not in node._execution.lost
    assert _commands(node, 'cancel_before_start') == []


def test_the_boundary_waits_a_little_for_a_returning_pc_then_starts_together():
    node = _lost_master()
    _merging(node)
    _back(node, motion_phase='running', motion_duration_sec=920.0, motion_elapsed_sec=916.0)
    synced = []
    node._begin_trigger_sync = synced.append

    _event(node, 'pc-a', 'motion_completed')
    _event(node, 'pc-b', 'motion_completed')
    assert synced == [], '그 PC 의 회차 끝이 4 s 뒤 · 경계를 잠깐 미룬다'
    node._drive_merge_hold()
    assert synced == []

    _event(node, 'pc-c', 'join_ready')
    node._drive_merge_hold()

    assert synced == ['cycle_initialize']
    assert set(node._execution.participants) == {'pc-a', 'pc-b', 'pc-c'}


def test_the_wait_is_bounded_and_the_pc_joins_one_boundary_later():
    node = _lost_master()
    _merging(node)
    _back(node, motion_phase='running', motion_duration_sec=920.0, motion_elapsed_sec=912.0)
    synced = []
    node._begin_trigger_sync = synced.append
    _event(node, 'pc-a', 'motion_completed')
    _event(node, 'pc-b', 'motion_completed')
    assert synced == []

    node._merge_hold['until'] = time.monotonic() - 0.1     # 한도(초기 이동 + 여유)가 지났다
    node._drive_merge_hold()

    assert synced == ['cycle_initialize']
    assert node._execution.participants == ('pc-a', 'pc-b')
    assert node._execution.joining['pc-c']['state'] == 'merging', '다음 경계에 다시'


def test_no_wait_when_the_returning_pc_is_far_from_its_cycle_end():
    node = _lost_master()
    _merging(node)
    _back(node, motion_phase='running', motion_duration_sec=920.0, motion_elapsed_sec=100.0)
    synced = []
    node._begin_trigger_sync = synced.append

    _event(node, 'pc-a', 'motion_completed')
    _event(node, 'pc-b', 'motion_completed')

    assert synced == ['cycle_initialize']


def test_a_merge_refusal_keeps_the_pc_playing():
    node = _lost_master()
    _merging(node)
    _event(node, 'pc-c', 'join_ready')
    node._begin_trigger_sync = lambda _action: None
    _event(node, 'pc-a', 'motion_completed')
    _event(node, 'pc-b', 'motion_completed')
    assert 'pc-c' in node._execution.participants

    _event(node, 'pc-c', 'rejected', success=False, message='회차 끝 장벽에 서 있지 않아')

    assert 'pc-c' not in node._execution.participants
    assert _commands(node, 'cancel_before_start') == [], '스스로 다음 회차를 잡았을 수 있다 · 풀지 않는다'
    assert 'pc-c' in node._execution.lost


def test_a_merging_pc_that_goes_away_again_is_not_released():
    node = _lost_master()
    _merging(node)
    _silent(node)

    node._manage_rejoiners()

    assert 'pc-c' not in node._execution.joining
    assert _commands(node, 'cancel_before_start') == []


def test_real_stops_still_reach_the_lost_pc():
    node = _lost_master()
    node._enforce_execution_membership()
    node._safety_stop = SimpleNamespace(
        stop_now=lambda local, publish: (publish(), SimpleNamespace(local_result={'success': True}))[1],
    )

    node._issue_stop_now(
        execution_id=node._execution.execution_id,
        participants=node._execution.participants, cycle_number=3,
    )

    [stop] = _commands(node, 'stop_now')
    assert stop.participant_ids == ['pc-a', 'pc-b', 'pc-c']


def test_ending_the_run_releases_the_lost_pc():
    node = _lost_master()
    node._enforce_execution_membership()
    node._execution.stop_now()

    node._clear_active_execution()

    [release] = _commands(node, 'cancel_before_start')
    assert release.participant_ids == ['pc-a', 'pc-c']


# --------------------------------------------------------------------------- #
# 참가 PC · 그대로 재생하며 합류
# --------------------------------------------------------------------------- #

def _playing_slave(*, phase='running', cycle=5):
    node = _node()
    node._config = SimpleNamespace(**{**vars(node._config), 'pc_id': 'pc-c'})
    node._joined = True
    node._event_pub = _Publisher()
    node._command_pub = _Publisher()
    node._registry.update(_member('pc-a', is_master=True))
    node._execution = GroupExecution()
    node._execution.activate_claim('exec-a', 'pc-a', ('pc-a', 'pc-b', 'pc-c'))
    node._execution.run_mode = 'continuous'
    node._execution.sync_mode = 'lockstep'
    node._local_status = {
        'operation_mode': 'schedule',
        'motion_run_status': {
            'group_execution': True, 'execution_id': 'exec-a', 'state': 'running',
            'phase': phase, 'current_cycle': cycle,
        },
    }
    node._last_local_event_key = ()
    calls = []
    node._call_local_control = lambda payload, **_kwargs: calls.append(dict(payload)) or {'success': True}
    node._local_readiness = lambda: {'success': True}
    return node, calls


def _join(cycle=12):
    return GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='join', command_id=f'cmd-join-{cycle}', cycle_number=cycle,
        participant_ids=['pc-a', 'pc-c'], run_mode='continuous', sync_mode='lockstep',
    )


def _update(cycle=12):
    return GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='update_participants', command_id='cmd-update', cycle_number=cycle,
        participant_ids=['pc-a', 'pc-b', 'pc-c'],
    )


def test_a_playing_slave_merges_without_a_new_plan():
    node, calls = _playing_slave()

    node._process_group_command(_join())

    assert calls == [], '계획을 새로 짓지 않는다(group_join 없음) · 재생을 세우지 않는다'
    assert node._execution.merging is True
    [accepted] = node._event_pub.messages
    assert accepted.event == 'join_accepted' and accepted.state == 'merging'


def test_a_merging_slave_reports_join_ready_at_its_cycle_end():
    node, _calls = _playing_slave()
    node._process_group_command(_join())
    node._local_status['motion_run_status'].update(phase='group_motion_completed', state='motion_completed')

    node._emit_local_runtime_event()

    assert node._event_pub.messages[-1].event == 'join_ready'


def test_the_merge_commit_takes_the_masters_cycle_number():
    node, calls = _playing_slave()
    node._process_group_command(_join())
    node._autonomy = {'execution_id': 'exec-a', 'stage': 'started'}

    node._process_group_command(_update(cycle=12))

    [commit] = calls
    assert commit == {
        'command': 'group_join_commit', 'execution_id': 'exec-a', 'cycle_number': 12,
        'network_operation_id': 'cmd-update', 'merge': True,
    }
    assert node._execution.participants == ('pc-a', 'pc-b', 'pc-c')
    assert node._execution.merging is False and node._execution.join_cycle == 0
    assert node._autonomy is None


def test_a_stopped_slave_still_rejoins_with_a_new_plan():
    """그 실행을 이미 놓은 PC 는 전처럼 계획을 새로 짓는 복귀(30-3)"""
    node, calls = _playing_slave()
    node._local_status['motion_run_status'].update(state='stopped', phase='stopped')

    node._process_group_command(_join())

    assert calls[-1]['command'] == 'group_join'
    assert node._execution.merging is False


def test_a_real_release_still_stops_a_merging_slave():
    node, _calls = _playing_slave()
    node._process_group_command(_join())
    node._command_dispatcher = SimpleNamespace(submit=lambda message, urgent_stop=False: True)
    stop = GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='stop_now', command_id='cmd-stop', participant_ids=['pc-a', 'pc-b', 'pc-c'],
    )

    node._command_callback(stop)

    assert 'exec-a' in node._cancelled_execution_ids
    assert 'exec-a' not in node._drop_released()


def test_a_slave_waiting_at_the_barrier_too_long_falls_back_to_leaving(monkeypatch):
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node, calls = _playing_slave(phase='group_motion_completed')
    node._registry = MemberRegistry()
    node._registry.update(_member('pc-a', is_master=True))

    node._enforce_barrier_wait()
    assert node._execution.execution_id == 'exec-a'
    node._barrier_wait['since'] -= 10_000.0
    node._enforce_barrier_wait()

    assert node._execution.execution_id == ''
    assert 'exec-a' in node._drop_released(), '그 뒤 진행 PC 의 복귀 권유는 받는다(181)'
    assert calls[-1]['command'] == 'stop_now'


def test_a_slave_does_not_time_out_while_the_master_commands_it():
    node, _calls = _playing_slave(phase='group_motion_completed')
    node._enforce_barrier_wait()
    since = node._barrier_wait['since']
    node._local_status['motion_run_status']['phase'] = 'group_cycle_initialized'

    node._enforce_barrier_wait()

    assert node._barrier_wait is None
    assert node._execution.execution_id == 'exec-a'
    assert since > 0


def test_a_drop_release_id_is_still_a_release_for_181():
    """하트비트 끊김 밖의 이유로 뺀 PC 에는 전처럼 풀기 · 181 의 `join` 받기도 그대로"""
    node, _calls = _playing_slave()
    node._command_dispatcher = SimpleNamespace(submit=lambda message, urgent_stop=False: True)
    node._local_group_execution_id = lambda: 'exec-a'
    release = GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='cancel_before_start', command_id=drop_release_command_id(),
        participant_ids=['pc-a', 'pc-c'],
    )

    node._command_callback(release)

    assert 'exec-a' in node._cancelled_execution_ids
    assert 'exec-a' in node._drop_released()
