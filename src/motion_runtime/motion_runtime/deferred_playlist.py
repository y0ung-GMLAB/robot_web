"""재생 목록 · 1번은 바로 · 2번부터는 뒤에서 짓는다 · 수정 목록 164

그룹 실행은 「초기 위치 이동 예약 시각(지금 + 1.5~3 s)」 전에 계획을 다 지어야 했다 · 재생 목록이
있으면 **목록의 모든 애니** 계획까지 · 920 s 파일이 목록에 섞이면 그것만으로 몇 초다 · 예약 시각을 넘겨
「그룹 예약 시작시각을 놓쳤습니다」 로 그 PC 가 빠졌다(NY 실물 2026-11-03 · floating1).

예약 시각 전에 꼭 있어야 하는 것은 1회차(목록 1번)의 재생 계획과 초기 위치 계획뿐이다 · 나머지는
작업 스레드 하나가 뒤에서 짓는다 · 처음 쓰일 때(1회차가 끝날 때) 아직이면 그때 기다린다 ·
그 사이 정지가 오면 기다림을 끝낸다(`InterruptedError`).

목록에서 깨진 파일은 전에는 시작 전에 거절됐다 · 이제는 1회차 도중에 알게 되고 **그 파일을 쓰기 전에**
멈춘다(「재생 목록 N번 …」 오류) · 1번 파일은 전처럼 시작 전에 거절된다.

`list` 처럼 쓴다 · `len` · `bool` · `[i]` · 끝까지 돌기 · `map` (항목마다 표시를 붙인 보기).

**언제 짓기 시작하나 · 수정 목록 171** · 만들 때가 아니라 `start()` 를 부를 때 · 그룹은 1회차가 시작되고
조금 뒤(`group_session.DEFERRED_BUILD_DELAY_SEC`) · 전에는 만들자마자 지어서 초기 위치 이동 · 「모션 시작
대기」 · `start_at` 확인과 겹쳤다 · 짓기가 GIL 을 쥐어 진행 PC 가 제 `start_at` 확인을 0.4 s 안에 못 했다
(NY 실물 2026-11-03 · floating1 「자신의 예약 확인 늦음」). 그 전에 쓰이면(`wait` · `[1]` 이후) 그때 바로 짓는다 ·
그 전에 정지가 오면 짓지 않는다. 짓는 스레드는 GIL 을 나눠 쓴다(`background_pacing`).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterator, List, Optional

from . import background_pacing

#: 정지를 보는 간격 · 기다리는 동안
_WAIT_POLL_SEC = 0.05


class DeferredPlaylist:
    def __init__(
        self,
        first: tuple,
        length: int,
        build: Callable[[], List[tuple]],
        *,
        stop_event: Optional[threading.Event] = None,
        name: str = 'playlist-build',
    ) -> None:
        self._first = first
        self._length = max(int(length), 0)
        self._build = build
        self._stop_event = stop_event
        self._name = name
        self._done = threading.Event()
        #: 미뤄 둔 시작을 앞당긴다(`wait`) · 171
        self._go = threading.Event()
        self._start_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._entries: Optional[List[tuple]] = None
        self._error: Optional[BaseException] = None

    def start(self, delay_sec: float = 0.0) -> None:
        """짓기 시작 · `delay_sec` 뒤에 · 그 사이 `wait` 가 오면 바로 · 여러 번 불러도 한 번만 짓는다 · 171"""
        delay = max(float(delay_sec or 0.0), 0.0)
        if delay <= 0.0:
            self._go.set()
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, args=(delay,), name=self._name, daemon=True,
                )
                self._thread.start()

    def started(self) -> bool:
        return self._thread is not None

    def _stopped(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    def _run(self, delay_sec: float) -> None:
        try:
            deadline = time.monotonic() + delay_sec
            while not self._go.is_set() and not self._stopped():
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    break
                self._go.wait(min(_WAIT_POLL_SEC, remaining))
            if self._stopped():
                raise InterruptedError()
            background_pacing.pace_current_thread()
            entries = list(self._build())
            if len(entries) != self._length:
                raise RuntimeError(
                    f'재생 목록 계획 수가 맞지 않습니다 · {len(entries)} / {self._length}'
                )
            self._entries = entries
        except BaseException as exc:  # noqa: BLE001 · 쓰는 쪽에서 그대로 다시 올린다
            self._error = exc
        finally:
            self._done.set()

    # -- 상태 ------------------------------------------------------------ #

    def done(self) -> bool:
        return self._done.is_set()

    def failed(self) -> Optional[BaseException]:
        """다 지었고 실패했으면 그 예외 · 아직이거나 성공이면 None · 기다리지 않는다"""
        return self._error if self._done.is_set() else None

    def wait(self) -> List[tuple]:
        """다 지을 때까지 · 실패면 그 예외 · 정지가 오면 `InterruptedError` · 아직 안 지었으면 지금 짓는다"""
        if self._stopped() and not self._done.is_set():
            raise InterruptedError()
        self.start()
        while not self._done.wait(_WAIT_POLL_SEC):
            if self._stop_event is not None and self._stop_event.is_set():
                raise InterruptedError()
        if self._error is not None:
            raise self._error
        assert self._entries is not None
        return self._entries

    # -- list 처럼 -------------------------------------------------------- #

    def __len__(self) -> int:
        return self._length

    def __bool__(self) -> bool:
        return self._length > 0

    def __getitem__(self, index: int) -> tuple:
        position = range(self._length)[index]
        if position == 0:
            return self._first
        return self.wait()[position]

    def __iter__(self) -> Iterator[tuple]:
        for position in range(self._length):
            yield self[position]

    def map(self, transform: Callable[[tuple], tuple]) -> 'MappedPlaylist':
        return MappedPlaylist(self, transform)


class MappedPlaylist:
    """항목마다 `transform` 을 붙여 보는 보기 · 짓기를 기다리는 것은 원래 목록 그대로"""

    def __init__(self, source: Any, transform: Callable[[tuple], tuple]) -> None:
        self._source = source
        self._transform = transform

    def __len__(self) -> int:
        return len(self._source)

    def __bool__(self) -> bool:
        return len(self._source) > 0

    def __getitem__(self, index: int) -> tuple:
        return self._transform(self._source[index])

    def __iter__(self) -> Iterator[tuple]:
        for position in range(len(self._source)):
            yield self[position]
