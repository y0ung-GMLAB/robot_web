"""바쁜 마스터 · 늦은 거절 · 남의 실행 정지 · 노드에 붙여서 · 수정 목록 136 (실물 V-4 · V-5 · V-8)

규칙만 보는 시험은 `test_busy_master_rules.py` (rclpy 없이).
"""

from types import SimpleNamespace

import pytest
from motion_coordination_interfaces.msg import GroupCommand, GroupEvent, GroupHeartbeat

from motion_coordination.group_execution import GroupExecution
from test_coordination_node import _member, _node, _Publisher


def _master(*, local=None, peers=('pc-b',)):
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._note_excluded = lambda *args, **kwargs: None
    node._local_status = dict(local or {})
    node._system_info_cache = {}
    for pc_id in peers:
        node._registry.update(_member(pc_id, operation_mode='manual'))
    return node


def _local_calls(node):
    calls = []
    node._call_local_control = lambda payload, **_kwargs: (
        calls.append(dict(payload)) or {'success': True}
    )
    return calls


SOLO = {'motion_run_status': {'state': 'running', 'phase': 'running'}}
JOG = {'motion_run_status': {'state': 'idle'}, 'safety_status': {'manual_activity_modes': ['jog']}}


# ① 바쁜 마스터는 빠지고 진행만 ---------------------------------------------------------- #

def test_a_master_running_solo_sits_out_and_the_others_run():
    """V-4 · 전에는 「참가 4대 · excluded {}」 → 제 준비 답으로 시작 취소"""
    node = _master(local=SOLO)

    result = node._start_group_execution(request={'started_by': 'human'})

    assert result['participants'] == ['pc-b']
    assert result['excluded'] == {'pc-a': '단독 재생 중'}
    [prepare] = node._command_pub.messages
    assert prepare.command == 'prepare'
    assert prepare.coordinator_id == 'pc-a'
    assert list(prepare.participant_ids) == ['pc-b']
    assert node._execution.coordinator_id == 'pc-a'
    # 진행 PC 는 제 준비 명령을 받지 않는다(참가 목록 밖)
    submitted = []
    node._command_dispatcher = SimpleNamespace(
        submit=lambda message, urgent_stop=False: submitted.append(message.command) or True,
    )
    node._command_callback(prepare)
    assert submitted == []


def test_a_jogging_master_alone_is_refused_up_front_without_a_latch():
    """V-5 · 들어갈 PC 가 없으면 시작 전에 거절 · 취소 · 정지 · 잠금 없음"""
    node = _master(local=JOG, peers=())
    calls = _local_calls(node)

    with pytest.raises(ValueError, match='들어갈 PC 가 없습니다'):
        node._start_group_execution(request={'started_by': 'human'})

    assert calls == []
    assert node._command_pub.messages == []
    assert node._execution.execution_id == ''
    assert node._coordination_error == {}
    failure = node.snapshot()['last_start_failure']
    assert failure['code'] == 'GROUP_START_NOT_READY'
    assert 'pc-a(사람 조작 중 · 조그 이동)' in failure['message']


def test_the_local_request_answers_the_refusal_instead_of_raising():
    node = _master(local=JOG, peers=())

    result = node._handle_local_request({'command': 'start_group', 'started_by': 'human'})

    assert result['success'] is False
    assert '사람 조작 중 · 조그 이동' in result['message']


def test_the_play_screen_preview_shows_the_busy_master():
    node = _master(local=SOLO)

    preview = node.snapshot()['start_preview']

    assert preview == {'participants': ['pc-b'], 'excluded': {'pc-a': '단독 재생 중'}}


