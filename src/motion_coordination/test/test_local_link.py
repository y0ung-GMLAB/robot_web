"""연동 노드 ↔ 이 PC 재생 관리자 · 감독 · 로컬 DDS 직접 연결 · 수정 목록 209

전에는 재생 · 안전 상태를 웹(HTTP · 50 ms · 시도 0.3 s)에서 읽고 1.5 s 못 받으면 이 PC 가 그룹에서 빠졌다(172) ·
웹이 잠깐 느린 것만으로 재생 중인 PC 가 빠져(실물 NY 2026-11-04 · 11-09) 「회차 끝까지 버팀」(188 ④) · 「연동 노드
자체 멈춤이면 한 번 더 물음」(184 B) 을 덧댔다 · 명령도 웹을 거쳐 그룹 예약 확인이 늦었다(130 · 153 · 171 · 179).

- 재생 · 안전 상태는 로컬 연결에서 · 웹은 웹만 아는 칸(늦거나 죽어도 아무것도 정하지 않음)
- 그룹 예약 · 풀기 · 합류 확정 · 정지 · 회차 후 정지는 재생 관리자에 바로 · 같은 요청 약속(세대 · 실행 컨텍스트)
- 남은 판정 하나 · 재생 관리자 상태가 `RUNTIME_SILENT_SEC` 넘게 끊김(고장 검출기) → 이 PC 만 빠짐
- 웹 역감시는 연동 노드가 내는 「살아 있음」 으로
"""

import json
import time
from types import SimpleNamespace

import pytest

import motion_coordination.coordination_node as coordination_node
from motion_coordination.group_execution import GroupExecution
from motion_coordination.local_link import RESPONSE_TIMEOUT_TEXT, LinkUnavailable
from local_link_fakes import CONTEXT, fake_link
from test_coordination_node import _InlineThread, _node, _Publisher

# --------------------------------------------------------------------------- #
# 연결 자체 · ROS 없이
# --------------------------------------------------------------------------- #

def test_a_request_carries_the_runtimes_own_generation_and_context():
    link = fake_link()

    result = link.request('group_start_at', {'execution_id': 'exec-a'}, timeout_sec=1.0)

    assert result == {'success': True, 'message': 'ok'}
    [sent] = link.sent
    assert sent['command'] == 'group_start_at'
    assert sent['project_generation'] == 7
    assert sent['request_id'].startswith('coord-g7-')
    assert sent['payload'] == {
        'execution_id': 'exec-a', 'project_id': 'project-a',
        'project_generation': 7, 'context_id': 'ctx-7',
    }


def test_a_given_stamp_wins_for_a_new_session():
    """`group_prepare` 는 준비 검사 때 웹이 준 값 · 그 사이 프로젝트가 바뀌면 재생 관리자가 거절(옛 보호 그대로)"""
    link = fake_link()

    link.request('group_prepare', {}, timeout_sec=1.0, stamp={
        'project_id': 'project-b', 'project_generation': 9, 'context_id': 'ctx-9',
    })

    assert link.sent[0]['project_generation'] == 9
    assert link.sent[0]['payload']['context_id'] == 'ctx-9'


def test_without_a_known_generation_it_cannot_send():
    link = fake_link()
    link.on_runtime_status(json.dumps({'execution_context': {}}))

    with pytest.raises(LinkUnavailable):
        link.request('stop', {}, timeout_sec=0.1)
    assert link.sent == []


def test_no_answer_reads_like_the_web_path_timeout():
    link = fake_link(answer=lambda _command, _payload: None)

    result = link.request('group_start_at', {}, timeout_sec=0.05)

    assert result['success'] is False
    assert result['message'] == RESPONSE_TIMEOUT_TEXT


def test_answers_to_other_requests_are_left_alone():
    link = fake_link()
    link.on_response(json.dumps({'request_id': 'run-g7-1', 'success': True}))   # 웹이 보낸 요청의 답
    assert link._pending == {}


def test_a_closed_link_refuses_and_the_safety_stop_is_plain():
    link = fake_link()
    request_id = link.safety_stop()
    assert link.safety_sent == [{'request_id': request_id, 'command': 'safety_motion_stop'}]
    link.close()
    with pytest.raises(LinkUnavailable):
        link.request('stop', {}, timeout_sec=0.1)
    assert link.up is False


# --------------------------------------------------------------------------- #
# 로컬 명령의 길 · 재생 관리자에 바로 · 웹만 아는 일은 웹
# --------------------------------------------------------------------------- #

