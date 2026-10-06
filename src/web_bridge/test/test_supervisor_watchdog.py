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


def test_boot_grace_then_silence_blocks_starts(tmp_path):
    dog, clock, calls = _watchdog(tmp_path)
    assert dog.unresponsive_reason() == ''          # 막 떴다 · supervisor 를 기다린다
    clock.advance(wd.BOOT_GRACE_SEC + 1)
    assert 'supervisor 응답 없음' in dog.unresponsive_reason()

    dog.safety_received({})
    assert dog.unresponsive_reason() == ''
    clock.advance(wd.LIVENESS_SEC + 0.5)
    assert 'supervisor 응답 없음' in dog.unresponsive_reason()
    assert calls == []


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
