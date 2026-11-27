"""웹 서비스가 다시 시작돼도 그룹 오류(2등급)로 잠그지 않는다 · 노드에 붙여서 · 수정 목록 145

실물 2026-10-14 11:49 floating4 (V-28 ④) · 그룹 연속 1회차 중 `systemctl --user restart motion-control` →
연동 노드가 「로컬 Web Bridge 상태 수신 중단」 → 전체 정지 → GROUP_PARTICIPANT_FAILURE 2등급 →
「그룹 오류 해제」 를 눌러야 다음 그룹 시작.

- ① 정상 종료(「프로그램 다시 시작」 · SIGTERM · systemd 다시 시작) · 웹이 먼저 「이 PC 빠짐」 을 알린다 ·
  그 PC 만 빠지고 나머지는 계속 · 마지막 PC 면 그룹만 세운다 · 진행 PC 자신이면 진행만 계속
- ② 갑자기 끊김 · 전에는 이 PC 만 빠졌다(178) · 수정 목록 209 뒤로 웹 끊김은 그룹과 상관없다(재생 상태는
  재생 관리자에서 로컬 DDS 로 직접) · 「이 PC 빠짐」 은 웹이 내려가며 알릴 때(①)와 재생 관리자가 끊길 때만

규칙만 보는 시험(장벽 넘기기)은 `test_group_execution.py`.
"""

import time
import motion_coordination.coordination_node as coordination_node
from test_coordination_node import _InlineThread
from types import SimpleNamespace

import pytest
from motion_coordination_interfaces.msg import GroupEvent

from motion_coordination.group_execution import (
    PARTICIPANT_LEFT_EVENT,
    GroupExecution,
)
from test_coordination_node import _node, _Publisher


def _master(participants=('pc-a', 'pc-b')):
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._notes = []
    node._note_excluded = lambda execution_id, excluded, participants, *, stage: (
        node._notes.append((dict(excluded), tuple(participants), stage))
    )
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._execution = GroupExecution()
    node._execution.begin('pc-a', participants, coordinator_participates='pc-a' in participants)
    node._execution.state = 'running'
    node._execution.cycle_number = 1
    return node


def _left(node, pc_id, reason='웹 서비스 다시 시작'):
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id=pc_id,
        event=PARTICIPANT_LEFT_EVENT, success=True, message=reason,
        command_id='runtime-participant_left-1', cycle_number=1,
    ))


def _no_latch(node):
    node._stop_for_peer_failure = lambda reason: pytest.fail(f'2등급으로 잠그면 안 됨 · {reason}')


# ① 정상 종료 · 그 PC 만 빠진다 --------------------------------------------------------------- #

def test_a_participant_whose_web_restarts_is_taken_out_and_the_rest_keep_going():
    node = _master(('pc-a', 'pc-b', 'pc-c'))
    _no_latch(node)
    execution_id = node._execution.execution_id

    _left(node, 'pc-b')

    assert node._execution.execution_id == execution_id
    assert node._execution.participants == ('pc-a', 'pc-c')
    assert node._execution.state == 'running'
    assert node._execution.excluded == {'pc-b': '웹 서비스 다시 시작'}
    commands = [(m.command, tuple(m.participant_ids)) for m in node._command_pub.messages]
    assert ('update_participants', ('pc-a', 'pc-c')) in commands
    assert ('cancel_before_start', ('pc-a', 'pc-b')) in commands, '뺀 PC 에만 풀기'
    assert all(command != 'stop_now' for command, _ in commands)
    assert node._coordination_error == {}
    assert node._notes == [({'pc-b': '웹 서비스 다시 시작'}, ('pc-a', 'pc-c'), '도는 중')]


def test_after_leaving_its_stopped_report_does_not_release_the_group():
    """빠진 PC 의 「정지」 사건은 실행 밖 PC 의 늦은 사건 · 전체 풀기(123)로 읽지 않는다"""
    node = _master(('pc-a', 'pc-b', 'pc-c'))
    _left(node, 'pc-b')
    node._begin_group_release = lambda: pytest.fail('빠진 PC 의 정지로 그룹을 풀면 안 됨')

    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id='pc-b',
        event='stopped', success=True, command_id='runtime-stopped-1', cycle_number=1,
    ))

    assert node._execution.participants == ('pc-a', 'pc-c')


