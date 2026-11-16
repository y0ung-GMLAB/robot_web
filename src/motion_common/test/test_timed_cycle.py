"""시간표 재생 회차 명령 · 초기 이동 시각 · 늦음 · 쉼 규칙 · 수정 목록 206 (2026-11-16)

사용자 결정 · 초기 이동이 늦게 끝나도 잘못이 아니다 · 끝나는 대로 시작(쉼 아님) · 너무 늦어 다음 회차 준비를 먹을 때만 쉼.
"""

import math

from motion_common.timed_cycle import CYCLE_END_SEC, INITIAL_MOVE_SETTLE_SEC, decide, initialize_at, latest_start


def test_the_initial_move_starts_back_from_the_cycle_start_by_this_pcs_own_time():
    assert INITIAL_MOVE_SETTLE_SEC == 1.0, '실측 늦게 끝남 0.2~0.8 s · 시작 확인 왕복은 없어짐(188 은 4 s)'
    assert initialize_at(1000.0, 10.0) == 1000.0 - 10.0 - INITIAL_MOVE_SETTLE_SEC
    assert initialize_at(1000.0, 5.0) == 994.0, '5 s 매핑이면 5 s 만큼만 앞에서 · PC 마다 다르다'
    assert initialize_at(1000.0, -3.0) == 999.0, '틀린 값은 0 으로'


def test_the_latest_start_leaves_room_for_the_next_cycles_initial_move():
    # 920 s 클립 · 초기 이동 10 s · 간격 940 → 늦어도 8.5 s 까지는 그 회차를 돈다
    assert CYCLE_END_SEC == 0.5, '최종 위치 확인 + 회차 끝을 보고 다음 회차 명령 · 셈 약 0.3 s(188 은 2 s)'
    latest = latest_start(1000.0, 1940.0, 920.0, 10.0)
    assert latest == 1940.0 - 10.0 - INITIAL_MOVE_SETTLE_SEC - CYCLE_END_SEC - 920.0 == 1008.5
    assert latest_start(1000.0, 0.0, 920.0, 10.0) == math.inf, '운영시간 마지막 회차 · 다음 회차 없음 · 한도 없음'
    # 클립이 간격보다 길어 제때 시작해도 넘침 · 제때는 늘 돈다(쉬는 것은 늦은 때만)
    assert latest_start(1000.0, 1100.0, 97.0, 5.0) == 1000.0


def test_on_time_a_little_late_and_too_late():
    on_time = decide(cycle=3, start=1000.0, ready_at=999.2, latest=1008.5)
    assert on_time.start_at == 1000.0 and on_time.late_sec == 0.0 and not on_time.skip
    late = decide(cycle=3, start=1000.0, ready_at=1003.0, latest=1008.5)
    assert late.start_at == 1003.0 and late.late_sec == 3.0 and not late.skip, '3 s 늦음 · 쉼 아님 · 끝나는 대로'
    edge = decide(cycle=3, start=1000.0, ready_at=1008.5, latest=1008.5)
    assert not edge.skip, '한도 그 시각까지는 돈다'
    too_late = decide(cycle=3, start=1000.0, ready_at=1009.0, latest=1008.5)
    assert too_late.skip == '초기 이동이 9.0 s 늦게 끝남 · 돌면 4회차 준비 시각을 넘김'
    before = decide(cycle=3, start=1000.0, ready_at=1012.0, latest=1008.5, moved=False)
    assert before.skip.startswith('지금 초기 이동을 시작해도 12.0 s 늦게 끝남'), '아직 안 움직였으면 끝날 시각으로'
