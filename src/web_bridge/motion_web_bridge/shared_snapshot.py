"""`/ws/status` 한 장을 화면 여럿이 나눠 쓴다 · 수정 목록 130

한 장 만드는 데 실측 66 KB · 17 ms(개발 PC · 미니 PC 는 더) · 화면 탭 하나가 초당 10 장을 받는다 ·
전에는 탭마다 따로 만들었다 · 탭 셋(사람 노트북 · 휴대폰 · 헤드리스 브라우저)이면 세 번 ·
서 있을 때도 motion_web_bridge CPU 31 %(실물 floating4 · 2026-10-13) · 그동안 같은 스레드 풀을 쓰는
연동 로컬 호출(예약 확인)이 줄을 섰다.

이제 반 박자 안에 만든 한 장이 있으면 그것을 보낸다 · 한 탭만 보면 전과 같다.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class SharedSnapshot:
    def __init__(
        self, build: Callable[[], str], *, max_age_sec: Callable[[], float],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._build = build
        self._max_age_sec = max_age_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._text = ''
        self._at = 0.0

    def text(self) -> str:
        # 만드는 동안 다른 탭은 기다렸다가 같은 한 장을 받는다
        with self._lock:
            if self._text and self._clock() - self._at < float(self._max_age_sec()):
                return self._text
            text = self._build()
            self._text = text
            self._at = self._clock()
            return text