def test_a_master_whose_own_prepare_is_refused_drops_itself_and_the_others_go_on():
    """조그를 선택 뒤 0.5 s 안에 시작한 경우 · 제 준비 답에서 보인다 · 이제 취소 대신 빠진다"""
    node = _master()
    calls = _local_calls(node)
    node._execution = GroupExecution()
    execution_id = node._execution.begin('pc-a', ('pc-a', 'pc-b'))
    node._execution.pending_command = 'prepare'
    node._execution.pending_command_id = 'cmd-prepare'
    node._execution.prepare_command_id = 'cmd-prepare'
    node._execution.ready = {'pc-b'}
    node._execution.pending_acks = {'pc-b'}
    synced = []
    node._begin_trigger_sync = synced.append

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-a', command_id='cmd-prepare',
        event='rejected', success=False, message='사람 조작 중 · 조그 이동',
    ))

    assert node._execution.execution_id == execution_id
    assert node._execution.participants == ('pc-b',)
    assert node._execution.excluded['pc-a'].endswith('사람 조작 중 · 조그 이동')
    [update] = [m for m in node._command_pub.messages if m.command == 'update_participants']
    assert list(update.participant_ids) == ['pc-b']
    assert [m for m in node._command_pub.messages if m.command in {'cancel_before_start', 'stop_now'}] == []
    assert [c for c in calls if c['command'] != 'group_note'] == []
    assert node._coordination_error == {}
    assert synced == ['initialize']


def test_a_master_alone_whose_prepare_is_refused_still_cancels_without_latching():
    node = _master(peers=())
    _local_calls(node)
    node._execution = GroupExecution()
    execution_id = node._execution.begin('pc-a', ('pc-a',))

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-a',
        event='rejected', success=False, message='실행 준비 검사 실패: 앱솔루트 미확인',
    ))

    assert node._execution.execution_id == ''
    assert node._coordination_error == {}
    assert node.snapshot()['last_start_failure']['code'] == 'GROUP_START_NOT_READY'


def test_when_every_participant_drops_the_sitting_out_master_lets_go_quietly():
    node = _master()
    _local_calls(node)
    node._execution = GroupExecution()
    execution_id = node._execution.begin('pc-a', ('pc-b',), coordinator_participates=False)
    node._execution.pending_command = 'prepare'
    node._execution.pending_command_id = 'cmd-prepare'
    node._execution.prepare_command_id = 'cmd-prepare'

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-b', command_id='cmd-prepare',
        event='rejected', success=False, message='모터 설정과 조인트 매핑을 저장해 확정하세요',
    ))

    assert node._execution.execution_id == ''
    assert node._coordination_error == {}
    releases = [m for m in node._command_pub.messages if m.command == 'cancel_before_start']
    assert [list(m.participant_ids) for m in releases] == [['pc-a', 'pc-b']]
    assert [m for m in node._command_pub.messages if m.command == 'stop_now'] == []
    assert '들어갈 PC 가 남지 않음' in node.snapshot()['last_start_failure']['message']


def test_trigger_sync_waits_for_every_participant_when_the_master_sits_out():
    node = _master(peers=('pc-b', 'pc-c'))
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-b', 'pc-c'), coordinator_participates=False)
    node._execution.ready = {'pc-b', 'pc-c'}
    published = []
    node._publish_action = published.append

    node._begin_trigger_sync('initialize')
    assert published == [], '진행 PC 하나만 맞췄다고 넘어가면 안 된다'
    node._sync_ready.update({'pc-b'})
    node._complete_trigger_sync_if_ready()
    assert published == []
    node._sync_ready.update({'pc-c'})
    node._complete_trigger_sync_if_ready()
    assert [action.command for action in published] == ['initialize_at']


# ② 남의 실행 정지는 이 PC 를 세우지 않는다 ------------------------------------------------- #

def _sitting_out_master(state='running'):
    node = _master(local=SOLO, peers=('pc-b', 'pc-c'))
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-b', 'pc-c'), coordinator_participates=False)
    node._execution.state = state
    return node


def test_a_group_failure_stops_the_participants_but_not_the_sitting_out_master():
    """V-4 · 전에는 마스터에도 즉시 정지 → 단독 재생이 섰다"""
    node = _sitting_out_master()
    calls = _local_calls(node)

    node._stop_for_peer_failure('pc-b 그룹 명령 실패')

    assert [c['command'] for c in calls] == []
    [stop] = [m for m in node._command_pub.messages if m.command == 'stop_now']
    assert list(stop.participant_ids) == ['pc-b', 'pc-c']
    assert stop.execution_id


def test_a_human_group_stop_on_the_sitting_out_master_leaves_its_solo_run():
    node = _sitting_out_master()
    calls = _local_calls(node)

    result = node._request_group_stop(after_cycle=False)

    assert result['success'] is True
    assert calls == []
    assert [m.command for m in node._command_pub.messages] == ['stop_now']


