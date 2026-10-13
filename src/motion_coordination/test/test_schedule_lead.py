"""그룹 예약 여유 · 진행 PC 자신의 늦은 확인 · 수정 목록 130

실물 2026-10-13 floating4 (모터 있는 PC 는 마스터 혼자 · floating1~3 준비 거절로 빠짐)

    19:18     첫 「1회 시작」 · 됨
    19:20:03  같은 시작 · 준비 거절 3대 뺌 → 1.4 s 뒤 「그룹 예약 확인 제한시간 초과 · floating4」 → 잠김
    19:20:14 · 19:23:33 · 19:24:22 · 19:26:41  같음 · 매번 「그룹 오류 해제」 가 필요

예약 여유는 늘 0.5 s(확인 마감 0.4 s)였고 진행 PC 자신도 그 안에 HTTP · ROS 로 답해야 했다.

여기는 rclpy 없이 도는 규칙만 · 노드에 붙인 시험은 `test_coordination_node.py` (미니 PC).
"""

import pytest

from motion_coordination.group_execution import GroupExecution
from motion_coordination.schedule_lead import (
    INITIALIZE_LEAD_MIN_SEC,
    LATENCY_WINDOW,
    LEAD_MAX_SEC,
    ScheduleLeadPlanner,
    command_kind,
    is_timing_rejection,
    only_self_late,
)


def _lead(planner, kind, participants=('floating4',)):
    return planner.lead_sec(kind, participants, base_lead_sec=0.5, ack_margin_sec=0.1)


def test_initialize_lead_has_a_floor_before_anything_is_measured():
    planner = ScheduleLeadPlanner()
    assert _lead(planner, 'initialize') == pytest.approx(INITIALIZE_LEAD_MIN_SEC)
    # 회차 시작 · 회차 초기화는 설정값 그대로(가벼운 예약)
    assert _lead(planner, 'schedule') == pytest.approx(0.5)


def test_a_slow_own_ack_grows_the_next_lead():
    planner = ScheduleLeadPlanner()
    # 마스터 자신이 0.9 s 걸렸다(실물에서 0.4 s 를 넘긴 길) → 다음은 두 배 + 마감 여백
    planner.record('initialize', 'floating4', 0.9)
    assert _lead(planner, 'initialize') == pytest.approx(1.9)
    planner.record('schedule', 'floating4', 0.35)
    assert _lead(planner, 'schedule') == pytest.approx(0.8)
    assert planner.snapshot()['last_lead_sec'] == {
        'initialize': pytest.approx(1.9), 'schedule': pytest.approx(0.8),
    }


def test_the_lead_is_capped_and_old_samples_fall_out():
    planner = ScheduleLeadPlanner()
    planner.record('initialize', 'floating4', 10.0)
    assert _lead(planner, 'initialize') == pytest.approx(LEAD_MAX_SEC)
    for _ in range(LATENCY_WINDOW):
        planner.record('initialize', 'floating4', 0.05)
    assert _lead(planner, 'initialize') == pytest.approx(INITIALIZE_LEAD_MIN_SEC)


def test_only_participants_count():
    planner = ScheduleLeadPlanner()
    planner.record('schedule', 'floating1', 1.0)   # 이번에 빠진 PC
    assert _lead(planner, 'schedule', ('floating4',)) == pytest.approx(0.5)
    assert _lead(planner, 'schedule', ('floating1', 'floating4')) == pytest.approx(2.1)


def test_bad_samples_are_ignored():
    planner = ScheduleLeadPlanner()
    for value in (-1.0, float('nan'), 'x', None):
        planner.record('schedule', 'floating4', value)
    planner.record('', 'floating4', 1.0)
    planner.record('schedule', '', 1.0)
    assert planner.worst('schedule', ('floating4',)) == 0.0


def test_only_the_masters_own_late_ack_is_not_a_group_fault():
    assert only_self_late(['floating4'], 'floating4', 'initialize_at') is True
    assert only_self_late(['floating4'], 'floating4', 'cycle_initialize_at') is True
    assert only_self_late(['floating4'], 'floating4', 'start_at') is True
    # 다른 PC 가 늦으면 옛 그대로(망 · 상대 고장일 수 있다)
    assert only_self_late(['floating2'], 'floating4', 'initialize_at') is False
    assert only_self_late(['floating2', 'floating4'], 'floating4', 'initialize_at') is False
    # 준비 확인은 124 가 따로 본다
    assert only_self_late(['floating4'], 'floating4', 'prepare') is False


def test_command_kinds_and_timing_rejections():
    assert command_kind('initialize_at') == 'initialize'
    assert command_kind('start_at') == 'schedule'
    assert command_kind('cycle_initialize_at') == 'schedule'
    assert command_kind('prepare') == ''
    assert is_timing_rejection('그룹 예약 트리거의 준비 여유가 부족합니다') is True
    assert is_timing_rejection('그룹 초기 위치 이동 예약 트리거가 이미 지났습니다') is True
    assert is_timing_rejection('motion_run_manager response timeout') is True
    assert is_timing_rejection('현재 프로젝트의 실행 준비가 끝나지 않았습니다') is False
    assert is_timing_rejection('') is False


def test_group_execution_uses_the_given_lead_but_never_less_than_the_setting():
    execution = GroupExecution(start_lead_sec=0.5)
    execution.begin('floating4', ('floating4',))
    execution.mark_ready('floating4')
    action = execution.initialize_action(now=100.0, lead_sec=1.9)
    assert action.scheduled_at == pytest.approx(101.9)

    execution = GroupExecution(start_lead_sec=0.5)
    execution.begin('floating4', ('floating4',))
    execution.mark_ready('floating4')
    action = execution.initialize_action(now=100.0, lead_sec=0.1)
    assert action.scheduled_at == pytest.approx(100.5)
