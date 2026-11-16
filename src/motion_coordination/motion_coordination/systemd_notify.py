"""systemd 감시(WatchdogSec)에 「살아 있음」 을 알린다 · 끊김 시험 G (2026-11-08)

연동 노드가 멈춰(행) 버리면 아무도 다시 띄우지 않았다(유닛에 `Restart=on-failure` 뿐) · 이제 노드의
실행기 타이머(`_state_tick`)가 1 s 마다 `WATCHDOG=1` 을 보낸다 · 실행기가 `WATCHDOG_SEC` 넘게 멈추면
systemd 가 SIGABRT 로 끝내고(그때 스택이 `log/motion_coordination_stall.log` 에) 다시 띄운다.

노드가 다 뜬 순간 `READY=1` 과 감시 시간(`WATCHDOG_USEC=`)을 한 번에 보낸다 · 유닛이 `Type=notify` 라
systemd 감시는 READY 뒤부터 켜진다 · 기동(랜 대기 최대 60 s + ROS setup + import)은 유닛 `TimeoutStartSec` 이
「영영 안 뜸」 만 잡는다 · 수정 목록 202 · 전에는 Type=simple 이라 감시가 실행 스크립트를 띄운 순간부터 ·
유닛 90 s 로 기동을 짐작해 덮고 노드가 뜬 뒤 15 s 로 좁혔다(느린 PC 는 90 s 를 넘겨 기동 중에 죽을 수 있었다).
옛 유닛(Type=simple)에서도 READY 는 해가 없다 · 감시는 전처럼 좁혀진다.

`python3-systemd` 없이 `NOTIFY_SOCKET` 에 직접 쓴다 · 그 값이 없으면(서비스 밖 · 시험) 아무것도 안 한다.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Mapping, Optional

#: 감시 시간 · 웹 역감시(살아 있으면 10 s · E)보다 길게 · 유닛 `WatchdogSec` 과 같은 값 · 끄기 0
WATCHDOG_SEC = 15.0
#: 끄기(0) 때 보내는 감시 시간 · 30일 · 유닛에 `WatchdogSec` 이 있어 READY 뒤 감시가 켜지므로 끄려면 덮어야 한다 ·
#: 0 은 systemd 판마다 뜻이 갈릴 수 있어(바로 만료로 읽히면 즉시 종료) 아주 긴 값을 쓴다 · 수정 목록 202 ·
#: 전에는 0 이면 아무것도 안 보내 유닛 감시(90 s)에 죽었다
OFF_USEC = 30 * 24 * 3600 * 1_000_000
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
        #: READY=1 을 보냈나 · 서비스 밖(시험 · 손으로 띄움)이면 False
        self.ready_sent = False

    def start(self) -> bool:
        """「준비 끝」(READY=1) + 감시 시간 · 한 데이터그램 · 감시를 쓰면(알림을 보내야 하면) True

        끄기(0)여도 READY 는 보낸다(안 보내면 `TimeoutStartSec` 뒤 기동 실패) · 감시 시간은 아주 길게(`OFF_USEC`).
        """
        seconds = configured_watchdog_sec(self._environ)
        usec = int(seconds * 1_000_000) if seconds > 0.0 else OFF_USEC
        self.ready_sent = notify(f'READY=1\nWATCHDOG_USEC={usec}', self._environ)
        self._started = self.ready_sent and seconds > 0.0
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
