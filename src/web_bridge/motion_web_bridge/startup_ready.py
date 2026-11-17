"""웹 서비스 「준비 끝」 · 기동 순서를 시간으로 짐작하지 않는다 · 수정 목록 202

웹(브리지)은 supervisor · 재생 관리자와 같은 서비스(motion-control)로 뜬다 · 둘은 0.5 s 마다 상태를
보낸다 · 첫 상태가 곧 「떴다」 · 둘 다 한 번씩 받으면 이 웹 인스턴스는 준비 끝 · 다시 꺼지지 않는다
(그 뒤 끊김은 supervisor 감시 · 연동 노드가 따로 본다).

연동 노드가 묻는 `/api/coordination/local-status` 에 `ready` · `bridge_instance_id` 로 싣는다 · 연동
노드는 「한 번도 준비 끝 아님」 을 「아직 안 뜸」(고장 아님) · 준비 끝 뒤 끊김만 진짜 끊김으로 본다 ·
전에는 연동 노드 기동 뒤 90 s · 웹 다시 시작 뒤 120 s · supervisor 감시 20 s 를 시간으로 짐작했다 ·
느린 PC(NY floating4 · RAM 4.7 GB · 스왑 · 찬 디스크 캐시)는 그 시간을 넘겨 정상 기동이 고장으로 읽혔다.

준비 전에는 시작 · 수동 조작을 막는다(`blocker`) · 그 글이 하트비트 `start_blocker` 로 진행 PC 에 가서
그룹 시작 때 이 PC 만 빠진다 · `STARTUP_NOTICE_SEC` 넘게 안 끝나면 「확인할 일」 · 그룹은 잠그지 않는다.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

#: 준비 끝에 필요한 첫 상태 · (이름, 화면 글)
REQUIRED = (
    ('supervisor', 'supervisor'),
    ('motion_run_manager', '재생 관리자'),
)
#: 이만큼 지나도 준비 끝이 아니면 「확인할 일」 · 막는 것은 그 전후 같다 · 느린 PC 도 넘지 않을 만큼 길게
STARTUP_NOTICE_SEC = 300.0


class StartupReadiness:
    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._started = monotonic()
        self._seen: Dict[str, float] = {}
        self._ready_after: Optional[float] = None
        self._lock = threading.Lock()

    def mark(self, name: str) -> None:
        """그 서비스의 첫 상태를 받았다 · 두 번째부터는 아무 일 없음"""
        with self._lock:
            if name in self._seen:
                return
            now = self._monotonic()
            self._seen[name] = now
            if self._ready_after is None and all(key in self._seen for key, _label in REQUIRED):
                self._ready_after = now - self._started

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._ready_after is not None

    def waiting(self) -> List[str]:
        with self._lock:
            return [label for key, label in REQUIRED if key not in self._seen]

    def blocker(self) -> str:
        """준비 전이면 시작 · 수동 조작을 막는 글 · 준비 끝이면 빈 글"""
        waiting = self.waiting()
        if not waiting:
            return ''
        return f'프로그램 시작 중입니다 (대기: {", ".join(waiting)})'

    def status(self) -> Dict[str, Any]:
        with self._lock:
            ready_after = self._ready_after
            waiting = [label for key, label in REQUIRED if key not in self._seen]
            elapsed = self._monotonic() - self._started
        overdue = ready_after is None and elapsed >= STARTUP_NOTICE_SEC
        message = ''
        if overdue:
            message = (
                f'{", ".join(waiting)} 상태를 {elapsed / 60.0:.0f}분간 수신하지 못했습니다. '
                '프로그램을 재시작하세요.'
            )
        return {
            'ready': ready_after is not None,
            'waiting': waiting,
            'elapsed_sec': round(elapsed, 1),
            'ready_after_sec': None if ready_after is None else round(ready_after, 1),
            'overdue': overdue,
            'message': message,
        }
