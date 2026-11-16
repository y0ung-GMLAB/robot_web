"""supervisor 생존·수신 감시 · 수정 목록 29 + 14 (2026-10-06)"""

from pathlib import Path
from types import SimpleNamespace

from motion_web_bridge import supervisor_watchdog as wd
from motion_web_bridge.supervisor_watchdog import SupervisorWatchdog


class _Clock:
    def __init__(self):
        self.mono = 100.0
        self.wall = 1_000_000.0

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


def _watchdog(tmp_path):
    clock = _Clock()
    calls = []
    dog = SupervisorWatchdog(
        log_dir=tmp_path,
        restart=lambda: calls.append('restart') or '재시작 요청',
        dump_threads=lambda: calls.append('dump'),
        monotonic=lambda: clock.mono,
        wall=lambda: clock.wall,
    )
    return dog, clock, calls


def test_silence_after_the_first_status_blocks_starts(tmp_path):
    """첫 상태를 받은 뒤의 생존 감시 · 2 s 안 오면 막음 · 수정 목록 29 (전 시험의 기동 20 s 부분은 아래 202 로)"""
    dog, clock, calls = _watchdog(tmp_path)
    dog.safety_received({})
    assert dog.unresponsive_reason() == '' and dog.ready is True
    clock.advance(wd.LIVENESS_SEC + 0.5)
    assert 'supervisor 응답 없음' in dog.unresponsive_reason()
    assert calls == []


def test_a_slow_supervisor_start_is_not_a_failure(tmp_path):
    """느린 PC · supervisor 첫 상태가 2분 뒤 · 「아직 안 뜸」 · 재시작 · 빨간 줄 없음 · 수정 목록 202

    전에는 기동 20 s 뒤 「응답 없음」 + 상위 서비스 재시작 · 정상 기동을 끊고 처음부터 다시 띄웠다.
    """
    dog, clock, calls = _watchdog(tmp_path)
    for _ in range(120):
        clock.advance(1.0)
        assert dog.tick('idle') == ''
        assert dog.unresponsive_reason() == ''
    assert calls == []
    assert dog.snapshot()['ready'] is False and dog.snapshot()['ok'] is True

    dog.safety_received({})
    assert dog.ready is True
    clock.advance(wd.RESTART_AFTER_SEC + 1)
    assert '응답 없음' in dog.tick('idle'), '첫 상태 뒤 끊김은 진짜 · 10 s 뒤 재시작'
    assert calls == ['restart']


def test_a_supervisor_that_never_starts_is_reported_and_restarted_once(tmp_path):
    dog, clock, calls = _watchdog(tmp_path)
    clock.advance(wd.STARTUP_FAILURE_SEC - 1)
    assert dog.tick('idle') == '' and dog.unresponsive_reason() == ''
    clock.advance(2)
    assert 'supervisor 시작 안 됨' in dog.unresponsive_reason()
    assert 'supervisor 시작 안 됨' in dog.tick('idle')
    assert calls == ['restart']
    clock.advance(30)
    assert dog.tick('idle') == '', '5분에 한 번까지'
    assert calls == ['restart']
    assert 'supervisor 시작 안 됨' in dog.snapshot()['message']


def test_ten_seconds_of_silence_restarts_once_then_cools_down(tmp_path):
    dog, clock, calls = _watchdog(tmp_path)
    dog.safety_received({})
    clock.advance(wd.RESTART_AFTER_SEC - 1)
    assert dog.tick('idle') == ''
    clock.advance(1.5)
    assert '자동 재시작' in dog.tick('idle')
    assert calls == ['restart']              # 죽었으면 덤프할 스레드도 없다
    clock.advance(30)
    assert dog.tick('idle') == ''            # 5분에 한 번까지
    assert calls == ['restart']
    snapshot = dog.snapshot()
    assert snapshot['restart_count'] == 1 and snapshot['ok'] is False
    assert '자동 재시작' in snapshot['last_restart']['reason']

    clock.advance(wd.RESTART_COOLDOWN_SEC)
    assert dog.tick('idle') != ''
    assert calls == ['restart', 'restart']


def test_reception_stop_while_playing_dumps_threads_then_restarts(tmp_path):
    dog, clock, calls = _watchdog(tmp_path)
    stale = {'motion_run_received_age_sec': 3600.0}   # 옛 나이 · 재생이 막 시작했다

    dog.safety_received(stale)
    assert dog.tick('running') == ''         # 재생이 5초 넘게 이어져야 본다
    for _ in range(int(wd.RECEPTION_STOP_SEC)):
        clock.advance(1.0)
        dog.safety_received({'motion_run_received_age_sec': 0.02})
        assert dog.tick('running') == ''     # 잘 받고 있다

    clock.advance(1.0)
    dog.safety_received({'motion_run_received_age_sec': wd.RECEPTION_STOP_SEC + 0.5})
    assert '수신 정지' in dog.tick('running')
    assert calls == ['dump', 'restart']


def test_reception_age_is_ignored_when_not_playing(tmp_path):
    dog, clock, calls = _watchdog(tmp_path)
    for _ in range(10):
        clock.advance(1.0)
        dog.safety_received({'motion_run_received_age_sec': 999.0})
        assert dog.tick('idle') == '' and dog.tick('initializing') == ''
    assert calls == []


def test_bridge_blocks_starts_and_feeds_the_watchdog(tmp_path):
    from motion_web_bridge.bridge_node import MotionWebBridge

    bridge = MotionWebBridge.__new__(MotionWebBridge)
    bridge.supervisor_watchdog = SimpleNamespace(unresponsive_reason=lambda: 'supervisor 응답 없음 · 5초째')
    assert bridge.motor_runtime_control_blocker() == 'supervisor 응답 없음 · 5초째'

    source = Path(__file__).resolve().parents[1] / 'motion_web_bridge' / 'bridge_node.py'
    text = source.read_text(encoding='utf-8')
    assert 'watchdog.safety_received(payload)' in text
    assert "self.create_timer(\n            1.0, self._supervisor_watchdog_tick" in text
