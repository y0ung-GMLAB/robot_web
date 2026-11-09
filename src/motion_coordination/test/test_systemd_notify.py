"""systemd 감시 알림 · 끊김 시험 G (2026-11-08)"""

import socket
import time

from motion_coordination import systemd_notify
from motion_coordination.systemd_notify import SystemdWatchdog


def _listener(tmp_path):
    path = str(tmp_path / 'notify.sock')
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(path)
    sock.settimeout(1.0)
    return sock, {'NOTIFY_SOCKET': path}


def test_nothing_happens_outside_systemd():
    assert systemd_notify.notify('WATCHDOG=1', {}) is False
    watchdog = SystemdWatchdog({})
    assert watchdog.start() is False
    assert watchdog.ping(force=True) is False


def test_start_narrows_the_timeout_and_pings(tmp_path):
    sock, environ = _listener(tmp_path)
    try:
        watchdog = SystemdWatchdog(environ)
        assert watchdog.start() is True
        assert sock.recv(256) == b'WATCHDOG_USEC=15000000'
        assert sock.recv(256) == b'WATCHDOG=1'
    finally:
        sock.close()


def test_pings_are_at_most_once_a_second(tmp_path):
    sock, environ = _listener(tmp_path)
    try:
        watchdog = SystemdWatchdog(environ)
        watchdog.start()
        sock.recv(256), sock.recv(256)
        assert watchdog.ping() is False, '방금 보냈다'
        watchdog._last_ping = time.monotonic() - 1.5
        assert watchdog.ping() is True
        assert sock.recv(256) == b'WATCHDOG=1'
    finally:
        sock.close()


def test_the_timeout_can_be_changed_or_switched_off(tmp_path):
    assert systemd_notify.configured_watchdog_sec({'MOTION_COORDINATION_WATCHDOG_SEC': '20'}) == 20.0
    sock, environ = _listener(tmp_path)
    try:
        environ['MOTION_COORDINATION_WATCHDOG_SEC'] = '0'
        assert SystemdWatchdog(environ).start() is False
    finally:
        sock.close()


def test_the_executor_tick_pings_the_watchdog():
    from test_coordination_node import _node

    node = _node()
    pings = []
    node._systemd_watchdog = type('W', (), {'ping': lambda self: pings.append(1)})()
    node._consume_local_runtime_status = lambda: None
    try:
        node._state_tick()
    except Exception:
        pass
    assert pings == [1], '실행기 타이머가 맨 먼저 알린다'
