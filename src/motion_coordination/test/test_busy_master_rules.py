"""바쁜 마스터 · 늦은 거절 · 미리 빼기 · 규칙만 · 수정 목록 136 (실물 V-4 · V-5 · V-8 · 2026-10-13/14)

V-4  floating4(마스터) 단독 연속 중 그룹 「1회 시작」 → 마스터가 빠지지 않고 제 준비 답에서 「사람 조작 중」 →
     시작 취소 → 정리 중 floating2 의 늦은 준비 거절이 「참가 PC 오류」 → 모든 참가 PC 에 즉시 정지 →
     마스터의 단독 재생까지 섬 · 그룹 오류 잠김
V-5  같은 길 · 마스터 조그가 97.5° 에서 섬
V-8  복귀 권유(`join`)를 마스터가 제 것으로 처리 → 참가 목록이 {마스터, floating1} 로 덮임 → floating1 의
     복귀 거절이 「참가 PC 명령 실패」 → 전체 정지

rclpy 없이 돈다 · 노드에 붙인 시험은 `test_busy_master_group.py` (미니 PC · WSL).
"""

import time

import pytest

from motion_coordination.group_execution import (
    GROUP_PROTOCOL_VERSION,
    GroupExecution,
    Member,
    is_own_join,
    late_refusal_reason,
)
from motion_coordination.participant_rules import (
    SOLO_BUSY_REASON,
    STARTED_BY_HUMAN,
    exclusion_reason,
    local_start_blocker,
    self_exclusion_reason,
)


def _member(**overrides):
    values = dict(
        pc_id='floating2', boot_id='boot-2', joined=True, is_master=False,
        state='ready', trigger_sync_state='idle', trigger_sync_uncertainty_ms=0.0,
        alarm_grade=0, received_monotonic=time.monotonic(), sequence=1,
        protocol_version=GROUP_PROTOCOL_VERSION, operation_mode='manual',
    )
    values.update(overrides)
    return Member(**values)


def test_protocol_is_eight():
    """하트비트 칸이 늘고 진행 PC 가 참가 목록 밖일 수 있다 · 옛 PC 와 섞이면 안 된다"""
    assert GROUP_PROTOCOL_VERSION == 8


# ⑤ 선택 때 하트비트 `start_blocker` 로 미리 뺀다 ------------------------------------ #

def test_a_pc_that_says_it_cannot_start_is_left_out_before_preparation():
    blocker = '실행 준비 안 됨 · 모터 설정과 조인트 매핑을 저장해 확정하세요'
    member = _member(start_blocker=blocker)
    assert exclusion_reason(
        member, 'online', protocol_version=GROUP_PROTOCOL_VERSION, started_by=STARTED_BY_HUMAN,
    ) == blocker
    assert exclusion_reason(
        _member(), 'online', protocol_version=GROUP_PROTOCOL_VERSION, started_by=STARTED_BY_HUMAN,
    ) == ''


def test_solo_run_still_reads_as_solo_busy_before_the_blocker():
    member = _member(motion_phase='running', start_blocker='사람 조작 중 · 단독 재생')
    assert exclusion_reason(
        member, 'online', protocol_version=GROUP_PROTOCOL_VERSION, started_by=STARTED_BY_HUMAN,
    ) == SOLO_BUSY_REASON


@pytest.mark.parametrize('status, expected', [
    ({}, ''),
    ({'start_blocker': '실행 준비 안 됨 · 모터 상태를 아직 수신하지 못했습니다'},
     '실행 준비 안 됨 · 모터 상태를 아직 수신하지 못했습니다'),
    ({'safety_status': {'manual_activity_modes': ['jog']}, 'start_blocker': '실행 준비 안 됨 · x'},
     '사람 조작 중 · 조그 이동'),
    ({'safety_status': {'command_owner': 'stream'}}, '사람 조작 중 · 페이더'),
    ({'motion_run_status': {'state': 'running', 'group_execution': True}}, ''),
])
def test_the_heartbeat_blocker_comes_from_one_local_status(status, expected):
    assert local_start_blocker(status) == expected


