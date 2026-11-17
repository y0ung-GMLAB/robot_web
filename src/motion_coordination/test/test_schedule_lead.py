"""그룹 예약 여유 · 진행 PC 자신의 늦은 확인 · 수정 목록 130

실물 2026-10-13 floating4 (모터 있는 PC 는 마스터 혼자 · floating1~3 준비 거절로 빠짐)

    19:18     첫 「1회 시작」 · 됨
    19:20:03  같은 시작 · 준비 거절 3대 뺌 → 1.4 s 뒤 「그룹 예약 확인 제한시간 초과 · floating4」 → 잠김
    19:20:14 · 19:23:33 · 19:24:22 · 19:26:41  같음 · 매번 「그룹 오류 해제」 가 필요

예약 여유는 늘 0.5 s(확인 마감 0.4 s)였고 진행 PC 자신도 그 안에 HTTP · ROS 로 답해야 했다.

수정 목록 207 · 진행 PC 자신의 예약은 이 프로세스 안에서 재생 관리자에 바로 간다 · 그 길 때문에 덧댄 회차
초기화 바닥과 회차 초기화 다시 예약(153 ②)을 없앴다 · 초기 위치 바닥(3 s)은 남김(모든 PC 가 확인 뒤 재생 계획을
짓는다 · 164) · 1회차 시작 바닥(3 s)도 남김(잰 값이 없을 때의 기본값 · 사용자 결정 179) · 재시작 뒤 그 종류를 잰
값이 없으면 같은 PC 의 다른 예약 종류에서 방금 잰 값.

여기는 rclpy 없이 도는 규칙만 · 노드에 붙인 시험은 `test_coordination_node.py` (미니 PC).
"""

import pytest

