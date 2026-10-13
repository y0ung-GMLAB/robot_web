"""스케줄 노드가 고르는 길 · rclpy 없이 · 수정 목록 115 · 124

실물 R-43 (2026-10-13 14:17) · 수동 모드에서 사람이 켠 단독 연속 재생 · 운전 모드를 스케줄로
바꾸자 스케줄 노드가 26 s 뒤 「구간 밖인데 돌고 있다 · 회차 후 정지」 를 판단 · 그런데 그룹
길(`/api/coordination/control`)로만 보내 「활성 그룹 실행이 없습니다」 로 거절 · 4회차 넘게 안 멈춤.

실물 S-12 (15:34) · 부팅 직후 앱솔루트 확인 전에 그룹 시작 · 거절이 2등급으로 잠김.
"""

import pytest

from motion_schedule.schedule_rules import (
    GROUP_ROUTE,
    IDLE_PARK,
    LOCAL_ROUTE,
    START_WENT_NOWHERE,
    WINDOW_END_DONE,
    WINDOW_END_WAIT,
    window_end_step,
    start_blocker,
    start_failure_message,
    stop_route,
)


def test_a_solo_run_is_stopped_on_the_local_path_even_when_joined():
    """R-43 · 연동 묶임 + 그룹 실행 없음 = 단독 길"""
    assert stop_route({}, joined=True) == LOCAL_ROUTE
    assert stop_route({'state': 'stopped', 'execution_id': 'exec-old'}, joined=True) == LOCAL_ROUTE
    assert stop_route({'state': 'running', 'execution_id': ''}, joined=True) == LOCAL_ROUTE


def test_a_live_group_run_goes_the_group_way():
    for state in ('preparing', 'running', 'running_independent', 'cycle_ready', 'releasing'):
        assert stop_route({'state': state, 'execution_id': 'exec-a'}, joined=True) == GROUP_ROUTE, state


def test_not_joined_is_always_local():
    assert stop_route({'state': 'running', 'execution_id': 'exec-a'}, joined=False) == LOCAL_ROUTE


def test_the_start_blocker_is_read_only_when_the_bridge_says_so():
    assert start_blocker(None) is None, '못 읽었으면 직전 값을 쓴다'
    assert start_blocker({'run_mode': 'schedule'}) is None, '옛 브리지 · 칸이 없다'
    assert start_blocker({'start_blocker': ''}) == ''
    assert start_blocker({'start_blocker': '  앱솔루트 미확인 '}) == '앱솔루트 미확인'


def test_why_the_last_start_went_nowhere():
    group = {'last_start_failure': {'message': 'floating4 실행 준비 안 됨: 앱솔루트 미확인'}}
    assert start_failure_message(group, {}) == 'floating4 실행 준비 안 됨: 앱솔루트 미확인'
    assert start_failure_message({}, {'state': 'error', 'message': '도달 확인 실패'}) == '도달 확인 실패'
    assert start_failure_message(None, {'state': 'stopped', 'message': '정지'}) == START_WENT_NOWHERE


def _walk(states, *, run_mode='schedule'):
    """점검 순서대로 (구간 안?, 도는 중?) · 노드처럼 pending 을 이어 가며 답만 모은다"""
    pending, steps = False, []
    for in_window, running in states:
        step = window_end_step(pending=pending, in_window=in_window, running=running, run_mode=run_mode)
        pending = step == WINDOW_END_WAIT
        steps.append(step)
    return steps


def test_window_end_parks_a_robot_that_was_already_stopped_once():
    """사용자 2026-10-13 · 구간 끝에 멈춰 있어도 주차 → 서보 OFF · 구간 끝마다 한 번"""
    assert _walk([(True, False), (False, False), (False, False)]) == [WINDOW_END_WAIT, IDLE_PARK, WINDOW_END_DONE]


def test_window_end_while_running_is_left_to_the_stop_after_cycle_path():
    """도는 중이면 옛 길(회차 후 정지 + schedule_end) · 멈춘 뒤 또 주차하지 않는다"""
    assert _walk([(True, True), (False, True), (False, False)]) == [WINDOW_END_WAIT, WINDOW_END_DONE, WINDOW_END_DONE]


@pytest.mark.parametrize('mode', ['manual', 'off', ''])
def test_window_end_parks_only_in_schedule_mode(mode):
    """수동 · 끔 · 모름 · 사람이 만지는 중일 수 있다"""
    assert _walk([(True, False), (False, False)], run_mode=mode) == [WINDOW_END_WAIT, WINDOW_END_DONE]


def test_starting_outside_the_window_does_not_park():
    """재부팅 · 구간 밖에서 켜졌다 · 구간 끝을 본 적이 없다"""
    assert _walk([(False, False), (False, False)]) == [WINDOW_END_DONE, WINDOW_END_DONE]


def test_each_window_end_parks_again():
    steps = _walk([(True, False), (False, False), (True, True), (False, True), (True, False), (False, False)])
    assert steps.count(IDLE_PARK) == 2
