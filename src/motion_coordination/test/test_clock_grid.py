"""시간표 재생 · 회차 시각 계산 · 수정 목록 186 (2026-11-09)

같은 설정 · 같은 벽시계면 PC 끼리 통신 없이 같은 회차 번호 · 같은 시작 시각이 나와야 한다.
"""

from datetime import datetime

import pytest

from motion_coordination import clock_grid
from motion_coordination.clock_grid import (
    Timeline, auto_period, effective_period, next_slot, period_error, pick_window,
    playlist_index, rebase_point, running_cycle, window_timeline,
)


def _ts(text: str) -> float:
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S').timestamp()


# --------------------------------------------------------------------------- #
# 주기
# --------------------------------------------------------------------------- #

def test_the_auto_period_is_the_longest_need_plus_the_gap_between_cycles_rounded_up_to_ten():
    # 920 s 애니 + 초기 이동 5 s → 925 + 회차 사이(장벽 2 + 시작 여유 4) + 2 → 933 → 940 · 수정 목록 188(전에는 930)
    assert auto_period([925.0, 400.0, 0.0]) == 940.0
    assert auto_period([932.5]) == 950.0
    assert auto_period([]) == 0.0, '아무도 모르면 0 · 시간표 없음'


def test_a_period_shorter_than_the_animation_is_refused():
    assert period_error(0.0, 930.0) == '', '0 = 자동'
    assert period_error(1000.0, 930.0) == ''
    assert '최소 930' in period_error(900.0, 930.0)
    assert period_error(-5.0, 930.0)
    assert period_error(10 ** 7, 930.0)
    assert period_error('abc', 930.0)


def test_the_effective_period_prefers_a_valid_manual_value():
    assert effective_period(1000.0, 930.0) == 1000.0
    assert effective_period(900.0, 930.0) == 930.0, '짧은 입력은 무시 · 자동'
    assert effective_period(0.0, 930.0) == 930.0
    assert effective_period(0.0, 0.0) == 0.0


# --------------------------------------------------------------------------- #
# 회차 번호 · 시각
# --------------------------------------------------------------------------- #

def test_a_pc_that_starts_mid_window_finds_the_same_next_cycle():
    timeline = Timeline('tt-s1', anchor_unix=10_060.0, period_sec=930.0, end_unix=40_000.0)
    # 13시 재부팅 PC 와 계속 돌던 PC · 같은 시각이면 같은 답
    slot = next_slot(timeline, 10_060.0 + 930.0 * 3 + 500.0, prep_sec=60.0, playlist_length=3)
    assert slot.cycle == 5 and slot.start_unix == 10_060.0 + 930.0 * 4
    assert slot.item_index == 1, '5회차 → 목록 2번째(0 부터 1)'


def test_a_cycle_closer_than_the_preparation_time_is_skipped():
    timeline = Timeline('tt-s1', anchor_unix=1000.0, period_sec=100.0)
    # 2회차(1100)까지 30 s 남았는데 준비에 60 s 필요 → 3회차
    assert next_slot(timeline, 1070.0, prep_sec=60.0).cycle == 3
    assert next_slot(timeline, 1030.0, prep_sec=60.0).cycle == 2
    # 1회차 전
    assert next_slot(timeline, 500.0, prep_sec=60.0).cycle == 1


def test_no_cycle_starts_after_the_window_end():
    timeline = Timeline('tt-s1', anchor_unix=1000.0, period_sec=100.0, end_unix=1250.0)
    assert next_slot(timeline, 1110.0, prep_sec=10.0).cycle == 3   # 1200 < 1250
    assert next_slot(timeline, 1210.0, prep_sec=10.0) is None, '1300 은 끝 뒤'
    assert running_cycle(timeline, 1299.0) == 3, '3회차는 끝까지 재생(끝 시각을 넘겨도)'
    assert running_cycle(timeline, 999.0) == 0


def test_the_playlist_cycles_in_order():
    assert [playlist_index(k, 3) for k in range(1, 8)] == [0, 1, 2, 0, 1, 2, 0]
    assert playlist_index(5, 1) == 0
    assert playlist_index(5, 0) == 0


