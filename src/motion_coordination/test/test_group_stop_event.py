"""진행 PC 가 그룹 실행을 놓을 때 「정지」 사건을 한 번 낸다 · 스피커가 그걸로 소리를 멈춘다 · 수정 목록 146 ②

실물 2026-10-15 floating4 (W-A5 · W-A10) · 즉시 정지 · 「프로그램 다시 시작」 · `restart motion-control` 에
스피커가 안 멈추고, 다음 그룹 시작의 `ready` 에 실린 낡은 `state=stopped` 로 새 소리가 끊겼다 ·
진행 PC 는 `_clear_active_execution` 바로 뒤 제 런타임 `stopped` 를 실행 번호 비교로 버렸다.

- 즉시 정지 · 남은 PC 없음 · 회차 후 정지 끝 · 1회 재생 끝 · 진행 PC 혼자 빠짐 · 종료 → 사건 1건
- 지우기 **전에** 낸다 · `event=stopped` · `state=stopped` · 실행 번호 · 보낸 PC = 진행 PC
- 같은 실행에 두 번 내지 않는다 · 참가 PC(진행 아님)는 내지 않는다
- 진행 PC 자신만 빠지고 나머지는 계속 → 내지 않는다 · 제 런타임 `stopped` 도 그룹 사건으로 안 낸다
"""

from motion_coordination_interfaces.msg import GroupEvent

from motion_coordination.group_execution import PARTICIPANT_LEFT_EVENT, GroupExecution
from test_coordination_node import _node, _peer_release_ack, _Publisher


class _EventPublisher(_Publisher):
    """낼 때 노드가 아직 그 실행을 쥐고 있었는지 같이 적는다"""

    def __init__(self, node):
        super().__init__()
        self.node = node
        self.held = []

    def publish(self, message):
        super().publish(message)
        self.held.append(self.node._execution.execution_id)


def _master(participants=('pc-a', 'pc-b'), *, run_mode='continuous'):
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _EventPublisher(node)
    node._note_excluded = lambda *_args, **_kwargs: None
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._execution = GroupExecution()
    node._execution.begin(
        'pc-a', participants, coordinator_participates='pc-a' in participants,
        run_mode=run_mode,
    )
    node._execution.state = 'running'
    node._execution.cycle_number = 3
    return node


def _group_stops(node):
    return [
        (message, held)
        for message, held in zip(node._event_pub.messages, node._event_pub.held)
        if message.command_id.startswith('group-stopped-')
    ]


def _assert_one_stop(node, execution_id):
    stops = _group_stops(node)
    assert len(stops) == 1, [m.event for m in node._event_pub.messages]
    message, held = stops[0]
    assert message.event == 'stopped'
    assert message.state == 'stopped', '캐시된 모션 상태가 아니라 정지'
    assert message.execution_id == execution_id
    assert message.pc_id == 'pc-a'
    assert message.group_id == 'stage-a'
    assert message.cycle_number == 3
    assert held == execution_id, '지우기 전에 낸다'
    assert node._execution.execution_id == ''


def _left(node, pc_id):
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id=pc_id,
        event=PARTICIPANT_LEFT_EVENT, success=True, message='웹 서비스 다시 시작',
        command_id='runtime-participant_left-1', cycle_number=3,
    ))


def test_stop_now_announces_one_stopped_event_before_clearing():
    node = _master()
    execution_id = node._execution.execution_id

    node._request_group_stop(after_cycle=False)

    _assert_one_stop(node, execution_id)


def test_the_last_participant_leaving_announces_the_stop():
    """진행 PC 가 바빠 빠져 있고 남은 한 대가 웹 다시 시작 · 「남은 PC 없음」 (145 ①)"""
    node = _master(('pc-b',))
    execution_id = node._execution.execution_id

    _left(node, 'pc-b')

    _assert_one_stop(node, execution_id)


def test_the_master_alone_restarting_its_web_announces_the_stop():
    """W-A10 · floating4 혼자 그룹 연속 · 「프로그램 다시 시작」 · `restart motion-control`"""
    node = _master(('pc-a',))
    execution_id = node._execution.execution_id

    node._handle_local_request({'command': 'bridge_leaving', 'reason': '웹 서비스 다시 시작'})

    _assert_one_stop(node, execution_id)


