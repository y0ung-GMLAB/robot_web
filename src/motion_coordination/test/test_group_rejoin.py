"""도는 그룹에 복귀 · 수정 목록 30-3 (2026-10-06)

빠졌던 PC 가 돌아오면 · 진행 PC 가 `join` → 그 PC 는 계획만 만들고 `join_ready` →
지금 회차가 끝나 회차 초기화로 갈 때 참가 목록에 넣고(`update_participants`) 같이
초기 위치 → 다음 회차부터 같이 · 복귀 PC 의 실패는 도는 그룹을 멈추지 않는다.
"""

import time

from motion_coordination_interfaces.msg import GroupCommand, GroupEvent

from motion_coordination.group_execution import GROUP_PROTOCOL_VERSION, GroupExecution
from test_coordination_node import _member, _node, _Publisher


def _running_master(*, cycle=3, participants=('pc-a', 'pc-b'), **execution):
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._execution = GroupExecution()
    node._execution.begin('pc-a', participants, run_mode='continuous', repeat_mode='reinitialize')
    node._execution.state = 'running'
    node._execution.cycle_number = cycle
    for key, value in execution.items():
        setattr(node._execution, key, value)
    for pc_id in participants:
        if pc_id != 'pc-a':
            node._registry.update(_member(pc_id))
    return node


def _event(node, pc_id, event, *, success=True, message=''):
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id=pc_id,
        event=event, success=success, message=message,
        cycle_number=node._execution.cycle_number,
    ))


def _commands(node, name):
    return [message for message in node._command_pub.messages if message.command == name]


def test_returning_pc_is_invited_to_prepare_without_moving():
    node = _running_master()
    node._registry.update(_member('pc-c'))   # 돌아왔다

    node._manage_rejoiners()

    [join] = _commands(node, 'join')
    assert join.participant_ids == ['pc-a', 'pc-c']
    assert join.cycle_number == 3
    assert join.sync_mode == 'lockstep' and join.run_mode == 'continuous'
    assert node._execution.joining == {'pc-c': {'state': 'preparing', 'since': node._execution.joining['pc-c']['since']}}
    assert node._execution.participants == ('pc-a', 'pc-b')   # 아직 안 넣는다
    node._manage_rejoiners()
    assert len(_commands(node, 'join')) == 1                   # 두 번 부르지 않는다
    assert node.snapshot()['execution']['joining'] == {'pc-c': 'preparing'}


def test_no_invite_when_the_run_cannot_take_a_new_pc():
    for overrides in (
        {'sync_mode': 'independent'}, {'stop_after_cycle': True},
        {'state': 'cycle_initializing'}, {'initialization_only': True},
        {'target_cycle_count': 3},
    ):
        node = _running_master(**overrides)
        node._registry.update(_member('pc-c'))
        node._manage_rejoiners()
        assert _commands(node, 'join') == [], overrides
    node = _running_master()
    node._registry.update(_member('pc-c', operation_mode='manual'))
    node._registry.update(_member('pc-d', protocol_version=GROUP_PROTOCOL_VERSION - 1))
    node._manage_rejoiners()
    assert _commands(node, 'join') == []


def test_ready_joiner_is_admitted_at_the_cycle_boundary_and_initializes_with_everyone():
    node = _running_master()
    node._registry.update(_member('pc-c'))
    node._execution.excluded = {'pc-c': '통신 단절'}
    node._manage_rejoiners()
    _event(node, 'pc-c', 'join_ready')
    assert node._execution.joining['pc-c']['state'] == 'ready'

    # 지금 회차가 끝났다 · 원래 두 대만 완료를 보낸다
    synced = []
    node._begin_trigger_sync = synced.append
    node._note_group = lambda *args, **kwargs: None
    _event(node, 'pc-a', 'motion_completed')
    _event(node, 'pc-b', 'motion_completed')

    [update] = _commands(node, 'update_participants')
    assert update.participant_ids == ['pc-a', 'pc-b', 'pc-c']
    assert update.cycle_number == 3
    assert node._execution.participants == ('pc-a', 'pc-b', 'pc-c')
    assert node._execution.joining == {}
    assert 'pc-c' not in node._execution.excluded
    assert synced == ['cycle_initialize']
    # 회차 초기화 장벽이 넣은 PC 까지 보고 바로 넘어간다
    action = node._execution.cycle_initialize_action(now=time.monotonic())
    assert action.command == 'cycle_initialize_at' and action.cycle_number == 3


def test_a_joiner_that_fails_is_dropped_without_stopping_the_group():
    node = _running_master()
    node._registry.update(_member('pc-c'))
    node._note_excluded = lambda *args, **kwargs: None
    node._manage_rejoiners()

    _event(node, 'pc-c', 'rejected', success=False, message='수동 모드')

    assert node._execution.state == 'running'
    assert node._execution.joining == {}
    assert node._execution.excluded['pc-c'] == '복귀 실패 · 수동 모드'
    [cancel] = _commands(node, 'cancel_before_start')
    assert cancel.participant_ids == ['pc-a', 'pc-c']
    # 접은 뒤 그 PC 의 늦은 「정지」 는 그룹에 영향이 없다
    _event(node, 'pc-c', 'stopped')
    assert node._execution.state == 'running'
    # 30초 안에는 다시 권하지 않는다
    node._manage_rejoiners()
    assert len(_commands(node, 'join')) == 1


