"""systemd 감시(WatchdogSec)에 「살아 있음」 을 알린다 · 끊김 시험 G (2026-11-08)

연동 노드가 멈춰(행) 버리면 아무도 다시 띄우지 않았다(유닛에 `Restart=on-failure` 뿐) · 이제 노드의
실행기 타이머(`_state_tick`)가 1 s 마다 `WATCHDOG=1` 을 보낸다 · 실행기가 `WATCHDOG_SEC` 넘게 멈추면
systemd 가 SIGABRT 로 끝내고(그때 스택이 `log/motion_coordination_stall.log` 에) 다시 띄운다.

유닛의 `WatchdogSec` 은 넉넉히(90 s) · 실행 스크립트가 랜을 최대 60 s 기다린 뒤 노드를 띄우므로 ·
노드가 뜬 뒤 `WATCHDOG_USEC=` 로 15 s 로 좁힌다(systemd 236 이상 · 우분투 22.04 = 249).

`python3-systemd` 없이 `NOTIFY_SOCKET` 에 직접 쓴다 · 그 값이 없으면(서비스 밖 · 시험) 아무것도 안 한다.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Mapping, Optional

#: 노드가 뜬 뒤 좁히는 감시 시간 · 웹 역감시(살아 있으면 10 s · E)보다 길게 · 끄기 0
WATCHDOG_SEC = 15.0
WATCHDOG_ENV = 'MOTION_COORDINATION_WATCHDOG_SEC'
#: 알림 간격
PING_INTERVAL_SEC = 1.0


def notify(state: str, environ: Optional[Mapping[str, str]] = None) -> bool:
    """`NOTIFY_SOCKET` 으로 한 줄 · 보냈으면 True"""
    address = str((environ if environ is not None else os.environ).get('NOTIFY_SOCKET') or '')
    if not address or not hasattr(socket, 'AF_UNIX'):
        return False
    if address.startswith('@'):
        address = '\0' + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(str(state).encode('utf-8'))
        return True
    except OSError:
        return False


def configured_watchdog_sec(environ: Optional[Mapping[str, str]] = None) -> float:
    raw = (environ if environ is not None else os.environ).get(WATCHDOG_ENV)
    try:
        value = float(raw) if raw not in (None, '') else WATCHDOG_SEC
    except ValueError:
        value = WATCHDOG_SEC
    return max(value, 0.0)


class SystemdWatchdog:
    def __init__(self, environ: Optional[Mapping[str, str]] = None) -> None:
        self._environ = environ
        self._last_ping = 0.0
        self._started = False

    def start(self) -> bool:
        """감시 시간을 좁히고 첫 알림 · 서비스 밖이면 False"""
        seconds = configured_watchdog_sec(self._environ)
        if seconds <= 0.0:
            return False
        self._started = notify(f'WATCHDOG_USEC={int(seconds * 1_000_000)}', self._environ)
        if self._started:
            self.ping(force=True)
        return self._started

    def ping(self, *, force: bool = False) -> bool:
        if not self._started:
            return False
        now = time.monotonic()
        if not force and now - self._last_ping < PING_INTERVAL_SEC:
            return False
        self._last_ping = now
        return notify('WATCHDOG=1', self._environ)