def test_stop_after_cycle_announces_when_the_release_completes():
    node = _master()
    execution_id = node._execution.execution_id
    node._request_group_stop(after_cycle=True)
    assert _group_stops(node) == [], '회차가 끝나기 전에는 내지 않는다'

    # 회차 끝 · 참가 PC 의 런타임 정지 → 풀기 → 모두 답함
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=execution_id, pc_id='pc-b', event='stopped',
        command_id='runtime-stopped-3', success=True, cycle_number=3,
    ))
    assert node._execution.state == 'releasing'
    assert _group_stops(node) == []
    node._execution.pending_acks.add('pc-a')
    _peer_release_ack(node)

    _assert_one_stop(node, execution_id)


def test_a_once_run_announces_when_the_release_completes():
    node = _master(run_mode='once')
    execution_id = node._execution.execution_id
    node._begin_group_release()
    node._execution.pending_acks.add('pc-a')

    _peer_release_ack(node)

    _assert_one_stop(node, execution_id)


def test_shutdown_announces_the_stop():
    node = _master()
    execution_id = node._execution.execution_id

    node._stop_active_execution_for_shutdown()

    _assert_one_stop(node, execution_id)


def test_the_stop_is_announced_only_once_per_execution():
    """정지 뒤 늦게 도는 정리(제 정지 명령 처리 · 다시 지우기)가 사건을 또 내지 않는다"""
    node = _master()
    execution_id = node._execution.execution_id
    node._request_group_stop(after_cycle=False)

    with node._lock:
        node._execution.execution_id = execution_id      # 같은 실행을 다시 쥐었다 놓는 경우
        node._execution.coordinator_id = 'pc-a'
        node._clear_active_execution()
        node._clear_active_execution()

    assert len(_group_stops(node)) == 1


def test_its_own_stopped_event_does_not_touch_the_next_execution():
    """진행 PC 는 제 사건을 지운 뒤에 받는다 · 새 실행의 장벽·풀기에 끼지 않는다"""
    node = _master()
    node._request_group_stop(after_cycle=False)
    [(announced, _held)] = _group_stops(node)
    next_id = node._execution.begin('pc-a', ('pc-a', 'pc-b'))
    node._execution.state = 'running'

    node._event_callback(announced)

    assert node._execution.execution_id == next_id
    assert node._execution.state == 'running'
    assert node._command_pub.messages[-1].command == 'stop_now', '새 실행에 풀기·정지를 보내지 않는다'


def test_a_participant_letting_go_does_not_announce():
    """진행 PC 가 아닌 PC 가 실행을 놓을 때(빠짐 · 풀기 답) · 나머지는 계속 돈다"""
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._execution = GroupExecution()
    node._execution.execution_id = 'exec-b'
    node._execution.coordinator_id = 'pc-b'
    node._execution.participants = ('pc-a', 'pc-b')
    node._execution.state = 'running'

    node._handle_local_request({'command': 'bridge_leaving', 'reason': '웹 서비스 다시 시작'})

    assert [m.event for m in node._event_pub.messages] == [PARTICIPANT_LEFT_EVENT]
    assert node._execution.execution_id == ''


def test_the_master_leaving_while_others_keep_going_does_not_announce():
    """진행 PC 자신만 빠지고 나머지는 계속 (145 ①) · 스피커 소리도 계속"""
    node = _master(('pc-a', 'pc-b'))
    execution_id = node._execution.execution_id

    node._handle_local_request({'command': 'bridge_leaving', 'reason': '웹 서비스 다시 시작'})
    # 웹이 내려가며 이 PC 재생을 세웠다 · 그 상태가 마지막으로 들어온다
    node._local_status = {'motion_run_status': {
        'group_execution': True, 'execution_id': execution_id, 'phase': 'stopped',
        'state': 'stopped', 'group_cycle_number': 3,
    }}
    node._emit_local_runtime_event()

    assert node._execution.execution_id == execution_id
    assert node._execution.participants == ('pc-b',)
    assert node._event_pub.messages == [], '정지 사건 없음'


def test_a_participating_master_still_reports_its_own_runtime_stop():
    """빠지지 않은 진행 PC 의 런타임 정지는 전처럼 그룹 사건으로 (제 사건으로 전체 풀기 · 123)"""
    node = _master(('pc-a', 'pc-b'))
    node._last_local_event_key = None
    execution_id = node._execution.execution_id
    node._local_status = {'motion_run_status': {
        'group_execution': True, 'execution_id': execution_id, 'phase': 'stopped',
        'state': 'stopped', 'group_cycle_number': 3,
    }}

    node._emit_local_runtime_event()

    assert [(m.event, m.execution_id) for m in node._event_pub.messages] == [('stopped', execution_id)]
