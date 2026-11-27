"""그룹 시작이 실패해도 갇히지 않는다 · 사람이 한 재시작은 오류가 아니다 · 수정 목록 123·124

실물 2026-10-13

    S-11 15:09  4대 스케줄 · floating1~3 준비 거절 → 마스터가 뺀 PC 에 보낸 풀기 명령을
                제 것으로 처리(`group_cancel` 세션 불일치 ×3) → 제 실행을 `stopped` 로 두고
                `execution_id` 는 남김 → 17 분 동안 「이전 그룹 실행 정리 확인 중입니다」
    S-11 다시   「프로그램 다시 시작」 → 브리지가 사라진 것을 GROUP_PARTICIPANT_FAILURE 2등급으로 잠금
    S-12 15:34  부팅 직후 앱솔루트 확인 전 시작 → 진행 PC 준비 거절 → GROUP_START_REJECTED 2등급

여기는 rclpy 없이 도는 규칙만 · 노드에 붙인 시험은 `test_coordination_node.py` (미니 PC).

수정 목록 202 · 기동 · 다시 시작을 시간(전 90 s · 120 s)이 아니라 웹이 알린 「준비 끝」 으로 가른다 ·
`_moving` 시험이 바뀐 까닭 · 전에는 `boot_monotonic` · `planned_restart_until` 을 받았다.
"""

from motion_coordination.group_execution import (
    BRIDGE_LEAVE_SETTLE_SEC,
    BRIDGE_STARTUP_NOTICE_SEC,
    DROP_RELEASE_PREFIX,
    LocalBridgeReadiness,
    STALE_LEASE_LIMIT_SEC,
    StaleLeaseWatch,
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


# 수정 목록 202 · 웹 「준비 끝」 · 시간 대신 ------------------------------------------------- #

def _ok(instance, ready=True):
    return {'bridge_state': 'ok', 'bridge_instance_id': instance, 'ready': ready}


def test_a_slow_boot_stays_not_ready_however_long_it_takes():
    """NY floating4 · 기동이 90 s 를 넘어도 「아직 안 뜸」 · 전에는 90 s 뒤 끊김을 움직이던 중으로 봤다"""
    tracker = LocalBridgeReadiness(now=0.0)
    tracker.observe(_ok('web-1', ready=False), 50.0)
    tracker.observe(_ok('web-1', ready=False), 150.0)
    assert tracker.ready is False and tracker.phase == 'starting'
    tracker.observe(_ok('web-1'), 151.0)
    assert tracker.ready is True and tracker.phase == 'ready'


def test_ready_right_after_boot_is_ready():
    """준비 끝을 알린 뒤면 기동 2 s 뒤 끊김도 진짜 끊김 · 전에는 90 s 안이라 묻혔다"""
    tracker = LocalBridgeReadiness(now=0.0)
    tracker.observe(_ok('web-1'), 2.0)
    assert tracker.ready is True


def test_the_same_last_answer_is_seen_only_once():
    tracker = LocalBridgeReadiness(now=0.0)
    tracker.observe(_ok('web-1'), 5.0)
    tracker.leaving(now=6.0)
    # 끊긴 뒤에도 감시자는 마지막 답을 들고 있다 · 다시 봐도 「다시 뜸」 이 아니다
    tracker.observe(_ok('web-1'), 5.0)
    tracker.observe(_ok('web-1'), 5.0)
    assert tracker.phase == 'restarting'


def test_after_a_leave_only_a_new_web_that_says_ready_counts():
    """「내려간다」 알림 뒤 · 새 인스턴스가 준비 끝을 알릴 때까지 다시 뜨는 중 · 시간(전 120 s)과 상관없이"""
    tracker = LocalBridgeReadiness(now=0.0)
    tracker.observe(_ok('web-1'), 10.0)
    tracker.leaving(now=20.0)
    assert tracker.ready is False and tracker.phase == 'restarting'
    tracker.observe(_ok('web-1'), 21.0)                 # 내려가는 중인 옛 웹의 마지막 답
    assert tracker.phase == 'restarting'
    tracker.observe(_ok('web-2', ready=False), 400.0)   # 새 웹 · 아직 준비 전 · 120 s 훨씬 뒤
    assert tracker.ready is False
    tracker.observe(_ok('web-2'), 401.0)
    assert tracker.ready is True


def test_a_web_that_said_it_leaves_but_stays_is_ready_again():
    """다시 시작 요청이 실패해 옛 웹이 그대로 · 정지 한도보다 넉넉히 지나도 같은 인스턴스가 답하면 준비 끝"""
    tracker = LocalBridgeReadiness(now=0.0)
    tracker.observe(_ok('web-1'), 10.0)
    tracker.leaving(now=20.0)
    tracker.observe(_ok('web-1'), 20.0 + BRIDGE_LEAVE_SETTLE_SEC + 1.0)
    assert tracker.ready is True


def test_a_new_web_without_a_leave_notice_starts_over():
    """알림 없이 다시 뜸(죽어서 systemd 가 다시 띄움) · 새 인스턴스가 준비 전이면 다시 「아직 안 뜸」"""
    tracker = LocalBridgeReadiness(now=0.0)
    tracker.observe(_ok('web-1'), 10.0)
    tracker.observe(_ok('web-2', ready=False), 30.0)
    assert tracker.ready is False and tracker.phase == 'starting'


def test_an_old_web_without_the_field_counts_as_ready_when_it_answers():
    tracker = LocalBridgeReadiness(now=0.0)
    assert tracker.ready is False
    tracker.observe({'bridge_state': 'ok'}, 3.0)
    assert tracker.ready is True


def test_a_web_that_never_gets_ready_is_noted_once_after_a_long_wait():
    tracker = LocalBridgeReadiness(now=0.0)
    tracker.observe(_ok('web-1', ready=False), 1.0)
    assert tracker.overdue_once(BRIDGE_STARTUP_NOTICE_SEC - 1.0) == 0.0
    assert tracker.overdue_once(BRIDGE_STARTUP_NOTICE_SEC + 1.0) == BRIDGE_STARTUP_NOTICE_SEC + 1.0
    assert tracker.overdue_once(BRIDGE_STARTUP_NOTICE_SEC + 50.0) == 0.0, '한 번만'
    snap = tracker.snapshot(BRIDGE_STARTUP_NOTICE_SEC + 50.0)
    assert snap['phase'] == 'starting' and snap['overdue'] is True
    tracker.observe(_ok('web-1'), BRIDGE_STARTUP_NOTICE_SEC + 60.0)
    assert tracker.snapshot(BRIDGE_STARTUP_NOTICE_SEC + 61.0)['overdue'] is False