def test_the_last_participant_leaving_stops_the_group_without_a_latch():
    """진행 PC 가 바빠 빠져 있고 남은 한 대가 웹 다시 시작 · 그룹만 세운다"""
    node = _master(('pc-b',))
    _no_latch(node)

    _left(node, 'pc-b')

    assert node._execution.execution_id == ''
    assert node._coordination_error == {}
    failure = node.snapshot()['last_start_failure']
    assert failure['code'] == 'GROUP_PARTICIPANT_LEFT'
    assert failure['message'].startswith('그룹 실행 정지: 잔여 PC 없음 (잠금 없음) · pc-b(')
    commands = [(m.command, tuple(m.participant_ids)) for m in node._command_pub.messages]
    assert commands == [('cancel_before_start', ('pc-a', 'pc-b'))]


def test_the_master_restarting_its_web_keeps_coordinating_the_others():
    """연동 서비스는 따로라 살아 있다 · 진행 PC 자신만 빠지고 진행은 계속"""
    node = _master(('pc-a', 'pc-b'))
    _no_latch(node)
    execution_id = node._execution.execution_id

    result = node._handle_local_request({'command': 'bridge_leaving', 'reason': '웹 서비스 다시 시작'})

    assert result['success'] is True
    assert result['still_coordinating'] is True
    assert node._execution.execution_id == execution_id
    assert node._execution.coordinator_id == 'pc-a'
    assert node._execution.participants == ('pc-b',)
    commands = [(m.command, tuple(m.participant_ids)) for m in node._command_pub.messages]
    assert commands == [('update_participants', ('pc-b',))], '제 자신에게 풀기를 보내지 않는다'
    assert node._coordination_error == {}


def test_a_master_that_only_coordinates_ignores_its_own_web_going_away():
    """빠진 뒤 제 웹이 내려간 동안 「상태 수신 중단」 이 나머지 PC 를 세우지 않는다"""
    node = _master(('pc-a', 'pc-b'))
    node._handle_local_request({'command': 'planned_restart'})
    # 「다시 뜨는 중」 덕이 아님을 보인다 · 새 추적기는 아래 답을 준비 끝으로 본다(전 `_planned_restart_until = 0`) · 수정 목록 202
    node._bridge_readiness = None
    node._stop_for_bridge_loss = lambda detail: pytest.fail(f'진행만 하는 PC 는 세우지 않음 · {detail}')
    node._release_without_latch = lambda reason: pytest.fail(f'진행만 하는 PC 는 풀지 않음 · {reason}')
    _no_latch(node)
    before = len(node._command_pub.messages)
    node._local_runtime_monitor = SimpleNamespace(
        snapshot=lambda: {'status': {}, 'received_monotonic': 1.0, 'active_since_monotonic': 0.0},
        diagnosis=lambda: '연결 거부',
    )

    node._consume_local_runtime_status()
    node._consume_local_runtime_status()

    assert node._execution.participants == ('pc-b',)
    assert len(node._command_pub.messages) == before


def test_the_master_alone_restarting_its_web_stops_without_a_latch():
    """실물 V-28 · floating4 혼자 그룹 연속 · 「프로그램 다시 시작」"""
    node = _master(('pc-a',))
    _no_latch(node)

    result = node._handle_local_request({'command': 'planned_restart'})

    assert result['success'] is True
    assert result['still_coordinating'] is False
    assert node._execution.execution_id == ''
    assert node._coordination_error == {}
    assert node.snapshot()['last_start_failure']['code'] == 'GROUP_PARTICIPANT_LEFT'
    assert node._command_pub.messages == [], '남은 PC 가 없다 · 보낼 곳 없음'
    # 다음 그룹 시작이 「이전 그룹 실행 정리 확인 중입니다」 로 막히지 않는다
    assert node._execution.begin('pc-a', ('pc-a',))


