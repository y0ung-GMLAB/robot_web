"""빠진 PC 가 같은 실행에 다시 붙는다 · 수정 목록 181

실물 NY 2026-11-07 15:08:15 공유기 Wi-Fi 4대 동시 끊김(약 112 s) → 마스터가 floating2·3·4 를 뺌 ·
뺄 때 보낸 풀기(drop release)가 망이 돌아온 뒤 도착 → 슬레이브가 그 실행을 「취소됨」 으로 잠금 ·
그 뒤 복귀 권유(`join` · 같은 실행 번호)를 「정지된 그룹 실행의 지연 명령」 으로 버림 · 30 s 뒤 마스터가
또 풀기 → 또 잠금 · 스스로 못 빠져나왔다(연동 서비스를 재시작해도).
"""

from types import SimpleNamespace

from motion_coordination_interfaces.msg import GroupCommand

from motion_coordination.group_execution import GroupExecution, drop_release_command_id, is_drop_release
from test_coordination_node import _member, _node, _Publisher


def _slave():
    node = _node()
    node._config.pc_id = 'pc-b'
    node._joined = True
    node._event_pub = _Publisher()
    node._registry.update(_member('pc-a', is_master=True))
    node._execution = GroupExecution()
    node._execution.begin('pc-a', ('pc-a', 'pc-b', 'pc-c'), run_mode='continuous')
    node._execution.execution_id = 'exec-a'
    node._execution.state = 'running'
    node._execution.cycle_number = 10
    node._command_dispatcher = SimpleNamespace(submit=lambda message, urgent_stop=False: True)
    # 빠진 PC 는 마스터의 새 참가 목록을 못 받았다 · 제 로컬 재생이 그 실행을 쥐고 있어 풀기가 맞는다(실물)
    node._local_group_execution_id = lambda: 'exec-a'
    rejoins = []
    node._accept_rejoin = lambda message, participants: rejoins.append(message.command_id)
    return node, rejoins


def _command(command, command_id, cycle=10):
    return GroupCommand(
        group_id='stage-a', execution_id='exec-a', coordinator_id='pc-a',
        command=command, command_id=command_id, cycle_number=cycle,
        participant_ids=['pc-a', 'pc-b'],
    )


def test_drop_release_ids_are_recognised():
    assert is_drop_release('cancel_before_start', drop_release_command_id()) is True
    assert is_drop_release('cancel_before_start', 'cmd-stop') is False
    assert is_drop_release('stop_now', drop_release_command_id()) is False


def test_a_dropped_pc_accepts_the_join_for_the_same_execution():
    node, rejoins = _slave()
    release = _command('cancel_before_start', drop_release_command_id())
    node._command_callback(release)
    assert 'exec-a' in node._cancelled_execution_ids, '풀기는 지금처럼 그 실행을 세운다'

    join = _command('join', 'cmd-join-1', cycle=12)
    node._command_callback(join)
    node._process_group_command(join)

    assert rejoins == ['cmd-join-1']
    assert 'exec-a' not in node._cancelled_execution_ids


def test_other_late_commands_of_the_dropped_execution_are_still_dropped():
    node, rejoins = _slave()
    node._command_callback(_command('cancel_before_start', drop_release_command_id()))
    starts = []
    node._call_local_control = lambda payload, **_kwargs: starts.append(payload) or {'success': True}
    node._process_group_command(_command('start_at', 'cmd-start-late', cycle=11))
    assert starts == [] and rejoins == []
    assert 'exec-a' in node._cancelled_execution_ids


def test_a_real_stop_after_the_drop_still_refuses_the_join():
    node, rejoins = _slave()
    node._command_callback(_command('cancel_before_start', drop_release_command_id()))
    node._command_callback(_command('stop_now', 'cmd-stop'))
    join = _command('join', 'cmd-join-2', cycle=12)
    node._process_group_command(join)
    assert rejoins == []
    assert 'exec-a' in node._cancelled_execution_ids


def test_the_loop_of_release_then_invite_now_ends_at_the_first_invite():
    """실물 15:47~15:52 · 권유 → 버림 → 30 s 뒤 풀기 → 잠금 → 권유 → 버림 … · 이제 권유를 받는다"""
    node, rejoins = _slave()
    for round_number in range(3):
        node._command_callback(_command('cancel_before_start', drop_release_command_id()))
        join = _command('join', f'cmd-join-loop-{round_number}', cycle=12 + round_number)
        node._command_callback(join)
        node._process_group_command(join)
    assert rejoins == ['cmd-join-loop-0', 'cmd-join-loop-1', 'cmd-join-loop-2']


