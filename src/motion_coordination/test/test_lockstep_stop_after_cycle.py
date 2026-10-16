"""회차 맞춤 · 「회차 후 정지」 는 가장 긴 PC 의 회차 끝까지 · 수정 목록 154 · 155

실물 2026-10-16 14:37:02 · floating3(38 s) · floating4(17 s) · 스케줄 그룹 연속 · 구간 끝 `stop_after_cycle` 이
두 PC 재생 중에 도착 · floating4 회차 끝 → 진행 PC 가 그 `stopped` 를 보고 곧바로 풀어 floating3 의 마지막
회차가 17.18 / 37.98 s 에서 잘렸다.

- 회차 맞춤 PC 런타임은 그룹 전체 회차 후 정지면 제 회차 뒤 장벽(`motion_completed`)에 머문다 ·
  진행 PC 는 그 보고를 장벽에 적고 **모든** PC 가 끝났을 때만 푼다
- 진짜 정지(사람 · 오류 · 회차 사이에 받아 바로 선 것)는 회차 후 정지 중에도 바로 푼다
- 각자 재생은 그대로 · 모두 제 회차를 끝내고 멈춰야 푼다
- 연동 노드는 런타임에 「그룹 전체」 를 알린다(`group_wide`) · 슬레이브 혼자 1등급 알람은 옛 그대로
"""

from motion_coordination_interfaces.msg import GroupCommand, GroupEvent

from motion_coordination.group_execution import GroupExecution
from test_coordination_node import _node, _peer_release_ack, _Publisher


def _master(*, sync_mode='lockstep'):
    """pc-a = 진행 PC · 긴 애니(38 s) · pc-b = 짧은 애니(17 s) · 3회차 재생 중"""
    node = _node()
    node._joined = True
    node._command_pub = _Publisher()
    node._event_pub = _Publisher()
    node._note_excluded = lambda *_args, **_kwargs: None
    node.local_calls = []
    node._call_local_control = lambda payload, **_kwargs: (
        node.local_calls.append(dict(payload)) or {'success': True}
    )
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a', 'pc-b'), run_mode='continuous', sync_mode=sync_mode)
    node._execution.state = 'running_independent' if sync_mode == 'independent' else 'running'
    node._execution.cycle_number = 3
    return node


def _event(node, pc_id, event, *, cycle=3, message=''):
    node._event_callback(GroupEvent(
        group_id='stage-a', execution_id=node._execution.execution_id, pc_id=pc_id,
        event=event, command_id=f'runtime-{event}-{cycle}', success=True,
        cycle_number=cycle, message=message or event,
    ))


def _released(node):
    return [m for m in node._command_pub.messages if m.command == 'cancel_before_start']


def test_the_short_pc_finishing_does_not_cut_the_long_pc():
    node = _master()
    node._request_group_stop(after_cycle=True, reason='schedule_end')
    assert node._execution.stop_after_cycle is True

    # 짧은 PC(17 s) 회차 끝 · 장벽에 선다 · 긴 PC 는 아직 재생 중
    _event(node, 'pc-b', 'motion_completed')
    assert node._execution.state == 'running'
    assert _released(node) == [], '긴 PC 재생 중에는 풀지 않는다'

    # 긴 PC(38 s) 회차 끝 · 그때 모두 푼다
    _event(node, 'pc-a', 'motion_completed')
    assert node._execution.state == 'releasing'
    assert len(_released(node)) == 1
    node._execution.pending_acks.add('pc-a')
    _peer_release_ack(node)
    assert node._execution.execution_id == ''


def test_the_master_tells_its_runtime_the_stop_is_group_wide():
    node = _master()
    node._request_group_stop(after_cycle=True, reason='schedule_end')
    [local] = [call for call in node.local_calls if call['command'] == 'stop_after_cycle']
    assert local['group_wide'] is True
    assert local['reason'] == 'schedule_end'
    [published] = [m for m in node._command_pub.messages if m.command == 'stop_after_cycle']
    assert published.stop_reason == 'schedule_end'


def test_a_real_stop_during_stop_after_cycle_still_releases_at_once():
    """회차 후 정지를 기다리는 중 · 긴 PC 가 사람 정지 · 오류로 섰다 · 바로 푼다"""
    node = _master()
    node._request_group_stop(after_cycle=True, reason='schedule_end')
    _event(node, 'pc-b', 'motion_completed')
    assert _released(node) == []

    _event(node, 'pc-a', 'stopped', message='그룹 실행 정지')

    assert node._execution.state == 'releasing'
    assert len(_released(node)) == 1


def test_stop_now_during_stop_after_cycle_stops_every_pc_at_once():
    node = _master()
    node._request_group_stop(after_cycle=True, reason='schedule_end')
    _event(node, 'pc-b', 'motion_completed')

    node._request_group_stop(after_cycle=False)

    assert [m.command for m in node._command_pub.messages][-1] == 'stop_now'
    assert node._execution.execution_id == ''


def test_independent_release_still_waits_for_every_pc_to_stop():
    node = _master(sync_mode='independent')
    node._request_group_stop(after_cycle=True, reason='schedule_end')

    _event(node, 'pc-b', 'stopped', message='구간 끝 · 회차 후 정지')
    assert _released(node) == [], '각자 재생 · 다른 PC 가 아직 돈다'

    _event(node, 'pc-a', 'stopped', message='구간 끝 · 회차 후 정지')
    assert node._execution.state == 'releasing'
    assert len(_released(node)) == 1


def test_a_slave_tells_its_runtime_the_received_stop_is_group_wide():
    node = _node()
    node._config.pc_id = 'pc-b'
    node._joined = True
    node._event_pub = _Publisher()
    node._execution.activate_claim('exec-a', 'pc-a', ('pc-a', 'pc-b'))
    node._execution.state = 'running'
    calls = []
    node._call_local_control = lambda payload, **_kwargs: (
        calls.append(dict(payload)) or {'success': True, 'message': 'ok'}
    )

    node._process_group_command(GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command='stop_after_cycle', command_id='cmd-stop', stop_reason='schedule_end',
        participant_ids=['pc-a', 'pc-b'],
    ))

    [local] = calls
    assert local['command'] == 'stop_after_cycle'
    assert local['group_wide'] is True
    assert local['reason'] == 'schedule_end'
    [event] = node._event_pub.messages
    assert event.event == 'stop_after_cycle_accepted'
