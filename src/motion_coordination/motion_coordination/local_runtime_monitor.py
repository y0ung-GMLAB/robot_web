"""웹 쪽 칸을 옆에서 받아 두는 감시자 · ROS 실행기를 막지 않는다.

수정 목록 209 · 이 질문은 더 이상 그룹 판단에 쓰이지 않는다 · 재생 · 안전 상태는 연동 노드가 재생 관리자 ·
감독에서 로컬 DDS 로 직접 받는다(`local_link.py`) · 여기서는 웹만 아는 칸(운전 모드 · 시작 막힘 · 운영시간 ·
시간표 칸 · 「준비 끝」)을 0.5 s 마다 묻는다 · 못 받으면 지난 값을 쓰고 아무것도 정하지 않는다.

전에는 여기서 못 받으면 **그룹 실행이 통째로 정지했다**(§6-153 · 뒤에 이 PC 만 빠짐 · 178) · 그래서 못 받았을 때
「왜」 가 남아야 했다 · 숫자(몇 ms · 몇 번 연속 · 직전 응답들)는 지금도 화면 진단(`local_runtime.bridge_fields`)에 남긴다.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Mapping

#: 직전 응답 시간을 몇 개나 들고 있을 것인가 · 터진 순간 앞뒤를 보려면 이 정도면 된다
RECENT_SAMPLES = 20


class LocalRuntimeMonitor:
    """Poll loopback state outside the ROS executor and retain the latest sample."""

    def __init__(
        self,
        fetch: Callable[[], Mapping[str, Any]],
        *,
        active_interval_sec: float = 0.05,
        idle_interval_sec: float = 0.5,
    ) -> None:
        self._fetch = fetch
        self._active_interval_sec = max(float(active_interval_sec), 0.01)
        self._idle_interval_sec = max(
            float(idle_interval_sec), self._active_interval_sec
        )
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._active = False
        self._active_since_monotonic = 0.0
        self._status: Dict[str, Any] = {}
        self._received_monotonic = 0.0
        self._error = ''
        # 터진 순간에 들고 있어야 할 것들 · §6-153
        self._recent_ms: deque = deque(maxlen=RECENT_SAMPLES)
        self._consecutive_failures = 0
        self._worst_ms = 0.0
        self._failures_total = 0
        self._thread = threading.Thread(
            target=self._run,
            name='motion-coordination-local-runtime-monitor',
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def set_active(self, active: bool) -> None:
        active = bool(active)
        with self._lock:
            changed = active != self._active
            self._active = active
            if changed:
                self._active_since_monotonic = (
                    time.monotonic() if active else 0.0
                )
        if changed:
            self._wake.set()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'status': copy.deepcopy(self._status),
                'received_monotonic': self._received_monotonic,
                'active': self._active,
                'active_since_monotonic': self._active_since_monotonic,
                'error': self._error,
                # 아래는 오직 「왜 못 받았나」를 남기기 위한 것 · 판정에는 안 쓴다
                'recent_ms': [round(value, 1) for value in self._recent_ms],
                'consecutive_failures': self._consecutive_failures,
                'worst_ms': round(self._worst_ms, 1),
                'failures_total': self._failures_total,
            }

    def diagnosis(self) -> str:
        """못 받은 이유를 한 줄로 · 숫자를 같이 적는다 · §6-153

        이 글이 그대로 화면과 로그에 남는다 · 다음에 터졌을 때 이것만 보고
        「브리지가 느렸나 · 아예 죽었나 · 한 번 튀었나 · 계속 그런가」를
        가릴 수 있어야 한다.
        """
        with self._lock:
            since = (
                (time.monotonic() - self._received_monotonic) * 1000.0
                if self._received_monotonic else None
            )
            recent = ', '.join(f'{value:.0f}' for value in self._recent_ms) or '없음'
            parts = [
                f'마지막 성공 {since:.0f}ms 전' if since is not None
                else '수신 이력 없음',
                f'연속 실패 {self._consecutive_failures}회',
                f'최근 응답(ms) {recent}',
            ]
            if self._error:
                parts.append(f'사유 {self._error}')
        return ' · '.join(parts)

    def close(self) -> None:
        self._closed.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def poll_once(self) -> None:
        """Fetch one sample; public for deterministic unit tests."""
        started = time.monotonic()
        try:
            value = self._fetch()
            status = dict(value) if isinstance(value, Mapping) else {}
            if status.get('bridge_state') != 'ok':
                raise ValueError('로컬 Web Bridge 상태 형식 오류')
        except Exception as exc:  # loopback monitor safety boundary
            elapsed_ms = (time.monotonic() - started) * 1000.0
            with self._lock:
                self._error = str(exc)
                self._recent_ms.append(elapsed_ms)
                self._worst_ms = max(self._worst_ms, elapsed_ms)
                self._consecutive_failures += 1
                self._failures_total += 1
            return
        elapsed_ms = (time.monotonic() - started) * 1000.0
        with self._lock:
            self._status = status
            self._received_monotonic = time.monotonic()
            self._error = ''
            self._recent_ms.append(elapsed_ms)
            self._worst_ms = max(self._worst_ms, elapsed_ms)
            self._consecutive_failures = 0

    def _run(self) -> None:
        while not self._closed.is_set():
            self.poll_once()
            with self._lock:
                interval = (
                    self._active_interval_sec
                    if self._active else self._idle_interval_sec
                )
            self._wake.wait(interval)
            self._wake.clear()