def _routed(link, *, http=None):
    node = _node()
    node._local_link = link
    calls = []
    node._local_http = lambda path, payload=None, **_kwargs: (
        calls.append(dict(payload or {})) or (http or {'success': True, 'message': 'web'})
    )
    return node, calls


def test_group_reservations_go_straight_to_the_runtime():
    link = fake_link()
    node, web = _routed(link)

    for payload in (
        {'command': 'group_start_at', 'execution_id': 'exec-a', 'cycle_number': 2, 'start_monotonic': 12.5,
         'network_operation_id': 'cmd-s'},
        {'command': 'group_initialize_at', 'execution_id': 'exec-a', 'cycle_number': 1,
         'initialize_monotonic': 10.0, 'network_operation_id': 'cmd-i'},
        {'command': 'group_join_commit', 'execution_id': 'exec-a', 'cycle_number': 3, 'merge': True},
    ):
        assert node._call_local_control(payload)['success'] is True

    assert web == [], '웹을 거치지 않는다'
    assert [row['command'] for row in link.sent] == ['group_start_at', 'group_initialize_at', 'group_join_commit']
    start = link.sent[0]['payload']
    assert start['start_monotonic'] == 12.5 and start['group_execution'] is True
    assert start['request_source'] == 'network_control' and start['network_operation_id'] == 'cmd-s'
    assert link.sent[2]['payload']['merge'] is True


def test_the_timetable_cycle_command_goes_straight_to_the_runtime():
    """시간표 회차 명령(206)도 로컬 연결로 · 본문은 웹 길과 같은 `group_run_request.cycle_request` ·
    세대 · 실행 컨텍스트는 재생 관리자 상태의 것 · 준비 검사를 안 거친 시간표 실행이라 재생 파일 고르기 없음"""
    link = fake_link()
    node, web = _routed(link)

    result = node._call_local_control({
        'command': 'group_cycle_at', 'execution_id': 'tt-s1', 'cycle_number': 4,
        'start_monotonic': 1234.5, 'next_start_monotonic': 2174.5, 'network_operation_id': 'tt-cycle-a',
    })

    assert result['success'] is True
    assert web == [], '웹을 거치지 않는다'
    [sent] = link.sent
    assert sent['command'] == 'group_cycle_at'
    assert sent['payload'] == {
        'execution_id': 'tt-s1', 'cycle_number': 4, 'start_monotonic': 1234.5,
        'next_start_monotonic': 2174.5, 'network_operation_id': 'tt-cycle-a', 'group_execution': True,
        'project_id': 'project-a', 'project_generation': 7, 'context_id': 'ctx-7',
    }


def test_the_timetable_cycle_command_falls_back_to_the_web_without_the_link():
    """로컬 연결이 없거나(되돌리기) 재생 관리자 세대를 아직 모르면 웹 길 그대로 · 다른 직접 명령과 같다 · 206 · 209"""
    closed = fake_link()
    closed.close()
    node, web = _routed(closed)
    node._call_local_control({'command': 'group_cycle_at', 'execution_id': 'tt-s1', 'cycle_number': 2,
                              'start_monotonic': 50.0})
    unknown = fake_link()
    unknown.on_runtime_status(json.dumps({'execution_context': {}}))
    node2, web2 = _routed(unknown)
    node2._call_local_control({'command': 'group_cycle_at', 'execution_id': 'tt-s1', 'cycle_number': 2,
                               'start_monotonic': 50.0})

    assert [row['command'] for row in web] == ['group_cycle_at']
    assert [row['command'] for row in web2] == ['group_cycle_at']
    assert closed.sent == [] and unknown.sent == []


def test_without_the_link_the_web_fields_poll_stands_in_for_the_alive_signal():
    """되돌리기 길 · 「살아 있음」 토픽을 낼 길이 없다 · 웹 쪽 칸 질문에 `?link=down` · 웹 역감시가 그것을 살아 있음으로 센다 ·
    연결이 있으면 붙이지 않는다(209 · 생사는 토픽)"""
    paths = []

    def http(path, payload=None, **_kwargs):
        paths.append(path)
        return {'bridge_state': 'ok'}

    for link, expected in ((fake_link(), '/api/coordination/local-status'),
                           (None, '/api/coordination/local-status?link=down')):
        node = _node()
        node._local_link = link
        node._local_http = http
        node._fetch_bridge_fields()
        assert paths[-1] == expected
    closed = fake_link()
    closed.close()
    node = _node()
    node._local_link = closed
    node._local_http = http
    node._fetch_bridge_fields()
    assert paths[-1].endswith('?link=down')


