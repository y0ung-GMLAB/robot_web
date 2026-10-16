"""그룹 구간 재생 · 진행 PC 의 시작이 구간을 모든 PC · 스피커에 싣는다 · 약속 번호 10 (2026-10-16)

PC 마다 제 재생 목록 1번을 같은 시각으로 자른다 · 1번이 구간 시작보다 짧은 PC 는 준비 검사에서
거절 → 다른 준비 거절처럼 그 PC 만 빠진다 · 스케줄이 켠 그룹은 늘 통째로.
"""

import time
from types import SimpleNamespace

import pytest
from motion_coordination_interfaces.msg import GroupCommand

from motion_coordination import coordination_node
from motion_coordination.group_execution import GROUP_PROTOCOL_VERSION, GroupExecution
from test_coordination_node import _member, _node, _Publisher


def _master(*peers):
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    for pc_id in peers or ('pc-b',):
        node._registry.update(_member(pc_id))
    return node


def test_protocol_version_is_10_with_the_new_fields():
    assert GROUP_PROTOCOL_VERSION == 10
    message = GroupCommand()
    assert (message.segment_start_sec, message.segment_end_sec) == (0.0, 0.0)


def test_every_command_fills_the_segment_fields_and_defaults_to_whole():
    node = _node()
    whole = node._new_command(command='stop_now', execution_id='e', cycle_number=0, participants=('pc-a',))
    assert (whole.segment_start_sec, whole.segment_end_sec) == (0.0, 0.0)
    cut = node._new_command(
        command='prepare', execution_id='e', cycle_number=0, participants=('pc-a',),
        segment_start_sec=80.0, segment_end_sec=105.0,
    )
    assert (cut.segment_start_sec, cut.segment_end_sec) == (80.0, 105.0)


def test_received_segment_tolerates_old_and_broken_commands():
    read = coordination_node._message_segment
    assert read(SimpleNamespace(segment_start_sec=80.0, segment_end_sec=105.0)) == (80.0, 105.0)
    assert read(SimpleNamespace()) == (0.0, 0.0), '옛 PC(약속 번호 9) · 칸이 없다'
    assert read(SimpleNamespace(segment_start_sec=90.0, segment_end_sec=80.0)) == (0.0, 0.0)
    assert read(SimpleNamespace(segment_start_sec=-1.0, segment_end_sec=0.0)) == (0.0, 0.0)


def test_execution_keeps_the_segment_until_reset():
    execution = GroupExecution()
    execution.begin('pc-a', ['pc-a'], segment_start_sec=80.0, segment_end_sec=105.0)
    assert (execution.segment_start_sec, execution.segment_end_sec) == (80.0, 105.0)
    execution.reset()
    assert (execution.segment_start_sec, execution.segment_end_sec) == (0.0, 0.0)


def test_a_human_group_start_carries_the_segment_to_every_pc():
    node = _master('pc-b', 'pc-c')

    result = node._start_group_execution(request={
        'started_by': 'human', 'run_mode': 'continuous',
        'segment_start_sec': 80.0, 'segment_end_sec': 105.0,
    })

    assert (result['segment_start_sec'], result['segment_end_sec']) == (80.0, 105.0)
    [prepare] = node._command_pub.messages
    assert prepare.command == 'prepare'
    assert (prepare.segment_start_sec, prepare.segment_end_sec) == (80.0, 105.0)
    execution = node.snapshot()['execution']
    assert (execution['segment_start_sec'], execution['segment_end_sec']) == (80.0, 105.0)


def test_the_screen_shape_is_read_too():
    node = _master()
    node._start_group_execution(request={'started_by': 'human', 'segment': {'start_sec': 12, 'end_sec': 0}})
    assert node._command_pub.messages[0].segment_start_sec == 12.0


def test_a_schedule_group_start_is_always_whole():
    node = _master()
    node._start_group_execution(request={
        'started_by': 'schedule', 'segment_start_sec': 80.0, 'segment_end_sec': 105.0,
    })
    [prepare] = node._command_pub.messages
    assert (prepare.segment_start_sec, prepare.segment_end_sec) == (0.0, 0.0)


def test_a_wrong_segment_is_refused_before_anything_is_sent():
    node = _master()
    result = node._handle_local_request({
        'command': 'start_group', 'started_by': 'human',
        'segment_start_sec': 90.0, 'segment_end_sec': 80.0,
    })
    assert result['success'] is False
    assert '구간 끝 1:20 이 구간 시작 1:30 보다 뒤여야 합니다' in result['message']
    assert node._command_pub.messages == []
    assert node._execution.execution_id == ''


def test_group_initialize_also_carries_the_segment():
    node = _master()
    node._start_group_execution(request={'started_by': 'human', 'segment_start_sec': 30.0}, initialization_only=True)
    [prepare] = node._command_pub.messages
    assert prepare.initialization_only is True and prepare.segment_start_sec == 30.0


def _slave():
    node = _node()
    node._config.pc_id = 'pc-b'
    node._config.is_master = False
    node._joined = True
    node._event_pub = _Publisher()
    node._command_pub = _Publisher()
    node._registry.update(_member('pc-a', is_master=True))
    return node


def _prepare(**fields):
    return GroupCommand(
        group_id='stage-a', execution_id='exec-a', command_id='cmd-prepare', coordinator_id='pc-a',
        command='prepare', participant_ids=['pc-a', 'pc-b'], repeat_mode='reinitialize',
        run_mode='continuous', sync_mode='lockstep', **fields,
    )


