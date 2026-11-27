"""계획 재료 캐시 · 같은 키는 한 번만 계산 · 여러 스레드가 같이 써도 된다 · 수정 목록 164

준비 검사(작업 스레드)와 그룹 준비(그룹 작업 스레드)가 **같은 파일로 같은 계획**을
거의 동시에 짓는다 · 따로 지으면 같은 일을 두 번 한다.

    키가 이미 있다         → 그 값
    다른 스레드가 계산 중  → 끝나기를 기다렸다가 그 값 (실패했으면 직접 다시 계산 · 같은 오류가 난다)
    없다                   → 계산해서 넣는다 · 개수를 넘으면 오래된 것부터 버린다

키가 None 이면 담지 않는다(그때마다 계산) · 실패는 담지 않는다.
**담은 값은 고치지 않는다** · 부르는 쪽이 고칠 것이면 사본을 만든다.

수정 목록 208 · 무거운 계산은 디스크 변환본(`plan_artifact`)으로 갔다 · 여기는 변환본에서 읽은 것을
잠깐 들고 있는 칸(개수 2) · 같은 키를 두 스레드가 동시에 변환하지 않게 하는 자리다. 바이트 예산(170) ·
기다리는 스레드 수(174 미리 짓기 그만두기)는 뺐다 · 재생 프로세스에서 큰 계산을 하지 않는다.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Dict, Hashable, Optional


class SingleFlightCache:
    def __init__(self, size: int) -> None:
        self.size = max(int(size), 1)
        self._lock = threading.Lock()
        self._values: 'OrderedDict[Hashable, Any]' = OrderedDict()
        self._pending: Dict[Hashable, threading.Event] = {}

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
            if not owner:
                event.wait()
                continue
            try:
                value = compute()
            except BaseException:
                with self._lock:
                    self._pending.pop(key, None)
                event.set()
                raise
            with self._lock:
                self._values[key] = value
                self._values.move_to_end(key)
                while len(self._values) > self.size:
                    self._values.popitem(last=False)
                self._pending.pop(key, None)
            event.set()
            return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def keys(self):
        with self._lock:
            return list(self._values)

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._values