def test_a_joiner_that_never_answers_is_dropped():
    node = _running_master()
    node._registry.update(_member('pc-c'))
    node._note_excluded = lambda *args, **kwargs: None
    node._manage_rejoiners()
    node._execution.joining['pc-c']['since'] = time.monotonic() - node.JOIN_PREPARE_TIMEOUT_SEC - 1.0

    node._manage_rejoiners()

    assert node._execution.joining == {}
    assert node._execution.excluded['pc-c'] == '복귀 준비 응답 없음'
    assert node._execution.state == 'running'


def test_admitted_joiner_refusing_the_commit_is_left_out_and_the_barrier_moves_on():
    node = _running_master(participants=('pc-a', 'pc-b', 'pc-c'))
    node._execution.admitted = {'pc-c'}
    node._execution.state = 'cycle_initializing'
    node._execution.cycle_initialized = {'pc-a', 'pc-b'}
    node._note_excluded = lambda *args, **kwargs: None
    started = []
    node._publish_next_start = lambda: started.append(True)

    _event(node, 'pc-c', 'rejected', success=False, message='복귀 준비가 끝나지 않아')

    assert node._execution.participants == ('pc-a', 'pc-b')
    assert node._execution.state == 'cycle_ready'
    assert started == [True]


def test_ending_the_run_releases_pcs_still_preparing_to_join():
    node = _running_master()
    node._registry.update(_member('pc-c'))
    node._manage_rejoiners()
    node._command_pub.messages.clear()

    node._clear_active_execution()

    [cancel] = _commands(node, 'cancel_before_start')
    assert cancel.participant_ids == ['pc-a', 'pc-c']
    assert node._execution.joining == {}


# --------------------------------------------------------------------------- #
# 복귀하는 쪽 PC
# --------------------------------------------------------------------------- #

def _joiner():
    node = _node()
    node._config.pc_id = 'pc-c'
    node._config.is_master = False
    node._joined = True
    node._event_pub = _Publisher()
    node._command_pub = _Publisher()
    node._registry.update(_member('pc-a', is_master=True))
    node._local_readiness = lambda: {'success': True}
    return node


def _join_command(cycle=3):
    return GroupCommand(
        group_id='stage-a', execution_id='exec-a', command_id='cmd-join', coordinator_id='pc-a',
        command='join', participant_ids=['pc-a', 'pc-c'], cycle_number=cycle,
        repeat_mode='reinitialize', run_mode='continuous', sync_mode='lockstep',
    )


def test_joiner_prepares_a_plan_and_waits_for_the_commit():
    node = _joiner()
    calls = []
    node._call_local_control = lambda payload, **_kwargs: calls.append(dict(payload)) or {'success': True}

    node._process_group_command(_join_command())

    [prepare] = calls
    assert prepare['command'] == 'group_join'
    assert prepare['join_cycle_number'] == 3
    assert 'initialize_monotonic' not in prepare
    assert node._execution.execution_id == 'exec-a'
    assert node._execution.join_cycle == 3
    assert [message.event for message in node._event_pub.messages] == ['join_accepted']

    # 진행 PC 가 넣었다 · 합류 확정 → 참가 목록 갱신
    node._process_group_command(GroupCommand(
        group_id='stage-a', execution_id='exec-a', command_id='cmd-update', coordinator_id='pc-a',
        command='update_participants', participant_ids=['pc-a', 'pc-b', 'pc-c'], cycle_number=3,
    ))
    assert calls[-1] == {
        'command': 'group_join_commit', 'execution_id': 'exec-a', 'cycle_number': 3,
        'network_operation_id': 'cmd-update',
    }
    assert node._execution.participants == ('pc-a', 'pc-b', 'pc-c')
    assert node._execution.join_cycle == 0


def test_joiner_that_cannot_run_refuses_and_lets_go():
    node = _joiner()
    node._local_readiness = lambda: {'success': False, 'message': '수동 모드'}
    node._call_local_control = lambda payload, **_kwargs: {'success': True}

    node._process_group_command(_join_command())

    [event] = node._event_pub.messages
    assert (event.event, event.success, event.message) == ('rejected', False, '수동 모드')
    assert node._execution.execution_id == ''


def test_joiner_reports_join_ready_when_its_plan_is_built():
    node = _joiner()
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._process_group_command(_join_command())
    node._event_pub.messages.clear()
    node._last_local_event_key = None
    node._local_status = {'motion_run_status': {
        'group_execution': True, 'execution_id': 'exec-a',
        'phase': 'group_join_ready', 'group_cycle_number': 3,
    }}

    node._emit_local_runtime_event()

    [event] = node._event_pub.messages
    assert event.event == 'join_ready' and event.success is True