# --------------------------------------------------------------------------- #
# 운영시간
# --------------------------------------------------------------------------- #

def test_the_first_cycle_starts_after_the_start_lead():
    window = (_ts('2026-11-09 10:00:00'), _ts('2026-11-09 18:00:00'))
    timeline = window_timeline(window, 930.0, start_lead_sec=60.0)
    assert timeline.anchor_unix == _ts('2026-11-09 10:01:00')
    assert timeline.end_unix == window[1]
    assert timeline.plan_id == clock_grid.schedule_plan_id(window[0])


def test_a_window_across_midnight_keeps_one_timeline():
    window = (_ts('2026-11-09 23:00:00'), _ts('2026-11-10 01:00:00'))
    timeline = window_timeline(window, 600.0, start_lead_sec=60.0)
    after_midnight = _ts('2026-11-10 00:05:00')
    slot = next_slot(timeline, after_midnight, prep_sec=30.0)
    assert slot.start_unix == _ts('2026-11-10 00:11:00')
    assert slot.cycle == 8   # 23:01 + 7 × 10 분
    assert timeline.plan_id == clock_grid.schedule_plan_id(window[0]), '자정을 넘겨도 같은 실행'


def test_touching_windows_are_one_operation():
    windows = [(1000.0, 2000.0), (2000.0, 3000.0), (5000.0, 6000.0)]
    assert pick_window(windows, 2500.0) == (1000.0, 3000.0)
    assert pick_window(windows, 3500.0) == (5000.0, 6000.0), '다음 운영시간'
    assert pick_window(windows, 6500.0) is None
    assert pick_window(windows, 500.0, horizon_sec=100.0) is None


# --------------------------------------------------------------------------- #
# 운영 중 설정 변경 · 다음 경계부터 · 회차 번호는 이어서
# --------------------------------------------------------------------------- #

def test_a_change_mid_operation_starts_at_the_next_boundary_and_keeps_counting():
    old = Timeline('tt-s1', anchor_unix=1000.0, period_sec=100.0, end_unix=5000.0)
    point, cycle = rebase_point(old, 1150.0, min_lead_sec=30.0)
    assert (point, cycle) == (1200.0, 3)
    # 경계가 너무 가까우면 그다음
    assert rebase_point(old, 1180.0, min_lead_sec=30.0) == (1300.0, 4)
    # 새 주기 120 s · 같은 운영시간 · 그 경계가 3회차
    new = window_timeline((940.0, 5000.0), 120.0, start_lead_sec=60.0, rebase=(point, cycle))
    assert new.plan_id == clock_grid.schedule_plan_id(940.0), '실행 번호 그대로'
    assert new.start_of(3) == 1200.0 and new.start_of(4) == 1320.0
    assert next_slot(new, 1150.0, prep_sec=30.0).cycle == 3
    assert not new.has_cycle(2), '경계 앞 회차는 새 시간표에 없다(옛 회차는 끝까지 재생)'


def test_a_rebase_from_another_window_is_ignored():
    timeline = window_timeline((10_000.0, 20_000.0), 100.0, start_lead_sec=60.0, rebase=(5000.0, 9))
    assert timeline.anchor_unix == 10_060.0 and timeline.first_cycle == 1


def test_before_the_first_cycle_the_anchor_stays():
    old = Timeline('tt-m1', anchor_unix=1000.0, period_sec=100.0)
    assert rebase_point(old, 900.0, min_lead_sec=30.0) == (1000.0, 1)


@pytest.mark.parametrize('now', [1000.0, 1234.5, 98_765.4])
def test_every_pc_gets_the_same_answer_for_the_same_clock(now):
    timeline = Timeline('tt-s1', anchor_unix=1000.0, period_sec=930.0)
    first = next_slot(timeline, now, prep_sec=45.0, playlist_length=2)
    again = next_slot(Timeline('tt-s1', anchor_unix=1000.0, period_sec=930.0), now, prep_sec=45.0, playlist_length=2)
    assert first == again
