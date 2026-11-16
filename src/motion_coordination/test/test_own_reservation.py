"""진행 PC 자신의 그룹 예약은 이 프로세스 안에서 바로 · 수정 목록 207

전에는 마스터도 제 예약(`initialize_at` · `cycle_initialize_at` · `start_at`)을 다른 PC 와 같은 길로 받았다 ·
DDS 로 제게 돌아온 명령 → 명령 처리 줄 → HTTP → 웹(매번 프로젝트 · 매핑 YAML 읽기) → ROS → 재생 관리자 ·
웹 짐에 따라 늦어 「자신의 예약 확인 늦음」 으로 빠지거나 그룹이 취소됐다(130 · 153 · 171 · 179) · 그래서
여유 바닥(1회차 시작 3 s · 회차 초기화 1.5 s)과 회차 초기화 다시 예약(153 ② · 2번 · 기다림 15 s)을 덧댔다.

- 제 예약은 보낸 즉시 제 차례(전용 스레드)에서 재생 관리자에 · 확인을 바로 센다 · DDS 로 돌아온 같은 명령은 버린다
- 못 잡으면 이 PC 만 빠지고(178) 나머지는 같은 시각에 돈다 · 그룹 취소 · 다시 예약 없음
- 마감까지 제 답이 없으면 다른 PC 와 같게 뺀다 · 따로 기다리지 않는다
- 여유 · 회차 초기화 바닥 없음 · 재시작 뒤 잰 값이 없으면 같은 PC 의 다른 예약에서 방금 잰 값 · 1회차 시작 바닥
  3 s 는 남김(잰 값이 없을 때의 기본값 · 사용자 결정 179)
"""

import time
from types import SimpleNamespace

import pytest
from motion_coordination_interfaces.msg import GroupCommand

import motion_coordination.coordination_node as coordination_node
from motion_coordination.group_execution import GroupExecution
from motion_coordination.schedule_lead import FIRST_START_LEAD_MIN_SEC, INITIALIZE_LEAD_MIN_SEC
from test_coordination_node import _InlineThread, _node, _Publisher


def _inline_lane(node):
    """제 차례 스레드를 그 자리에서 · 결과를 바로 본다"""
    node._own_reservations = SimpleNamespace(
        submit=lambda message, **_kwargs: (node._reserve_own_now(message), True)[1],
    )


def _local(node, *replies):
    calls = []
    queue = list(replies)

    def control(payload, **_kwargs):
        calls.append(dict(payload))
        reply = queue.pop(0) if queue else {'success': True, 'message': 'ok'}
        return reply() if callable(reply) else reply

    node._call_local_control = control
    return calls


def _between_cycles(node, participants=('pc-a', 'pc-b'), cycle=3):
    """마스터 pc-a · 회차 끝 · 모두 모션 완료 · 회차 초기화를 보낼 차례"""
    node._joined = True
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
    with node._lock:
        node._complete_trigger_sync_if_ready()
    command = node._command_pub.messages[-1]
    return command, command.scheduled_monotonic_ns / 1e9 - before


def test_the_master_reserves_its_own_cycle_initialize_in_process():
    node = _node()
    _inline_lane(node)
    calls = _local(node)

    command, _lead = _between_cycles(node)

    assert command.command == 'cycle_initialize_at'
    [call] = calls
    assert call['command'] == 'group_initialize_at'
    assert call['network_operation_id'] == command.command_id
    assert call['initialize_monotonic'] == pytest.approx(command.scheduled_monotonic_ns / 1e9, abs=1e-6)
    # 제 확인은 바로 센다 · 상대 PC 만 남는다
    assert node._execution.pending_acks == {'pc-a'}
    assert node._execution.pending_command_id == command.command_id


def test_the_dds_copy_of_an_own_reservation_is_dropped():
    node = _node()
    _inline_lane(node)
    _local(node)
    command, _lead = _between_cycles(node)
    submitted = []
    node._command_dispatcher = SimpleNamespace(
        submit=lambda message, urgent_stop=False: submitted.append(message.command) or True,
    )

    node._command_callback(command)

    assert submitted == [], 'DDS 로 돌아온 제 예약을 다시 처리하지 않는다'


def test_the_master_reserves_its_own_start_in_process_and_marks_it_scheduled():
    node = _node()
    _inline_lane(node)
    calls = _local(node)
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a', 'pc-b'))
    node._execution.state = 'armed'
    node._sync_ready = {'pc-a', 'pc-b'}
    node._sync_next_action = 'start'
    node._trigger_sync_status['trigger_sync_state'] = 'ready'

    with node._lock:
        node._complete_trigger_sync_if_ready()

    [call] = calls
    assert call['command'] == 'group_start_at'
    assert call['cycle_number'] == 1
    assert node._execution.pending_acks == {'pc-a'}
    assert 'pc-a' in node._execution.scheduled
    assert node._event_pub.messages == [], '제 예약 사건을 DDS 로 돌려 받을 필요가 없다'