# --------------------------------------------------------------------------- #
# 끊김 시험 C (2026-11-08) · 스스로 잇기 실패로 혼자 빠진 PC 도 같은 실행으로 돌아온다
#
# 실물 · floating3 이 회차 끝 직후 다시 붙음 → 진행 PC 가 아직 안 보여 스스로 잇다가 A 로 빠짐 · 진행 PC 가
# 30 s 마다 보낸 `join` 을 「정지된 그룹 실행의 지연 명령」 으로 버려 그 실행이 끝날 때까지 서 있었다.
# --------------------------------------------------------------------------- #

def _left(node, monkeypatch, reason, **kwargs):
    import motion_coordination.coordination_node as coordination_node
    from test_coordination_node import _InlineThread
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._leave_group_execution(reason, **kwargs)
    assert node._execution.execution_id == ''
    assert 'exec-a' in node._cancelled_execution_ids


def test_a_pc_that_left_because_its_own_continuation_failed_accepts_the_join(monkeypatch):
    node, rejoins = _slave()
    _left(node, monkeypatch, '스스로 잇기 · 시작 예약 실패 · 그룹 모션 시작 트리거가 이미 지났습니다', rejoinable=True)

    join = _command('join', 'cmd-join-autonomy', cycle=12)
    node._command_callback(join)
    node._process_group_command(join)

    assert rejoins == ['cmd-join-autonomy']
    assert 'exec-a' not in node._cancelled_execution_ids


def test_a_pc_that_was_taken_out_for_other_reasons_still_refuses_the_join(monkeypatch):
    """사람이 뺌 · 웹 재시작 · 모터 문제로 빠진 것은 지금처럼 다시 안 들어온다"""
    node, rejoins = _slave()
    _left(node, monkeypatch, '모터 상태에 없음')

    join = _command('join', 'cmd-join-motor', cycle=12)
    node._process_group_command(join)

    assert rejoins == []
    assert 'exec-a' in node._cancelled_execution_ids


def test_a_pc_removed_by_a_person_still_refuses_the_join():
    node, rejoins = _slave()
    node._command_callback(_command('cancel_before_start', 'cmd-remove-by-person'))

    join = _command('join', 'cmd-join-person', cycle=12)
    node._process_group_command(join)

    assert rejoins == []
    assert 'exec-a' in node._cancelled_execution_ids


def test_a_real_stop_after_an_autonomy_drop_refuses_the_join(monkeypatch):
    node, rejoins = _slave()
    _left(node, monkeypatch, '스스로 잇기 실패 · 주기를 모릅니다', rejoinable=True)
    node._command_callback(_command('stop_now', 'cmd-stop-after'))

    node._process_group_command(_command('join', 'cmd-join-after-stop', cycle=12))

    assert rejoins == []


# --------------------------------------------------------------------------- #
# 끊김 시험 Q (실물 NY 2026-11-08 19:30 floating4) · 웹 끊김으로 스스로 빠진 PC 도 같은 실행으로 돌아온다
# --------------------------------------------------------------------------- #

def _bridge_lost(node, monkeypatch):
    import motion_coordination.coordination_node as coordination_node
    from test_coordination_node import _InlineThread
    monkeypatch.setattr(coordination_node.threading, 'Thread', _InlineThread)
    node._call_local_control = lambda payload, **_kwargs: {'success': True}
    node._drop_self_for_bridge_loss('마지막 성공 2839ms 전 · 연속 실패 3회', moving=True)
    assert node._execution.execution_id == ''
    assert 'exec-a' in node._cancelled_execution_ids


def test_a_pc_that_left_because_its_web_was_lost_accepts_the_join(monkeypatch):
    node, rejoins = _slave()
    _bridge_lost(node, monkeypatch)

    join = _command('join', 'cmd-join-bridge', cycle=12)
    node._command_callback(join)
    node._process_group_command(join)

    assert rejoins == ['cmd-join-bridge']
    assert 'exec-a' not in node._cancelled_execution_ids


def test_a_real_stop_after_a_web_loss_refuses_the_join(monkeypatch):
    node, rejoins = _slave()
    _bridge_lost(node, monkeypatch)
    node._command_callback(_command('stop_now', 'cmd-stop-after-bridge'))

    node._process_group_command(_command('join', 'cmd-join-after-bridge-stop', cycle=12))

    assert rejoins == []
