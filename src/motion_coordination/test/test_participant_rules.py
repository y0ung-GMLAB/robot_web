"""그룹 재생에 넣을 PC · 운전 모드의 뜻은 「누가 시작하나」 · 수정 목록 122 (사용자 결정 2026-10-13)

실물 S-10 · 4대 모두 수동 모드에서 사람이 그룹 1회를 눌렀다 · floating1~3 이 「수동 모드」 로
빠지고 floating4 혼자 돌았는데 「그룹 실행 완료」 가 떴다 · 빠졌다는 안내도 없었다.

이제 사람이 누른 그룹 재생은 수동 PC 도 넣고 끔 PC 만 뺀다 · 스케줄이 켠 그룹 재생은
지금처럼 스케줄 PC 만 · rclpy 없이 돈다.
"""

import time

import pytest

from motion_coordination.group_execution import GROUP_PROTOCOL_VERSION, GroupExecution, Member
from motion_coordination.participant_rules import (
    MANUAL_REASON,
    OFF_REASON,
    SOLO_BUSY_REASON,
    STARTED_BY_HUMAN,
    STARTED_BY_SCHEDULE,
    exclusion_reason,
    idle_park_wanted,
    normalize_started_by,
    solo_busy,
    start_summary,
)


def _member(**overrides):
    values = dict(
        pc_id='floating1', boot_id='boot-1', joined=True, is_master=False,
        state='ready', trigger_sync_state='idle', trigger_sync_uncertainty_ms=0.0,
        alarm_grade=0, received_monotonic=time.monotonic(), sequence=1,
        protocol_version=GROUP_PROTOCOL_VERSION, operation_mode='manual',
    )
    values.update(overrides)
    return Member(**values)


def _reason(member, *, started_by, link='online'):
    return exclusion_reason(
        member, link, protocol_version=GROUP_PROTOCOL_VERSION, started_by=started_by,
    )


def test_a_human_group_start_takes_manual_pcs():
    assert _reason(_member(operation_mode='manual'), started_by=STARTED_BY_HUMAN) == ''
    assert _reason(_member(operation_mode='schedule'), started_by=STARTED_BY_HUMAN) == ''


def test_a_schedule_group_start_takes_only_schedule_pcs():
    assert _reason(_member(operation_mode='manual'), started_by=STARTED_BY_SCHEDULE) == MANUAL_REASON
    assert _reason(_member(operation_mode='schedule'), started_by=STARTED_BY_SCHEDULE) == ''


@pytest.mark.parametrize('started_by', [STARTED_BY_HUMAN, STARTED_BY_SCHEDULE])
def test_off_pcs_never_join(started_by):
    assert _reason(_member(operation_mode='off'), started_by=started_by) == OFF_REASON
    assert OFF_REASON == '끔 모드', '화면 글자(끔)와 같게'


@pytest.mark.parametrize('phase', ['running', 'initializing', 'waiting', 'repeat_waiting', 'stopping'])
def test_a_pc_busy_with_its_own_run_is_left_out_with_a_reason(phase):
    """(나) 그 PC 에서 단독 재생 중이면 그 PC 만 뺀다"""
    assert _reason(_member(motion_phase=phase), started_by=STARTED_BY_HUMAN) == SOLO_BUSY_REASON


@pytest.mark.parametrize('phase', ['', 'idle', 'stopped', 'completed', 'error', 'group_join_ready', 'group_armed'])
def test_resting_or_group_phases_are_not_busy(phase):
    assert solo_busy(phase) is False
    assert _reason(_member(motion_phase=phase), started_by=STARTED_BY_HUMAN) == ''


def test_link_alarm_and_version_come_first():
    assert _reason(None, started_by=STARTED_BY_HUMAN) == '통신 단절'
    assert _reason(_member(), started_by=STARTED_BY_HUMAN, link='offline') == '통신 단절'
    assert _reason(_member(), started_by=STARTED_BY_HUMAN, link='warning') == '응답 지연'
    assert _reason(_member(alarm_grade=2), started_by=STARTED_BY_HUMAN) == 'Servo 알람 2등급'
    assert _reason(_member(protocol_version=1), started_by=STARTED_BY_HUMAN).startswith('버전 불일치')


def test_an_unknown_starter_is_treated_as_the_schedule():
    """모르면 수동 PC 를 빼는 쪽 · 사람이 만지는 중일 수 있다"""
    assert normalize_started_by('') == STARTED_BY_SCHEDULE
    assert normalize_started_by(None) == STARTED_BY_SCHEDULE
    assert normalize_started_by('HUMAN') == STARTED_BY_HUMAN


def test_the_execution_remembers_who_started_it_for_rejoin():
    """(라) 복귀도 시작한 쪽 규칙 · 실행이 기억한다"""
    execution = GroupExecution()
    assert execution.started_by == STARTED_BY_SCHEDULE
    execution.begin('pc-a', ['pc-a', 'pc-b'], started_by='human')
    assert execution.started_by == STARTED_BY_HUMAN
    execution.reset()
    assert execution.started_by == STARTED_BY_SCHEDULE


def test_the_start_notice_names_the_count_and_who_was_left_out():
    """(다) 결과 알림에도 · 「참가 N대 · 빠짐 …」"""
    assert start_summary(('a', 'b', 'c'), {}) == '참가 3대'
    assert start_summary(('a',), {'c': '끔 모드', 'b': '단독 재생 중'}) == (
        '참가 1대 · 빠짐 b(단독 재생 중), c(끔 모드)'
    )


def test_idle_park_goes_out_only_for_a_schedule_end_without_a_group_run():
    """사용자 2026-10-13 · 도는 그룹 없이 구간이 끝나도 PC 마다 주차 → 서보 OFF"""
    assert idle_park_wanted(after_cycle=True, reason='schedule_end', execution_id='') is True
    assert idle_park_wanted(after_cycle=True, reason='schedule_end', execution_id='exec-a') is False, '도는 그룹은 옛 길'
    assert idle_park_wanted(after_cycle=True, reason='', execution_id='') is False, '사람이 누른 정지는 그대로 거절'
    assert idle_park_wanted(after_cycle=False, reason='schedule_end', execution_id='') is False