def test_a_participant_tells_its_coordinator_and_lets_go():
    node = _node()
    node._joined = True
    node._event_pub = _Publisher()
    node._execution = GroupExecution()
    node._execution.activate_claim('exec-a', 'pc-b', ('pc-a', 'pc-b'))

    result = node._handle_local_request({'command': 'bridge_leaving', 'reason': '웹 서비스 다시 시작'})

    assert result['success'] is True and result['left'] is True
    [event] = node._event_pub.messages
    assert event.event == PARTICIPANT_LEFT_EVENT
    assert event.execution_id == 'exec-a'
    assert event.pc_id == 'pc-a'
    assert event.message == '웹 서비스 다시 시작'
    assert node._execution.execution_id == ''
    assert 'exec-a' in node._cancelled_execution_ids, '놓은 실행의 늦은 명령은 거절 없이 버린다'


def test_leaving_with_nothing_running_does_nothing():
    node = _node()
    node._event_pub = _Publisher()

    result = node._handle_local_request({'command': 'bridge_leaving'})

    assert result == {
        'success': True, 'left': False, 'still_coordinating': False,
        'message': '웹 재시작: 진행 중인 그룹 실행 없음',
    }
    assert node._event_pub.messages == []


def test_a_leaving_pc_that_held_the_last_report_lets_the_cycle_move_on():
    """남은 PC 는 회차를 끝냈다 · 빠진 PC 의 완료 보고만 기다리던 장벽을 넘긴다"""
    node = _master(('pc-a', 'pc-b'))
    node._execution.motion_completed = {'pc-a'}
    advanced = []
    node._publish_next_cycle = lambda: advanced.append('next_cycle')

    _left(node, 'pc-b')

    assert node._execution.state == 'motion_completed'
    assert advanced == ['next_cycle']


def test_a_rejoining_pc_with_a_silent_web_keeps_its_rejoin():
    """복귀 준비 중(아직 참가자 아님) · 웹이 조용하다 · 남의 그룹을 세우지 않고 제 복귀도 놓지 않는다 · 수정 목록 209

    전에는 웹 끊김을 보고 진행 PC 에 「빠짐」 을 알리고 놓았다(145) · 이제 웹은 그룹 판단에 안 쓴다.
    """
    node = _node()
    node._joined = True
    node._event_pub = _Publisher()
    node._command_pub = _Publisher()
    node._execution = GroupExecution()
    node._execution.activate_claim('exec-a', 'pc-b', ('pc-b', 'pc-c'))
    node._execution.join_cycle = 3
    node._stop_for_bridge_loss = lambda detail: pytest.fail(f'남의 그룹을 세우면 안 됨 · {detail}')
    node._local_runtime_monitor = SimpleNamespace(
        snapshot=lambda: {'status': {}, 'received_monotonic': 1.0, 'active_since_monotonic': 0.0},
        diagnosis=lambda: '연결 거부',
    )

    node._consume_local_runtime_status()

    assert node._event_pub.messages == []
    assert node._command_pub.messages == []
    assert node._execution.execution_id == 'exec-a'


# ② 갑자기 끊김 · 웹은 그룹과 상관없다 · 수정 목록 209 -------------------------------------------- #

def test_a_sudden_web_loss_takes_nobody_out_and_records_nothing(monkeypatch):
    """알림 없이 웹이 사라졌다 · 전에는 이 PC(진행 PC)만 빠지고 기록(145 ② → 178) · 이제 아무도 안 빠진다"""
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _master(('pc-a', 'pc-b'))
    node._last_alarm_key = (0, ())
    _no_latch(node)
    node._local_runtime_monitor = SimpleNamespace(
        snapshot=lambda: {
            'status': {'bridge_state': 'ok'},
            'received_monotonic': time.monotonic() - 30.0, 'active_since_monotonic': 0.0,
        },
        diagnosis=lambda: '마지막 성공 30000ms 전 · 연속 실패 60회',
    )

    node._consume_local_runtime_status()

    assert node._execution.participants == ('pc-a', 'pc-b')
    assert node._command_pub.messages == []
    assert node._coordination_error == {}
    assert node.snapshot()['runtime_loss'] == {}
