"""회차 맞춤 그룹 · 회차 사이 마스터 자신의 회차 초기화 확인이 늦어도 그룹을 취소하지 않는다 · 수정 목록 153

실물 2026-10-16 14:35:05 floating3(마스터 38 s) · floating4(17 s) · 스케줄 그룹 연속 · `279c7bad`

    3회차 끝 → 「floating3 자신의 예약 확인 늦음 · cycle_initialize_at · 679 ms 안에 답 없음」
    → cancel_before_start · floating4 는 초기 이동 출발 → 취소 · 스케줄이 14:35:44 다시 시작
    → 매장에서 약 40 s 멈춤

① 회차 초기화 여유 · 따로 잰다 · 바닥 1.5 s
② 마스터 자신만 늦으면 · 마감 검사는 제 답을 기다리고 · 못 잡힌 예약은 여유를 늘려 이 PC 만 다시(2번까지)
"""

import time

import pytest
from motion_coordination_interfaces.msg import GroupCommand, GroupEvent

from motion_coordination.group_execution import GroupExecution
from motion_coordination.schedule_lead import (
    CYCLE_INITIALIZE_LEAD_MIN_SEC, SELF_LATE_WAIT_MAX_SEC,
)
from test_coordination_node import _node, _Publisher

LATE = '그룹 회차 초기화 트리거가 이미 지났습니다'


def _between_cycles(node, participants=('pc-a', 'pc-b'), cycle=3):
    """마스터 pc-a · 회차 끝 · 모두 모션 완료"""
    node._execution = GroupExecution()
    node._execution.begin('pc-a', participants)
    node._execution.state = 'motion_completed'
    node._execution.cycle_number = cycle
    node._execution.motion_completed = set(participants)
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._sync_ready = set(participants)
    node._sync_next_action = 'cycle_initialize'
    node._trigger_sync_status['trigger_sync_state'] = 'ready'
    before = time.monotonic()
    node._complete_trigger_sync_if_ready()
    command = node._command_pub.messages[-1]
    return command, command.scheduled_monotonic_ns / 1e9 - before


def test_cycle_initialize_lead_starts_at_its_own_floor():
    node = _node()
    command, lead = _between_cycles(node)

    assert command.command == 'cycle_initialize_at'
    assert lead == pytest.approx(CYCLE_INITIALIZE_LEAD_MIN_SEC, abs=0.05)
    # 첫 초기 위치의 무거운 값(group_prepare)은 회차 사이 여유에 안 섞인다
    node._lead_planner().record('initialize', 'pc-a', 1.2)
    node._schedule_sent[command.command_id] = (time.monotonic() - 0.9, time.monotonic() + 0.5)
    node._note_own_schedule_latency(command, {'success': True})
    assert node._lead_planner().worst('cycle_initialize', ('pc-a',)) == pytest.approx(0.9, abs=0.05)
    assert node._lead_planner().worst('schedule', ('pc-a',)) == 0.0


def _overdue(node, command):
    """마감이 지났다 · 상대 PC 는 답했고 마스터 자신만 아직"""
    node._execution.pending_acks = {'pc-b'}
    node._execution.pending_ack_deadline = time.monotonic() - 0.01
    node._call_local_control = lambda payload, **_kwargs: pytest.fail(
        f'그룹 취소 · 정지를 보내지 않는다 · {payload}'
    )


def test_deadline_waits_for_the_masters_own_cycle_initialize_answer():
    node = _node()
    command, _lead = _between_cycles(node)
    _overdue(node, command)
    warned = []
    node.get_logger = lambda: type('L', (), {
        'warn': lambda _self, text: warned.append(text),
        'error': lambda _self, text: pytest.fail(text),
        'info': lambda _self, _text: None,
    })()

    node._enforce_schedule_ack_deadline()
    node._enforce_schedule_ack_deadline()

    assert node._execution.execution_id != ''
    assert node._execution.state == 'cycle_initializing'
    assert node._coordination_error == {}
    assert [m.command for m in node._command_pub.messages] == ['cycle_initialize_at']
    assert len(warned) == 1 and '그룹 취소하지 않고' in warned[0], '한 번만 남긴다'

    # 늦게라도 받았다(예약 시각 전에 로컬이 잡음) · 그대로 간다
    node._note_own_schedule_latency(command, {'success': True})
    assert node._execution.pending_command_id == ''
    assert node._execution.execution_id != ''


def test_deadline_still_cancels_without_latch_when_the_wait_runs_out():
    node = _node()
    command, _lead = _between_cycles(node)
    _overdue(node, command)
    node._execution.pending_published_at = time.monotonic() - SELF_LATE_WAIT_MAX_SEC - 0.1
    sent = []
    node._call_local_control = lambda payload, **_kwargs: (
        sent.append(payload['command']) or {'success': True}
    )

    node._enforce_schedule_ack_deadline()

    assert sent == ['group_cancel']
    assert node._coordination_error == {}
    assert node._last_start_failure['code'] == 'GROUP_SCHEDULE_SELF_LATE'


def test_a_late_peer_between_cycles_still_cancels_as_before():
    node = _node()
    command, _lead = _between_cycles(node)
    node._execution.pending_acks = {'pc-a'}
    node._execution.pending_ack_deadline = time.monotonic() - 0.01
    node._call_local_control = lambda payload, **_kwargs: {'success': True}

    node._enforce_schedule_ack_deadline()

    assert node._coordination_error['code'] == 'GROUP_SCHEDULE_ACK_TIMEOUT'


