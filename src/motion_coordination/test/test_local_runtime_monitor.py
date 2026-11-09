import time

from motion_coordination.local_runtime_monitor import LocalRuntimeMonitor


def test_monitor_keeps_last_good_status_when_next_poll_fails():
    responses = [
        {'bridge_state': 'ok', 'motion_run_status': {'phase': 'running'}},
        OSError('bridge timeout'),
    ]

    def fetch():
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monitor = LocalRuntimeMonitor(fetch)
    monitor.poll_once()
    first = monitor.snapshot()
    monitor.poll_once()
    second = monitor.snapshot()

    assert first['status']['motion_run_status']['phase'] == 'running'
    assert second['status'] == first['status']
    assert second['error'] == 'bridge timeout'


def test_monitor_polls_more_often_while_execution_is_active():
    calls = []
    monitor = LocalRuntimeMonitor(
        lambda: calls.append(time.monotonic()) or {'bridge_state': 'ok'},
        active_interval_sec=0.01,
        idle_interval_sec=0.2,
    )
    monitor.start()
    try:
        deadline = time.monotonic() + 0.2
        while len(calls) < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        monitor.set_active(True)
        deadline = time.monotonic() + 0.2
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(calls) >= 3
    finally:
        monitor.close()


def test_monitor_records_activation_boundary_for_first_fresh_sample():
    monitor = LocalRuntimeMonitor(lambda: {'bridge_state': 'ok'})
    monitor.poll_once()
    idle = monitor.snapshot()

    monitor.set_active(True)
    active = monitor.snapshot()

    assert active['active'] is True
    assert active['active_since_monotonic'] >= idle['received_monotonic']


# 못 받았을 때 「왜」가 남는가 · §6-153
#
# 전에는 `timed out` 한 마디가 전부였다 · 브리지가 느렸는지 죽었는지, 한 번
# 튄 건지 계속 그런 건지 가릴 수가 없었다 · 그래서 원인 찾기에 반나절이 갔고,
# 재현이 안 되니 고쳤는지도 확인할 수 없었다.

def test_a_failure_leaves_numbers_behind():
    """사유만 남기면 다음에도 똑같이 헤맨다."""
    def refuse():
        raise OSError('timed out')

    monitor = LocalRuntimeMonitor(refuse)
    for _ in range(3):
        monitor.poll_once()

    said = monitor.diagnosis()
    assert '연속 실패 3회' in said
    assert '최근 응답(ms)' in said
    assert 'timed out' in said
    assert monitor.snapshot()['failures_total'] == 3


def test_a_success_resets_the_streak_but_keeps_the_worst():
    """연속 몇 번인지가 판정의 핵심이다 · 최악값은 여유를 보는 데 쓴다."""
    answers = [OSError('느림'), OSError('느림'), {'bridge_state': 'ok'}]

    def take_turns():
        value = answers.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monitor = LocalRuntimeMonitor(take_turns)
    for _ in range(3):
        monitor.poll_once()

    sample = monitor.snapshot()
    assert sample['consecutive_failures'] == 0, '성공했는데 연속 실패가 남았다'
    assert sample['failures_total'] == 2, '지나간 실패까지 지우면 안 된다'
    assert len(sample['recent_ms']) == 3, '성공도 실패도 다 재야 한다'


def test_recent_samples_do_not_grow_without_end():
    """오래 돌아도 메모리를 먹으면 안 된다 · 앞뒤만 보면 된다."""
    monitor = LocalRuntimeMonitor(lambda: {'bridge_state': 'ok'})
    for _ in range(200):
        monitor.poll_once()
    assert len(monitor.snapshot()['recent_ms']) == 20


def test_never_receiving_anything_says_so():
    """한 번도 못 받은 것과 받다가 끊긴 것은 원인이 다르다."""
    monitor = LocalRuntimeMonitor(lambda: (_ for _ in ()).throw(OSError('연결 거부')))
    monitor.poll_once()
    assert '한 번도 못 받음' in monitor.diagnosis()


# --------------------------------------------------------------------------- #
# 끊김 시험 B (2026-11-08) · 연동 노드 자체가 멈춘 것을 「웹 끊김」 으로 착각하지 않는다
#
# 실물 · 마스터가 다시 붙은 직후 연동 노드가 통째로 약 2.7 s 멈춤 · 깨어나 「로컬 상태 2.7 s 못 받음」 으로
# 저를 뺐다 · 그때 「연속 실패 0회」(요청이 실패한 적 없이 시간만 지남).
# --------------------------------------------------------------------------- #

