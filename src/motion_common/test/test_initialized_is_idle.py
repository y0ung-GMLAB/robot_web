"""초기 위치 이동이 끝나 서 있는 것은 「멈춤」 · 수정 목록 36 (2026-10-06)

전에는 도는 중으로 읽혀, 수동 「초기 위치 이동」 뒤나 스케줄 끝 기준점 주차 뒤에
다음 스케줄이 시작하지 못하고 1분마다 회차 후 정지만 보냈다.
"""

from motion_common import run_state


def test_initialized_counts_as_idle_for_the_scheduler():
    assert run_state.is_running('initialized') is False
    assert run_state.is_running('initializing') is True