# ① 마스터 자신 ------------------------------------------------------------------------- #

@pytest.mark.parametrize('run, safety, blocker, expected', [
    ({'state': 'running'}, {}, '', SOLO_BUSY_REASON),                              # V-4
    ({'state': 'initializing'}, {}, '', SOLO_BUSY_REASON),
    ({'state': 'idle'}, {'manual_activity_modes': ['jog']}, '', '사람 조작 중 · 조그 이동'),   # V-5
    ({'state': 'idle'}, {'command_owner': 'stream'}, '', '사람 조작 중 · 페이더'),
    ({'state': 'idle'}, {}, '실행 준비 안 됨 · x', '실행 준비 안 됨 · x'),
    ({'state': 'idle'}, {}, '', ''),
    ({'state': 'completed', 'group_execution': True}, {}, '', ''),                 # 끝난 그룹 · 쉬는 중
])
def test_the_master_is_judged_like_every_other_pc(run, safety, blocker, expected):
    assert self_exclusion_reason(run, safety, blocker) == expected


def test_a_busy_master_can_coordinate_without_participating():
    execution = GroupExecution()
    with pytest.raises(ValueError, match='참가 목록'):
        execution.begin('floating4', ('floating1', 'floating2'))
    execution_id = execution.begin(
        'floating4', ('floating1', 'floating2'), coordinator_participates=False,
    )
    assert execution_id
    assert execution.coordinator_id == 'floating4'
    assert execution.participants == ('floating1', 'floating2')


def test_the_coordinator_is_dropped_only_when_asked():
    execution = GroupExecution()
    execution.begin('floating4', ('floating2', 'floating4'))
    assert execution.exclude({'floating4': '준비 거절'}) == ()
    assert execution.exclude({'floating4': '준비 거절'}, allow_coordinator=True) == ('floating4',)
    assert execution.participants == ('floating2',)
    assert execution.excluded == {'floating4': '준비 거절'}


# ③ 늦은 거절 · V-4 ------------------------------------------------------------------- #

def _late(**overrides):
    values = dict(
        event='rejected', command_id='cmd-prepare', state='preparing',
        pending_command='prepare', pending_command_id='cmd-prepare',
        prepare_command_id='cmd-prepare',
    )
    values.update(overrides)
    return late_refusal_reason(**values)


def test_a_prepare_refusal_while_preparing_is_handled_as_before():
    assert _late() == ''


def test_a_prepare_refusal_arriving_while_releasing_is_ignored():
    """V-4 · 마스터 취소 뒤 floating2 의 늦은 준비 거절 · 전에는 전체 정지 + 잠금"""
    assert _late(
        state='releasing', pending_command='cancel_before_start', pending_command_id='cmd-release',
    ) == '정리 중 늦은 거절'


def test_a_refusal_of_the_release_itself_is_still_taken_seriously():
    assert _late(
        command_id='cmd-release', state='releasing',
        pending_command='cancel_before_start', pending_command_id='cmd-release',
    ) == ''


def test_a_prepare_refusal_after_preparation_is_ignored():
    assert _late(state='initializing', pending_command='initialize_at', pending_command_id='cmd-init') \
        == '준비 단계 뒤 늦은 준비 거절'
    # 준비 아닌 명령의 거절은 전처럼
    assert _late(
        command_id='cmd-init', state='initializing',
        pending_command='initialize_at', pending_command_id='cmd-init',
    ) == ''


def test_other_events_are_never_late_refusals():
    assert _late(event='stopped', state='releasing', pending_command='cancel_before_start') == ''


# V-8 · 진행 PC 는 제 복귀 권유를 처리하지 않는다 ----------------------------------------- #

def test_the_master_ignores_its_own_join_invitation():
    assert is_own_join('join', 'floating4', 'floating4') is True
    assert is_own_join('join', 'floating4', 'floating1') is False
    assert is_own_join('prepare', 'floating4', 'floating4') is False