def test_group_prepare_uses_what_the_readiness_check_approved():
    link = fake_link()
    node, web = _routed(link)
    node._remember_run_request('exec-a', {'run_request': {
        'motion_file_id': 'show.jsonl', 'mapping_file_id': 'map.yaml',
        'project_id': 'project-a', 'project_generation': 7, 'context_id': 'ctx-7',
    }})

    result = node._call_local_control({
        'command': 'group_prepare', 'execution_id': 'exec-a', 'initialize_monotonic': 20.0,
        'network_operation_id': 'cmd-p', 'repeat_mode': 'reinitialize', 'run_mode': 'continuous',
        'sync_mode': 'lockstep', 'initial_move_time_sec': 7.0,
    })

    assert result['success'] is True
    assert web == []
    [sent] = link.sent
    payload = sent['payload']
    assert sent['command'] == 'group_prepare'
    assert payload['motion_file_id'] == 'show.jsonl' and payload['mapping_file_id'] == 'map.yaml'
    assert payload['initialize_monotonic'] == 20.0 and payload['initial_move_time_sec'] == 7.0
    assert payload['run_mode'] == 'continuous' and payload['group_execution'] is True


def test_web_only_work_stays_on_the_web():
    link = fake_link()
    node, web = _routed(link)

    node._call_local_control({'command': 'group_prepare', 'execution_id': 'tt-s1', 'initialize_monotonic': 5.0})
    node._call_local_control({'command': 'group_join', 'execution_id': 'exec-a', 'join_cycle_number': 2})
    node._call_local_control({'command': 'group_note', 'message': 'x'})
    node._call_local_control({'command': 'stop_after_cycle', 'reason': 'schedule_end'})

    assert [row['command'] for row in web] == ['group_prepare', 'group_join', 'group_note', 'stop_after_cycle']
    assert link.sent == []


def test_a_group_stop_holds_the_output_first_then_stops_the_runtime():
    link = fake_link()
    node, web = _routed(link)

    result = node._call_local_control({'command': 'stop_now', 'execution_id': 'exec-a'}, timeout_sec=0.25)

    assert result['success'] is True
    assert link.safety_sent and link.safety_sent[0]['command'] == 'safety_motion_stop'
    assert [row['command'] for row in link.sent] == ['stop']
    assert web == []


def test_a_group_stop_leaves_a_solo_run_of_a_pc_outside_the_group_alone():
    link = fake_link(runtime={'state': 'running', 'group_execution': False})
    node, _web = _routed(link)

    result = node._call_local_control({'command': 'stop_now', 'execution_id': 'exec-a'})

    assert result['ignored'] is True
    assert link.safety_sent == [] and link.sent == []


def test_releasing_an_already_released_session_is_not_a_failure():
    link = fake_link(answer=lambda _command, _payload: {
        'success': False, 'message': 'motion run command failed: 취소하려는 그룹 실행 세션이 일치하지 않습니다',
    })
    node, _web = _routed(link)

    result = node._call_local_control({'command': 'group_cancel', 'execution_id': 'exec-a'})

    assert result == {'success': True, 'already_released': True, 'message': '이미 정리된 그룹 실행 세션입니다'}


def test_without_the_link_everything_goes_the_old_web_way():
    link = fake_link()
    link.close()
    node, web = _routed(link)

    node._call_local_control({'command': 'group_start_at', 'execution_id': 'exec-a'})

    assert [row['command'] for row in web] == ['group_start_at']


# --------------------------------------------------------------------------- #
# 이 PC 상태 · 웹이 느리거나 죽어도 그룹에서 빠지지 않는다
# --------------------------------------------------------------------------- #

def _playing_master(link, *, web_received_ago, web_failures=9):
    node = _node()
    node._local_link = link
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a', 'pc-b'))
    node._execution.state = 'running'
    node._command_pub = _Publisher()
    node._last_alarm_key = ()
    node._local_runtime_monitor = SimpleNamespace(
        snapshot=lambda: {
            'status': {'bridge_state': 'ok', 'operation_mode': 'schedule',
                       'motion_run_status': {'state': 'stale-from-web'}},
            'received_monotonic': time.monotonic() - web_received_ago,
            'consecutive_failures': web_failures,
        },
        diagnosis=lambda: f'마지막 성공 {web_received_ago * 1000:.0f}ms 전',
    )
    node._stop_for_peer_failure = lambda _reason: pytest.fail('전체를 세우지 않는다')
    node._drop_member_only = lambda reasons, **kwargs: pytest.fail(f'빠지면 안 된다 · {reasons}')
    return node


