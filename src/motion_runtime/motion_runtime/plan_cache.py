"""계획 재료 캐시 · 같은 키는 한 번만 계산 · 여러 스레드가 같이 써도 된다 · 수정 목록 164

준비 검사(작업 스레드)와 그룹 준비(그룹 작업 스레드)가 **같은 파일로 같은 계획**을
거의 동시에 짓는다 · 따로 지으면 같은 일을 두 번 하고 파이썬은 한 번에 한 스레드만 계산하므로 둘 다 두 배로 늦다.

    키가 이미 있다         → 그 값
    다른 스레드가 계산 중  → 끝나기를 기다렸다가 그 값 (실패했으면 직접 다시 계산 · 같은 오류가 난다)
    없다                   → 계산해서 넣는다 · 오래된 것부터 버린다(개수 · 바이트 제한)

키가 None 이면 담지 않는다(그때마다 계산) · 실패는 담지 않는다.
**담은 값은 고치지 않는다** · 부르는 쪽이 고칠 것이면 사본을 만든다.

기다리는 스레드 수 · `waiting(키)` · 미리 짓기(수정 목록 174)가 실행이 시작돼 계산을 그만둘지 볼 때 ·
누가 그 값을 기다리면 그만두지 않는다(그만두면 기다리던 쪽이 처음부터 다시 계산한다).

바이트 제한 · 수정 목록 170 · 값마다 `size_of(값)`(대략 바이트)를 더해 `max_bytes` 를 넘으면
오래된 것부터 버린다 · 방금 넣은 것 하나는 예산보다 커도 남긴다(바로 쓸 것이라 · 다음에 넣을 때 버려진다).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Hashable, Optional


def approx_nbytes(value: Any) -> int:
    """값의 대략 바이트 · `nbytes` 를 가진 것(배열 묶음)만 센다 · 튜플이면 칸마다 더한다 · 모르면 0"""
    if isinstance(value, tuple):
        return sum(approx_nbytes(item) for item in value)
    size = getattr(value, 'nbytes', None)
    return int(size) if isinstance(size, int) else 0


class SingleFlightCache:
    def __init__(
        self,
        size: int,
        *,
        max_bytes: Optional[int] = None,
        size_of: Callable[[Any], int] = approx_nbytes,
    ) -> None:
        self.size = max(int(size), 1)
        self.max_bytes = None if max_bytes is None else max(int(max_bytes), 0)
        self._size_of = size_of
        self._lock = threading.Lock()
        self._values: 'OrderedDict[Hashable, Any]' = OrderedDict()
        self._bytes: Dict[Hashable, int] = {}
        self._pending: Dict[Hashable, threading.Event] = {}
        self._waiters: Dict[Hashable, int] = {}

    def get_or_compute(self, key: Optional[Hashable], compute: Callable[[], Any]) -> Any:
        if key is None:
            return compute()
        while True:
            with self._lock:
                if key in self._values:
                    self._values.move_to_end(key)
                    return self._values[key]
                event = self._pending.get(key)
                owner = event is None
                if owner:
                    event = threading.Event()
                    self._pending[key] = event
                else:
                    self._waiters[key] = self._waiters.get(key, 0) + 1
            if not owner:
                try:
                    event.wait()
                finally:
                    with self._lock:
                        left = self._waiters.get(key, 0) - 1
                        if left > 0:
                            self._waiters[key] = left
                        else:
                            self._waiters.pop(key, None)
                continue
            try:
                value = compute()
                nbytes = self._measure(value)
            except BaseException:
                with self._lock:
                    self._pending.pop(key, None)
                event.set()
                raise
            with self._lock:
                self._values[key] = value
                self._bytes[key] = nbytes
                self._values.move_to_end(key)
                self._trim()
                self._pending.pop(key, None)
            event.set()
            return value

    def _measure(self, value: Any) -> int:
        if self.max_bytes is None:
            return 0
        try:
            return max(int(self._size_of(value)), 0)
        except Exception:  # noqa: BLE001 · 크기를 못 재도 값은 쓴다
            return 0

    def _trim(self) -> None:
        while len(self._values) > self.size:
            self._drop_oldest()
        if self.max_bytes is None:
            return
        while len(self._values) > 1 and sum(self._bytes.values()) > self.max_bytes:
            self._drop_oldest()

    def _drop_oldest(self) -> None:
        key, _ = self._values.popitem(last=False)
        self._bytes.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._bytes.clear()

    def waiting(self, key: Optional[Hashable]) -> int:
        """그 키의 계산이 끝나기를 기다리는 스레드 수 · 수정 목록 174"""
        if key is None:
            return 0
        with self._lock:
            return self._waiters.get(key, 0)

    def keys(self):
        with self._lock:
            return list(self._values)

    @property
    def nbytes(self) -> int:
        """담은 값의 대략 바이트 합 · 예산이 없으면 0"""
        with self._lock:
            return sum(self._bytes.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._values
