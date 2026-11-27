"""하트비트는 실행기와 따로 · 끊김 시험 N (2026-11-08)

하트비트를 실행기 타이머로 보냈다 · 그런데 같은 실행기의 `_state_tick` 이 로컬 웹 호출(`_call_local_control` ·
기본 4 s)에서 막히면 하트비트도 같이 굶어 3 s 넘게 안 나갔다 · 다른 PC 는 그것을 「통신 단절」 로 읽는다 ·
이 스레드는 실행기와 상관없이 `interval` 마다 하트비트를 보낸다(rclpy 발행은 스레드에서 써도 된다).

남는 경합 · 하트비트도 연동 노드의 상태 잠금(`_lock`)을 잠깐 쥔다 · 잠금을 쥔 채 로컬 웹을 부르는 곳(실행 교체
`_accept_execution_claim` 의 `group_cancel` 한 군데)이 막히면 그동안은 같이 기다린다.
"""

from __future__ import annotations

import threading
from typing import Callable


class HeartbeatPump:
    def __init__(self, interval_sec: float, tick: Callable[[], None], warn: Callable[[str], None]) -> None:
        self._interval_sec = max(float(interval_sec), 0.05)
        self._tick = tick
        self._warn = warn
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, name='motion-coordination-heartbeat', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._closed.wait(self._interval_sec):
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 · 한 번 실패로 하트비트가 영영 멈추면 안 된다
                self._warn(f'하트비트 보내기 실패 · {exc}')