def test_a_failed_own_reservation_drops_only_the_master_without_retry(monkeypatch):
    """제 재생 관리자가 거절 · 이 PC 만 빠진다 · 다른 PC 는 받은 시각 그대로 · 다시 예약 · 그룹 취소 없음"""
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _node()
    node._note_excluded = lambda *_args, **_kwargs: None
    _inline_lane(node)
    calls = _local(node, {'success': False, 'message': '그룹 회차 초기화 트리거가 이미 지났습니다'})

    command, _lead = _between_cycles(node)

    assert [row['command'] for row in calls] == ['group_initialize_at', 'stop_now']
    assert node._execution.execution_id != '', '그룹은 계속'
    assert node._execution.participants == ('pc-b',)
    published = [m.command for m in node._command_pub.messages]
    assert published == ['cycle_initialize_at', 'update_participants']
    assert 'cancel_before_start' not in published
    assert node._coordination_error == {}
    assert getattr(node, '_last_start_failure', {}) == {}


def test_an_own_reservation_for_a_finished_execution_is_skipped():
    node = _node()
    calls = _local(node)
    command, _lead = _between_cycles(node)   # 제 차례 없음(시험 노드) · 아래에서 직접
    node._execution.clear_active()

    node._reserve_own_now(command)

    assert calls == []


def test_the_deadline_treats_the_master_like_any_other_pc(monkeypatch):
    """마감까지 제 답이 없다(재생 관리자가 답을 못 함) · 다른 PC 처럼 뺀다 · 따로 기다리지 않는다 · 207

    전에는 회차 초기화면 제 답을 15 s 까지 기다렸다(153 ②) · 그 사이 다른 PC 는 그 시각에 초기 위치로 갔다.
    """
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node = _node()
    node._note_excluded = lambda *_args, **_kwargs: None
    calls = _local(node)
    _command, _lead = _between_cycles(node)          # 제 차례 없음 · 제 답이 안 왔다
    node._execution.pending_acks = {'pc-b'}
    node._execution.pending_ack_deadline = time.monotonic() - 0.01

    node._enforce_schedule_ack_deadline()

    assert node._execution.participants == ('pc-b',), '진행 PC 만 빠지고 나머지는 계속'
    assert node._execution.execution_id != ''
    assert [row['command'] for row in calls] == ['stop_now'], '제 재생만 세운다'
    assert node._coordination_error == {}
    assert getattr(node, '_last_start_failure', {}) == {}


def test_a_late_peer_between_cycles_is_dropped_without_latch():
    node = _node()
    node._note_excluded = lambda *_args, **_kwargs: None
    _command, _lead = _between_cycles(node)
    node._execution.pending_acks = {'pc-a'}
    node._execution.pending_ack_deadline = time.monotonic() - 0.01
    node._call_local_control = lambda payload, **_kwargs: {'success': True}

    node._enforce_schedule_ack_deadline()

    assert node._coordination_error == {}
    assert node._execution.participants == ('pc-a',)


def test_cycle_initialize_has_no_floor_anymore_but_the_first_start_keeps_its_default():
    """잰 값이 없으면 회차 초기화는 설정값(0.5 s · 전 1.5 s 바닥 · 153 · 207) · 1회차 시작은 3 s 그대로

    1회차 시작 바닥은 진행 PC 의 길 때문이 아니다 · 재시작 뒤에는 다른 PC 들의 Wi-Fi 왕복을 잰 값이 없다 ·
    그때의 기본값(사용자 결정 179 「그룹 시작 · 스케줄 시작 때 시간 여유를 확 늘리자」) · 진행 PC 자신의 예약은
    그래도 프로세스 안에서 바로(207)
    """
    node = _node()
    _command, lead = _between_cycles(node)
    assert lead == pytest.approx(0.5, abs=0.05)
    assert node._schedule_lead_sec('first_start') == pytest.approx(FIRST_START_LEAD_MIN_SEC)
    # 초기 위치는 바닥 그대로 · 모든 PC 가 확인 뒤 재생 계획을 짓는다(164)
    assert node._schedule_lead_sec('initialize') == pytest.approx(INITIALIZE_LEAD_MIN_SEC)


def test_a_follower_still_reserves_what_it_receives():
    """슬레이브는 DDS 로 받은 예약을 그대로 처리 · 길은 재생 관리자에 바로(`_call_local_control`)"""
    node = _node()
    node._event_pub = _Publisher()
    node._execution = GroupExecution()
    node._execution.activate_claim('exec-b', 'pc-b', ('pc-a', 'pc-b'))
    node._trigger_sync_status['trigger_sync_state'] = 'ready'
    calls = _local(node, {'success': False, 'message': '그룹 회차 초기화 트리거가 이미 지났습니다'})

    node._process_group_command(GroupCommand(
        group_id='stage-a', execution_id='exec-b', command_id='cmd-ci', coordinator_id='pc-b',
        command='cycle_initialize_at', cycle_number=2, participant_ids=['pc-a', 'pc-b'],
        scheduled_monotonic_ns=time.monotonic_ns() + 2_000_000_000,
    ))

    assert len(calls) == 1, '다시 예약하지 않는다'
    assert node._event_pub.messages[-1].event == 'rejected'
