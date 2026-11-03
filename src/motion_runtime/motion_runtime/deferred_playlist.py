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
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Iterator, List, Optional

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
        self._stop_event = stop_event
        self._done = threading.Event()
        self._entries: Optional[List[tuple]] = None
        self._error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, args=(build,), name=name, daemon=True)
        self._thread.start()

    def _run(self, build: Callable[[], List[tuple]]) -> None:
        try:
            entries = list(build())
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
        """다 지을 때까지 · 실패면 그 예외 · 정지가 오면 `InterruptedError`"""
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
