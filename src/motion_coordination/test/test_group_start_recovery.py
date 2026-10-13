"""그룹 시작이 실패해도 갇히지 않는다 · 사람이 한 재시작은 오류가 아니다 · 수정 목록 123·124

실물 2026-10-13

    S-11 15:09  4대 스케줄 · floating1~3 준비 거절 → 마스터가 뺀 PC 에 보낸 풀기 명령을
                제 것으로 처리(`group_cancel` 세션 불일치 ×3) → 제 실행을 `stopped` 로 두고
                `execution_id` 는 남김 → 17 분 동안 「이전 그룹 실행 정리 확인 중입니다」
    S-11 다시   「프로그램 다시 시작」 → 브리지가 사라진 것을 GROUP_PARTICIPANT_FAILURE 2등급으로 잠금
    S-12 15:34  부팅 직후 앱솔루트 확인 전 시작 → 진행 PC 준비 거절 → GROUP_START_REJECTED 2등급

여기는 rclpy 없이 도는 규칙만 · 노드에 붙인 시험은 `test_coordination_node.py` (미니 PC).
"""

from motion_coordination.group_execution import (
    BOOT_GRACE_SEC,
    DROP_RELEASE_PREFIX,
    STALE_LEASE_LIMIT_SEC,
    StaleLeaseWatch,
    bridge_loss_latches,
    drop_release_command_id,
    is_own_drop_release,
)


def test_the_master_skips_the_release_it_sent_to_a_dropped_pc():
    command_id = drop_release_command_id()
    assert command_id.startswith(DROP_RELEASE_PREFIX)
    assert is_own_drop_release('cancel_before_start', command_id, 'floating4', 'floating4') is True
    # 뺀 PC 는 받아서 푼다
    assert is_own_drop_release('cancel_before_start', command_id, 'floating4', 'floating1') is False
    # 전체 풀기(번호가 다름)는 진행 PC 도 처리한다
    assert is_own_drop_release('cancel_before_start', 'cmd-abc', 'floating4', 'floating4') is False
    assert is_own_drop_release('stop_now', command_id, 'floating4', 'floating4') is False


def _observe(watch, now, *, state='stopped', coordinator=True, releasing=False, execution_id='exec-a'):
    return watch.observe(
        execution_id=execution_id, state=state, coordinator=coordinator,
        releasing=releasing, now=now,
    )


def test_a_finished_execution_left_behind_is_reaped_after_the_limit():
    watch = StaleLeaseWatch()
    assert _observe(watch, 100.0) is False
    assert _observe(watch, 100.0 + STALE_LEASE_LIMIT_SEC - 1.0) is False
    assert _observe(watch, 100.0 + STALE_LEASE_LIMIT_SEC) is True


def test_a_live_or_releasing_execution_is_never_reaped():
    watch = StaleLeaseWatch(limit_sec=1.0)
    for state in ('preparing', 'running', 'cycle_initializing'):
        assert _observe(watch, 0.0, state=state) is False
        assert _observe(watch, 99.0, state=state) is False
    assert _observe(watch, 0.0, releasing=True) is False
    assert _observe(watch, 99.0, releasing=True) is False
    # 슬레이브는 진행 PC 의 명령으로 푼다
    assert _observe(watch, 0.0, coordinator=False) is False
    assert _observe(watch, 99.0, coordinator=False) is False


def test_a_brief_stop_before_the_start_does_not_count():
    """회차 후 정지가 출발 직전에 오면 잠깐 `stopped` 였다가 시작 보고로 `running` 이 된다"""
    watch = StaleLeaseWatch(limit_sec=10.0)
    assert _observe(watch, 0.0) is False
    assert _observe(watch, 1.0, state='running') is False
    assert _observe(watch, 2.0) is False
    assert _observe(watch, 11.0) is False, '다시 stopped 가 된 때부터 센다'
    assert _observe(watch, 12.0) is True


def test_a_new_execution_restarts_the_clock():
    watch = StaleLeaseWatch(limit_sec=10.0)
    assert _observe(watch, 0.0) is False
    assert _observe(watch, 11.0, execution_id='exec-b') is False
    assert _observe(watch, 21.0, execution_id='exec-b') is True


def _latches(state, *, now=10_000.0, boot=1.0, planned=0.0):
    return bridge_loss_latches(
        state=state, now=now, boot_monotonic=boot, planned_restart_until=planned,
    )


def test_losing_the_bridge_while_moving_still_latches():
    for state in ('initializing', 'armed', 'start_scheduled', 'running', 'cycle_initializing'):
        assert _latches(state) is True, state


def test_a_human_restart_does_not_latch():
    """「프로그램 다시 시작」 은 사람이 한 일 · S-11 다시"""
    assert _latches('running', now=100.0, boot=1.0 - BOOT_GRACE_SEC, planned=200.0) is False
    assert _latches('running', now=300.0, boot=1.0 - BOOT_GRACE_SEC, planned=200.0) is True


def test_right_after_boot_does_not_latch():
    assert _latches('running', now=50.0, boot=10.0) is False
    assert _latches('running', now=10.0 + BOOT_GRACE_SEC, boot=10.0) is True


def test_nothing_moved_yet_does_not_latch():
    for state in ('preparing', 'stopped', 'error', 'idle', 'ready'):
        assert _latches(state) is False, state