def test_stop_after_cycle_on_the_sitting_out_master_leaves_its_solo_run():
    node = _sitting_out_master()
    calls = _local_calls(node)

    node._request_group_stop(after_cycle=True)

    assert calls == []
    assert [m.command for m in node._command_pub.messages] == ['stop_after_cycle']


def test_cancelling_with_one_remote_participant_still_releases_it():
    """참가 PC 가 1대뿐이어도(마스터는 밖) 풀기 장벽을 돈다 · 전에는 `len > 1` 이라 안 풀렸다"""
    node = _sitting_out_master(state='preparing')
    node._execution.exclude({'pc-c': 'x'})
    calls = _local_calls(node)

    node._cancel_before_start('취소', code='GROUP_START_REJECTED', latch=False)

    assert [c['command'] for c in calls] == []
    [release] = [m for m in node._command_pub.messages if m.command == 'cancel_before_start']
    assert list(release.participant_ids) == ['pc-b']
    assert node._execution.state == 'releasing'


def test_a_participant_still_stops_itself_as_before():
    node = _master()
    calls = _local_calls(node)
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a', 'pc-b'))

    node._stop_for_peer_failure('pc-b 그룹 명령 실패')

    assert [c['command'] for c in calls] == ['stop_now']
    assert calls[0]['execution_id']


def test_the_sitting_out_masters_own_alarm_does_not_stop_the_group():
    node = _sitting_out_master()
    calls = _local_calls(node)
    node._last_alarm_key = ()
    node._local_status = {**SOLO, 'safety_status': {'servo_alarm_grade': 2, 'servo_alarm_active': []}}

    node._publish_local_alarm_if_changed()

    assert calls == []
    assert [m for m in node._command_pub.messages if m.command == 'stop_now'] == []
    assert node._execution.execution_id


# ③ 늦은 거절은 그 PC 만 · V-4 · V-8 -------------------------------------------------------- #

def test_a_late_prepare_refusal_while_releasing_does_not_stop_everyone():
    """V-4 · 마스터 취소(정리 중) 뒤 floating2 의 늦은 준비 거절 → 전에는 전체 정지 + 그룹 오류"""
    node = _master(peers=('pc-b', 'pc-c'))
    calls = _local_calls(node)
    node._execution = GroupExecution()
    execution_id = node._execution.begin('pc-a', ('pc-a', 'pc-b', 'pc-c'))
    node._execution.prepare_command_id = 'cmd-prepare'
    node._cancel_before_start('pc-x 실행 준비 안 됨', code='GROUP_START_NOT_READY', latch=False)
    assert node._execution.state == 'releasing'
    calls.clear()

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-b', command_id='cmd-prepare',
        event='rejected', success=False, message='모터 설정과 조인트 매핑을 저장해 확정하세요',
    ))

    assert calls == []
    assert [m for m in node._command_pub.messages if m.command == 'stop_now'] == []
    assert node._coordination_error == {}
    assert node._execution.state == 'releasing'


def test_the_master_never_handles_its_own_join_invitation():
    """V-8 · 마스터가 제 `join` 을 처리해 참가 목록이 {마스터, floating1} 로 덮였다"""
    node = _master(peers=('pc-b', 'pc-c'))
    _local_calls(node)
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a',), run_mode='continuous', started_by='human')
    node._execution.state = 'running'
    node._execution.cycle_number = 1
    submitted = []
    node._command_dispatcher = SimpleNamespace(
        submit=lambda message, urgent_stop=False: submitted.append(message.command) or True,
    )

    node._manage_rejoiners()
    joins = [m for m in node._command_pub.messages if m.command == 'join']
    assert len(joins) == 2
    for join in joins:
        node._command_callback(join)

    assert submitted == []
    assert node._execution.participants == ('pc-a',)


