"""그룹 명령에 초기 위치 이동 시간을 싣는다 · 마스터 재생 화면의 5/7/10 · 0 = PC마다 조인트 매핑 값 (2026-10-12)"""

from types import SimpleNamespace

from motion_coordination import coordination_node
from motion_coordination.group_execution import GROUP_PROTOCOL_VERSION, GroupExecution


def test_execution_keeps_the_chosen_time_and_defaults_to_mapping():
    execution = GroupExecution()
    execution.begin('pc-a', ['pc-a', 'pc-b'], initial_move_time_sec=7.0)
    assert execution.initial_move_time_sec == 7.0
    execution.reset()
    assert execution.initial_move_time_sec == 0.0
    execution.begin('pc-a', ['pc-a'], initial_move_time_sec=-3)
    assert execution.initial_move_time_sec == 0.0


def test_received_command_reads_the_time_and_old_commands_mean_mapping():
    read = coordination_node._message_initial_move_time
    assert read(SimpleNamespace(initial_move_time_sec=10.0)) == 10.0
    assert read(SimpleNamespace(initial_move_time_sec=0.0)) == 0.0
    assert read(SimpleNamespace()) == 0.0


def test_protocol_version_moved_on_with_the_new_field():
    """칸이 늘었다(6) · 그룹 동작이 바뀌었다(7 · 수정 목록 122 · 123) · 같은 버전끼리만 그룹"""
    assert GROUP_PROTOCOL_VERSION >= 6
    assert GROUP_PROTOCOL_VERSION == 10
