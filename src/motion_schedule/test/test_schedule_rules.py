"""스케줄 노드가 고르는 길 · rclpy 없이 · 수정 목록 115 · 124

실물 R-43 (2026-10-13 14:17) · 수동 모드에서 사람이 켠 단독 연속 재생 · 운전 모드를 스케줄로
바꾸자 스케줄 노드가 26 s 뒤 「구간 밖인데 돌고 있다 · 회차 후 정지」 를 판단 · 그런데 그룹
길(`/api/coordination/control`)로만 보내 「활성 그룹 실행이 없습니다」 로 거절 · 4회차 넘게 안 멈춤.

실물 S-12 (15:34) · 부팅 직후 앱솔루트 확인 전에 그룹 시작 · 거절이 2등급으로 잠김.
"""

from motion_schedule.schedule_rules import (
    GROUP_ROUTE,
    LOCAL_ROUTE,
    START_WENT_NOWHERE,
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