from motion_coordination.group_execution import GroupExecution
from motion_coordination.schedule_lead import (
    FIRST_START_LEAD_MIN_SEC,
    INITIALIZE_LEAD_MIN_SEC,
    LATENCY_WINDOW,
    LEAD_MAX_SEC,
    ScheduleLeadPlanner,
    command_kind,
    is_not_accepted_rejection,
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
    # 마스터 자신이 1.6 s 걸렸다 → 다음은 두 배 + 마감 여백(바닥 3 s 위)
    planner.record('initialize', 'floating4', 1.6)
    assert _lead(planner, 'initialize') == pytest.approx(3.3)
    planner.record('schedule', 'floating4', 0.35)
    assert _lead(planner, 'schedule') == pytest.approx(0.8)
    assert planner.snapshot()['last_lead_sec'] == {
        'initialize': pytest.approx(3.3), 'schedule': pytest.approx(0.8),
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


def test_command_kinds():
    assert command_kind('initialize_at') == 'initialize'
    assert command_kind('start_at') == 'schedule'
    assert command_kind('cycle_initialize_at') == 'cycle_initialize'
    assert command_kind('prepare') == ''


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


# ---------------------------------------------------------------------- #
# 수정 목록 153 · 회차 맞춤 그룹 회차 사이 · 마스터 자신의 회차 초기화 확인이 늦어 그룹 전체 취소
#
# 실물 2026-10-16 14:35:05 floating3(마스터 38 s) · floating4(17 s) · 스케줄 그룹 연속 · 3회차 끝
# 「floating3 자신의 예약 확인 늦음 · cycle_initialize_at · 679 ms 안에 답 없음」 → 취소 → 약 40 s 멈춤 ·
# 그때 여유 0.83 s(`schedule` 종류 · 바닥 0 · 자기 확인 253~363 ms)
# ---------------------------------------------------------------------- #

def test_cycle_initialize_has_no_floor_anymore():
    """바닥 1.5 s 는 진행 PC 자신의 길(DDS → HTTP → 웹) 탓이었다 · 207 뒤로 잰 값 · 설정값만"""
    planner = ScheduleLeadPlanner()
    assert _lead(planner, 'cycle_initialize') == pytest.approx(0.5)
    # 실물 값 · 363 ms 를 재면 두 배 + 마감 여백
    planner.record('cycle_initialize', 'floating4', 0.363)
    assert _lead(planner, 'cycle_initialize') == pytest.approx(0.826)
    assert _lead(planner, 'schedule') == pytest.approx(0.826), '안 잰 종류는 같은 PC 의 다른 예약 값'


def test_a_measured_kind_uses_only_its_own_samples():
    """잰 종류는 제 값만 · 안 잰 종류만 같은 PC 의 다른 예약 값(재시작 직후) · 207"""
    planner = ScheduleLeadPlanner()
    planner.record('initialize', 'floating4', 1.6)
    assert _lead(planner, 'cycle_initialize') == pytest.approx(3.3)
    planner.record('cycle_initialize', 'floating4', 0.2)
    assert _lead(planner, 'cycle_initialize') == pytest.approx(0.5)
    assert _lead(planner, 'initialize') == pytest.approx(3.3)
    assert set(planner.snapshot()['recent_ack_ms']) == {'initialize', 'cycle_initialize'}


def test_only_rejections_that_surely_did_not_book_are_retried():
    """스스로 잇기(178 · 끊김 시험 A)가 다음 눈금으로 한 번 더 잡을지"""
    assert is_not_accepted_rejection('그룹 예약 트리거의 준비 여유가 부족합니다') is True
    assert is_not_accepted_rejection('그룹 회차 초기화 트리거가 이미 지났습니다') is True
    # 받았는지 모른다 · 다시 예약하면 두 번 잡힐 수 있다
    assert is_not_accepted_rejection('motion_run_manager response timeout') is False
    assert is_not_accepted_rejection('로컬 Web Bridge 응답 없음: timed out') is False
    assert is_not_accepted_rejection('다른 그룹 회차 초기화 명령이 이미 예약 상태입니다') is False
    assert is_not_accepted_rejection('') is False


# ---------------------------------------------------------------------- #
# 수정 목록 179 · 재시작 뒤 첫 시작 · 마스터 자신의 `start_at` 확인 늦음으로 1회차 빠짐
#
# 실물 NY 2026-11-07 12:36:28 floating1(마스터) · 12:18 업데이트로 서비스 재시작 → 스케줄 첫 시작 ·
# `initialize_at` 은 바닥 1.5 s 라 통과(530 ms) · `start_at` 은 여유 0.5 s(마감 0.4 s)에 548 ms → 빠짐
# ---------------------------------------------------------------------- #

def test_first_start_keeps_its_floor_as_the_default_without_measurements():
    """재시작 뒤 첫 시작 · 다른 PC 들의 Wi-Fi 왕복을 잰 값이 없다 · 1회차 시작은 3 s 아래로 내리지 않는다 · 사용자 결정 179

    207 은 진행 PC 자신의 예약을 프로세스 안으로 옮기면서 이 바닥을 뺐다(방금 잰 `initialize_at` 값으로 버팀) ·
    바닥은 진행 PC 의 길 때문이 아니라 「잰 값이 없을 때의 기본값」 이다 · 잰 값이 작아도 바닥 · 크면 잰 값.
    """
    assert INITIALIZE_LEAD_MIN_SEC == pytest.approx(3.0)
    assert FIRST_START_LEAD_MIN_SEC == pytest.approx(3.0)
    planner = ScheduleLeadPlanner()
    assert _lead(planner, 'initialize') == pytest.approx(3.0)
    assert _lead(planner, 'first_start') == pytest.approx(FIRST_START_LEAD_MIN_SEC)
    # 방금 잰 초기 위치 확인(같은 PC · `SAMPLE_FALLBACK`)이 작아도 바닥
    planner.record('initialize', 'floating1', 0.3)
    assert _lead(planner, 'first_start', ('floating1', 'floating4')) == pytest.approx(FIRST_START_LEAD_MIN_SEC)
    # 2회차부터는 바닥 없음 · 잰 값만
    assert _lead(planner, 'schedule', ('floating1', 'floating4')) == pytest.approx(0.7)


def test_first_start_uses_the_start_at_samples_and_may_grow_up_to_six_seconds():
    assert LEAD_MAX_SEC == pytest.approx(6.0)
    planner = ScheduleLeadPlanner()
    # 회차 시작 확인이 2 s 걸린 적 있다 → 1회차도 두 배 + 마감 여백(바닥 위)
    planner.record('schedule', 'floating1', 2.0)
    assert _lead(planner, 'first_start', ('floating1',)) == pytest.approx(4.1)
    planner.record('schedule', 'floating1', 5.0)
    assert _lead(planner, 'first_start', ('floating1',)) == pytest.approx(6.0)
    # `first_start` 라는 이름으로 따로 쌓이지 않는다
    assert 'first_start' not in planner.snapshot()['recent_ack_ms']