def test_a_join_refusal_during_a_run_drops_only_that_pc():
    node = _master(peers=('pc-b',))
    _local_calls(node)
    node._execution = GroupExecution()
    execution_id = node._execution.begin('pc-a', ('pc-a',), run_mode='continuous', started_by='human')
    node._execution.state = 'running'
    node._execution.cycle_number = 1
    node._manage_rejoiners()
    [join] = [m for m in node._command_pub.messages if m.command == 'join']

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-b', command_id=join.command_id,
        event='rejected', success=False, message='모터 설정과 조인트 매핑을 저장해 확정하세요',
    ))

    assert node._execution.execution_id == execution_id
    assert node._execution.state == 'running'
    assert node._execution.participants == ('pc-a',)
    assert node._coordination_error == {}
    assert [m for m in node._command_pub.messages if m.command == 'stop_now'] == []


def test_a_pc_that_already_let_go_answers_the_release_with_stopped():
    """준비를 거절하고 놓은 PC 가 풀기를 받는다 · 전에는 「거절」 → 진행 PC 가 전체 정지"""
    node = _node()
    node._config.pc_id = 'pc-b'
    node._joined = True
    node._event_pub = _Publisher()
    node._registry.update(_member('pc-a', is_master=True))
    node._execution.clear_active()

    node._process_group_command(GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='cancel_before_start', command_id='cmd-release',
        participant_ids=['pc-a', 'pc-b'],
    ))

    [event] = node._event_pub.messages
    assert event.event == 'stopped' and event.success is True
    assert event.command_id == 'cmd-release'


# 참가 PC 쪽 · 참가 목록 밖 진행 PC(마스터)를 받는다 ----------------------------------------- #

def test_a_slave_accepts_a_prepare_from_a_master_outside_the_roster():
    node = _node()
    node._config.pc_id = 'pc-b'
    node._registry.update(_member('pc-a', is_master=True))
    command = GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='prepare', participant_ids=['pc-b', 'pc-c'],
    )

    node._accept_execution_claim(command, ('pc-b', 'pc-c'))

    assert node._execution.coordinator_id == 'pc-a'
    assert node._execution.participants == ('pc-b', 'pc-c')
    # 그 마스터의 정지도 받는다
    stop = GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='stop_now', participant_ids=['pc-b', 'pc-c'],
    )
    node._require_stop_command(stop, ('pc-b', 'pc-c'))


def test_a_slave_still_refuses_an_unknown_non_master_outside_the_roster():
    node = _node()
    node._config.pc_id = 'pc-b'
    node._registry.update(_member('pc-x', is_master=False))
    command = GroupCommand(
        group_id='stage-a', execution_id='exec-x', coordinator_id='pc-x',
        command='prepare', participant_ids=['pc-b', 'pc-c'],
    )
    with pytest.raises(ValueError, match='참가 목록'):
        node._accept_execution_claim(command, ('pc-b', 'pc-c'))


# ⑤ 하트비트 ---------------------------------------------------------------------------- #

def test_the_heartbeat_carries_why_this_pc_cannot_start():
    node = _node()
    node._joined = True
    node._heartbeat_pub = _Publisher()
    node._local_status = {
        'start_blocker': '실행 준비 안 됨 · 모터 설정과 조인트 매핑을 저장해 확정하세요',
    }

    node._heartbeat_tick()

    [message] = node._heartbeat_pub.messages
    assert message.start_blocker == '실행 준비 안 됨 · 모터 설정과 조인트 매핑을 저장해 확정하세요'


def test_a_peer_heartbeat_blocker_leaves_it_out_of_the_next_start():
    node = _master(peers=())
    node._heartbeat_callback(GroupHeartbeat(
        group_id='stage-a', pc_id='pc-b', boot_id='boot-b', joined=True, sequence=1,
        protocol_version=node_protocol(), operation_mode='manual',
        start_blocker='실행 준비 안 됨 · 모터 설정과 조인트 매핑을 저장해 확정하세요',
    ))
    node._registry.update(_member('pc-c', operation_mode='manual'))

    result = node._start_group_execution(request={'started_by': 'human'})

    assert result['participants'] == ['pc-a', 'pc-c']
    assert result['excluded'] == {
        'pc-b': '실행 준비 안 됨 · 모터 설정과 조인트 매핑을 저장해 확정하세요',
    }


def node_protocol():
    from motion_coordination.group_execution import GROUP_PROTOCOL_VERSION
    return GROUP_PROTOCOL_VERSION