def test_a_slow_or_dead_web_never_drops_a_playing_pc():
    """실물 NY 2026-11-04 16:11 · 11-09 00:48 · 웹이 0.3~2 s 느려 빠졌다 · 이제 웹은 그룹 판단에 안 쓴다"""
    link = fake_link(runtime={'state': 'running', 'group_execution': True, 'execution_id': 'x'})
    for web_ago in (2.0, 30.0, 600.0):
        node = _playing_master(link, web_received_ago=web_ago)

        node._consume_local_runtime_status()

        assert node._execution.participants == ('pc-a', 'pc-b')
        assert node._local_status['motion_run_status']['state'] == 'running', '재생 상태는 로컬 연결에서'
        assert node._local_status['operation_mode'] == 'schedule', '웹 쪽 칸은 지난 값'


def test_runtime_silence_under_the_limit_keeps_the_pc():
    link = fake_link(runtime_ago=coordination_node.RUNTIME_SILENT_SEC - 1.0)
    node = _playing_master(link, web_received_ago=0.1, web_failures=0)

    node._consume_local_runtime_status()

    assert node._execution.participants == ('pc-a', 'pc-b')


def test_runtime_silence_past_the_limit_drops_only_this_pc_and_clears_when_back(monkeypatch):
    """재생 관리자가 죽음 · 실행기 멈춤 · **고장 검출기** · 이 PC 만 빠진다 · 잠그지 않음 · 돌아오면 기록을 지운다"""
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    link = fake_link(runtime_ago=coordination_node.RUNTIME_SILENT_SEC + 1.0)
    node = _playing_master(link, web_received_ago=0.1, web_failures=0)
    del node._drop_member_only
    node._note_excluded = lambda *_args, **_kwargs: None
    notes = []
    node._note_group = lambda execution_id, event_type, message, details: notes.append(event_type)
    node._call_local_control = lambda payload, **_kwargs: {'success': True}

    node._consume_local_runtime_status()
    node._consume_local_runtime_status()

    assert node._execution.participants == ('pc-b',), '나머지는 계속'
    assert node._execution.execution_id != ''
    loss = node.snapshot()['runtime_loss']
    assert loss['code'] == coordination_node.RUNTIME_LOST_CODE
    assert loss['latched'] is False and loss['message'].startswith('pc-a 재생 관리자 상태 끊김')
    assert node._coordination_error == {}

    link.on_runtime_status(json.dumps({'execution_context': CONTEXT, 'state': 'stopped'}))
    node._consume_local_runtime_status()

    assert node.snapshot()['runtime_loss'] == {}
    assert notes == ['group_runtime_lost']


def test_a_pc_outside_the_group_is_not_watched():
    link = fake_link(runtime_ago=600.0)
    node = _playing_master(link, web_received_ago=0.1)
    node._execution.participants = ('pc-b',)

    node._consume_local_runtime_status()   # 빠지면 _drop_member_only 가 실패시킨다


def test_alive_goes_out_every_half_second_with_this_process():
    link = fake_link()
    node = _node()
    node._local_link = link

    node._publish_alive()
    node._publish_alive()

    [alive] = link.alive_sent
    assert alive['pc_id'] == 'pc-a' and alive['pid'] > 0
    node._alive_published_at -= coordination_node.ALIVE_INTERVAL_SEC
    node._publish_alive()
    assert len(link.alive_sent) == 2


def test_a_passed_readiness_check_is_remembered_for_the_initialize_reservation():
    from motion_coordination_interfaces.msg import GroupCommand

    node = _node()
    node._joined = True
    node._event_pub = _Publisher()
    node._registry.observe = lambda *_args, **_kwargs: None
    node._local_readiness = lambda: {'success': True, 'message': 'ready', 'run_request': {
        'motion_file_id': 'm.jsonl', 'mapping_file_id': 'map.yaml',
        'project_id': 'project-a', 'project_generation': 7, 'context_id': 'ctx-7',
    }}

    node._process_group_command(GroupCommand(
        group_id='stage-a', execution_id='exec-z', command_id='cmd-prepare', coordinator_id='pc-a',
        command='prepare', participant_ids=['pc-a'], run_mode='continuous',
    ))

    assert node._run_request_for('exec-z')['motion_file_id'] == 'm.jsonl'
    assert node._event_pub.messages[-1].event == 'ready'