def _master_after_a_stall(answers):
    import pytest

    from test_coordination_node import _node, _Publisher

    def fetch():
        value = answers.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    node = _node()
    node._execution.execution_id = 'exec-a'
    node._execution.coordinator_id = 'pc-a'
    node._execution.participants = ('pc-a', 'pc-b')
    node._execution.state = 'running'
    node._boot_monotonic = 0.0
    node._command_pub = _Publisher()
    node._last_alarm_key = ()
    warned = []
    node._warn = warned.append
    monitor = LocalRuntimeMonitor(fetch)
    monitor.poll_once()
    with monitor._lock:
        monitor._received_monotonic = time.monotonic() - 2.7     # 2.7 s 동안 아무 요청도 못 보냈다
    node._local_runtime_monitor = monitor
    dropped = []
    node._drop_self_for_bridge_loss = lambda detail, moving: dropped.append(detail)
    node._stop_for_peer_failure = lambda _reason: pytest.fail('그룹 전체를 세우지 않는다')
    return node, dropped, warned


def test_a_stall_of_this_node_with_no_failed_request_does_not_drop_it():
    ok = {'bridge_state': 'ok', 'motion_run_status': {'phase': 'running'}}
    node, dropped, warned = _master_after_a_stall([ok, ok])
    assert node._local_runtime_monitor.snapshot()['consecutive_failures'] == 0

    node._consume_local_runtime_status()

    assert dropped == [], '웹은 정상 · 빠지지 않는다'
    assert node._execution.participants == ('pc-a', 'pc-b')
    assert any('연동 노드 자체 멈춤 2.7 s' in text for text in warned)
    assert time.monotonic() - node._local_runtime_monitor.snapshot()['received_monotonic'] < 1.0


def test_a_stall_where_the_web_really_is_gone_still_drops():
    ok = {'bridge_state': 'ok'}
    node, dropped, _warned = _master_after_a_stall([ok, OSError('connection refused')])

    node._consume_local_runtime_status()

    assert len(dropped) == 1, '즉시 물어봐도 실패 · 지금처럼 빠진다'


def test_failed_requests_are_not_mistaken_for_a_stall():
    ok = {'bridge_state': 'ok'}
    node, dropped, _warned = _master_after_a_stall([ok, OSError('timed out'), ok])
    node._local_runtime_monitor.poll_once()                       # 실패 1회 · 웹이 느렸다
    with node._local_runtime_monitor._lock:
        node._local_runtime_monitor._received_monotonic = time.monotonic() - 2.7

    node._consume_local_runtime_status()

    assert len(dropped) == 1, '요청이 실패하고 있었다 · 웹 쪽 문제 · 지금처럼 빠진다'


# --------------------------------------------------------------------------- #
# 끊김 시험 B · 원인 잡기 · 멈춘 순간의 스택을 파일로
# --------------------------------------------------------------------------- #

def test_the_stall_watch_dumps_every_thread_when_it_cannot_rearm(tmp_path):
    from motion_coordination.stall_watch import StallWatch

    warned = []
    watch = StallWatch(tmp_path / 'stall.log', warned.append, interval_sec=0.02, threshold_sec=0.1)
    watch._open()
    try:
        before = watch._size()
        wake = time.monotonic()
        watch._arm()
        time.sleep(0.4)                                            # 다시 걸지 못함 = 멈춤
        _now, after = watch.check_once(wake, before)
    finally:
        watch.close()

    text = (tmp_path / 'stall.log').read_text(encoding='utf-8')
    assert after > before
    assert 'Thread' in text and 'test_the_stall_watch_dumps_every_thread' in text
    assert any('모든 스레드 스택을 남김' in line for line in warned)


def test_the_stall_watch_stays_quiet_while_it_keeps_rearming(tmp_path):
    from motion_coordination.stall_watch import StallWatch

    warned = []
    watch = StallWatch(tmp_path / 'stall.log', warned.append, interval_sec=0.02, threshold_sec=0.2)
    assert watch.start()
    time.sleep(0.5)
    watch.close()

    assert warned == []
    assert (tmp_path / 'stall.log').read_text(encoding='utf-8') == ''


def test_the_stall_log_is_rotated_when_too_big(tmp_path):
    from motion_coordination.stall_watch import StallWatch

    path = tmp_path / 'stall.log'
    path.write_text('x' * 10000, encoding='utf-8')
    watch = StallWatch(path, lambda _text: None, max_bytes=4096)
    watch._open()
    watch.close()

    assert path.with_name('stall.log.1').stat().st_size == 10000
    assert path.stat().st_size == 0


def test_the_stall_watch_can_be_switched_off(monkeypatch):
    from motion_coordination.stall_watch import stall_watch_enabled

    monkeypatch.setenv('MOTION_COORDINATION_STALL_WATCH', '0')
    assert stall_watch_enabled() is False
    monkeypatch.delenv('MOTION_COORDINATION_STALL_WATCH')
    assert stall_watch_enabled() is True