def test_a_slave_checks_its_own_item_one_against_the_segment_and_refuses_with_the_reason():
    node = _slave()
    asked = []

    def local_http(path, payload, **_kwargs):
        asked.append((path, dict(payload)))
        return {'success': False, 'message': '구간 시작 1:20 이 애니메이션 길이 0:40 보다 깁니다'}

    node._local_http = local_http
    node._process_group_command(_prepare(segment_start_sec=80.0, segment_end_sec=105.0))

    [(path, payload)] = asked
    assert path == '/api/coordination/local-readiness'
    assert (payload['segment_start_sec'], payload['segment_end_sec']) == (80.0, 105.0)
    [event] = node._event_pub.messages
    assert (event.event, event.success) == ('rejected', False)
    assert event.message == '구간 시작 1:20 이 애니메이션 길이 0:40 보다 깁니다'
    assert node._execution.execution_id == '', '거절한 PC 는 잡은 실행을 놓는다(진행 PC 가 이 PC 만 뺀다)'


def test_a_slave_prepares_its_plan_with_the_segment():
    node = _slave()
    node._local_http = lambda *_a, **_k: {'success': True}
    node._process_group_command(_prepare(segment_start_sec=80.0, segment_end_sec=0.0))
    assert (node._execution.segment_start_sec, node._execution.segment_end_sec) == (80.0, 0.0)

    calls = []
    node._call_local_control = lambda payload, **_k: calls.append(dict(payload)) or {'success': True}
    node._local_schedule_ns = lambda _message: time.monotonic_ns() + 2_000_000_000
    node._process_group_command(GroupCommand(
        group_id='stage-a', execution_id='exec-a', command_id='cmd-init', coordinator_id='pc-a',
        command='initialize_at', participant_ids=['pc-a', 'pc-b'],
    ))
    [prepare] = calls
    assert prepare['command'] == 'group_prepare'
    assert (prepare['segment_start_sec'], prepare['segment_end_sec']) == (80.0, 0.0)


def test_master_rejection_for_a_short_item_one_only_drops_the_master():
    """진행 PC 자신의 1번이 짧다 · 다른 PC 가 있으면 진행 PC 만 빠진다(수정 목록 136 ① 그대로) · 그룹 오류 없음"""
    node = _master('pc-b')
    node._event_pub = _Publisher()
    node._note_excluded = lambda *_a, **_k: None
    node._call_local_control = lambda payload, **_k: {'success': True}
    node._start_group_execution(request={'started_by': 'human', 'segment_start_sec': 80.0})
    execution_id = node._execution.execution_id
    from motion_coordination_interfaces.msg import GroupEvent
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-a', event='rejected',
        command_id=node._execution.prepare_command_id, success=False,
        message='구간 시작 1:20 이 애니메이션 길이 0:40 보다 깁니다',
    ))
    assert node._execution.participants == ('pc-b',)
    assert node._coordination_error == {}


def test_start_at_tells_the_speaker_where_to_start():
    node = _node()
    node._local_status = {'motion_run_status': {'motion_file_id': 'show_b.json'}}
    node._command_pub = _Publisher()
    node._execution = GroupExecution()
    execution_id = node._execution.begin('pc-a', ('pc-a', 'pc-b'), segment_start_sec=80.0, segment_end_sec=105.0)
    node._publish_action(SimpleNamespace(
        command='start_at', execution_id=execution_id, cycle_number=1,
        command_id='cmd-x', scheduled_at=time.monotonic() + 0.5,
    ))
    command = node._command_pub.messages[-1]
    assert (command.segment_start_sec, command.segment_end_sec) == (80.0, 105.0)
    assert command.motion_file_id == 'show_b.json'


def test_a_solo_segment_run_also_tells_the_speaker():
    node = _node()
    node._config.configured = True
    node._local_status = {'motion_run_status': {
        'state': 'running', 'group_execution': False, 'motion_file_id': 'show_a.json',
        'phase_started_at': time.time() - 0.05, 'current_cycle': 1, 'run_mode': 'once',
        'segment_start_sec': 80.0, 'segment_end_sec': 105.0,
    }}
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._announce_solo_motion()
    [command] = node._command_pub.messages
    assert (command.segment_start_sec, command.segment_end_sec) == (80.0, 105.0)


def test_a_rejoining_pc_gets_the_same_segment():
    node = _master('pc-b')
    node._start_group_execution(request={'started_by': 'human', 'run_mode': 'continuous', 'segment_start_sec': 80.0})
    invite = node._new_command(
        command='join', execution_id=node._execution.execution_id, cycle_number=3,
        participants=('pc-a', 'pc-c'), segment_start_sec=node._execution.segment_start_sec,
        segment_end_sec=node._execution.segment_end_sec,
    )
    joiner = _slave()
    joiner._config.pc_id = 'pc-c'
    joiner._local_readiness = lambda: {'success': True}
    calls = []
    joiner._call_local_control = lambda payload, **_k: calls.append(dict(payload)) or {'success': True}
    joiner._process_group_command(invite)
    [join] = calls
    assert join['command'] == 'group_join' and join['segment_start_sec'] == 80.0


def test_master_invites_carry_the_segment():
    source = open(coordination_node.__file__, encoding='utf-8').read()
    invite = source[source.index("command='join',"):source.index("for pc_id, reason in drops.items()")]
    assert 'segment_start_sec=self._execution.segment_start_sec' in invite
    assert 'segment_end_sec=self._execution.segment_end_sec' in invite


@pytest.mark.parametrize('field', ['segment_start_sec', 'segment_end_sec'])
def test_the_message_definition_has_the_field(field):
    import pathlib
    msg = pathlib.Path(coordination_node.__file__).resolve().parents[2] / 'motion_coordination_interfaces' / 'msg' / 'GroupCommand.msg'
    assert f'float64 {field}' in msg.read_text(encoding='utf-8')