def _local_replies(node, *replies):
    calls = []
    queue = list(replies)

    def local_control(payload, **_kwargs):
        calls.append(dict(payload))
        reply = queue.pop(0) if queue else {'success': True}
        return reply() if callable(reply) else reply

    node._call_local_control = local_control
    return calls


def test_masters_own_missed_cycle_initialize_is_rebooked_with_more_lead():
    node = _node()
    command, _lead = _between_cycles(node)
    node._execution.pending_acks.add('pc-b')   # 상대 PC 는 이미 답했다
    calls = _local_replies(node, {'success': False, 'message': LATE}, {'success': True, 'message': 'ok'})
    before = time.monotonic()

    node._process_group_command(command)

    assert [row['command'] for row in calls] == ['group_initialize_at', 'group_initialize_at']
    assert calls[1]['cycle_number'] == 3
    assert calls[1]['network_operation_id'] == command.command_id
    assert calls[1]['initialize_monotonic'] - before >= CYCLE_INITIALIZE_LEAD_MIN_SEC - 0.05
    assert calls[1]['initialize_monotonic'] > calls[0]['initialize_monotonic']
    [event] = node._event_pub.messages
    assert (event.event, event.success) == ('cycle_initialize_scheduled', True)
    # 제 확인은 다시 예약이 잡힌 때 센다 · 그룹은 그대로
    assert node._execution.pending_command_id == ''
    assert node._execution.state == 'cycle_initializing'
    assert node._coordination_error == {}


def test_a_short_margin_on_the_masters_own_command_is_rebooked_too():
    """제 명령이 DDS 를 늦게 돌아와 마감 0.1 s 안 · `_local_schedule_ns` 가 거절 · 같은 길로 다시"""
    node = _node()
    command, _lead = _between_cycles(node)
    node._execution.pending_acks.add('pc-b')
    calls = _local_replies(node, {'success': True})

    def too_late(_message):
        raise ValueError('그룹 예약 트리거의 준비 여유가 부족합니다')

    node._local_schedule_ns = too_late

    node._process_group_command(command)

    assert [row['command'] for row in calls] == ['group_initialize_at']
    assert node._event_pub.messages[-1].event == 'cycle_initialize_scheduled'
    assert node._execution.pending_command_id == ''


def test_rebooking_gives_up_after_two_tries_and_cancels_as_before():
    node = _node()
    command, _lead = _between_cycles(node)
    calls = _local_replies(node, *[{'success': False, 'message': LATE}] * 5)

    node._process_group_command(command)

    assert len(calls) == 3, '처음 + 다시 2번'
    [event] = node._event_pub.messages
    assert (event.event, event.success) == ('rejected', False)
    # 그 거절은 옛 길 · 「자신의 예약 확인 늦음」 · 잠그지 않고 취소
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=command.execution_id, pc_id='pc-a',
        event='rejected', command_id=command.command_id, success=False, message=event.message,
    ))
    assert node._coordination_error == {}
    assert node._last_start_failure['code'] == 'GROUP_SCHEDULE_SELF_LATE'


def test_a_response_timeout_is_not_rebooked():
    """받았는지 모른다 · 다시 예약하면 두 번 잡힐 수 있다 · 옛 그대로"""
    node = _node()
    command, _lead = _between_cycles(node)
    calls = _local_replies(node, {'success': False, 'message': 'motion_run_manager response timeout'})

    node._process_group_command(command)

    assert len(calls) == 1
    assert node._event_pub.messages[-1].event == 'rejected'


def test_rebooking_stops_once_the_group_was_cancelled():
    node = _node()
    command, _lead = _between_cycles(node)

    def cancelled_meanwhile():
        # 첫 로컬 호출 중에 그룹이 취소됐다(마감 상한 · 사람 정지)
        node._cancelled_execution_ids.add(command.execution_id)
        return {'success': False, 'message': LATE}

    calls = _local_replies(node, cancelled_meanwhile)

    node._process_group_command(command)

    # 다시 예약하지 않는다 · 늦게 끝난 명령은 이 PC 를 세우고 사건 없이 버린다(수정 목록 102)
    assert [row['command'] for row in calls] == ['group_initialize_at', 'stop_now']
    assert node._event_pub.messages == []


def test_a_follower_does_not_rebook_on_its_own():
    """다시 예약은 진행 PC 자신의 것만 · 다른 PC 의 거절은 진행 PC 가 옛 그대로 판단한다"""
    node = _node()
    node._execution = GroupExecution()
    node._execution.activate_claim('exec-b', 'pc-b', ('pc-a', 'pc-b'))
    node._trigger_sync_status['trigger_sync_state'] = 'ready'
    calls = _local_replies(node, {'success': False, 'message': LATE})

    node._process_group_command(GroupCommand(
        group_id='stage-a', execution_id='exec-b', command_id='cmd-ci', coordinator_id='pc-b',
        command='cycle_initialize_at', cycle_number=2, participant_ids=['pc-a', 'pc-b'],
        scheduled_monotonic_ns=time.monotonic_ns() + 2_000_000_000,
    ))

    assert len(calls) == 1
    assert node._event_pub.messages[-1].event == 'rejected'
