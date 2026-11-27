"""연동 노드가 통째로 멈추면 그 순간 모든 스레드의 스택을 파일로 · 끊김 시험 B (2026-11-08)

실물 · 마스터가 다시 붙은 직후 연동 노드가 약 2.7 s 멈췄다(로그에 「연속 실패 0회」 · swap 아님 ·
Wi-Fi 와 무관하게 과거에도 3번) · 무엇이 멈추게 했는지 모른다.

파이썬 스레드로 「깬 간격」 만 재면 GIL 을 쥔 멈춤 동안 그 스레드도 못 돌아 **멈춘 뒤의** 스택만 남는다 ·
그래서 표준 `faulthandler.dump_traceback_later` 를 쓴다 · C 스레드라 GIL 없이 시간이 되면 모든 스레드
스택을 적는다 · 이 스레드가 `interval` 마다 다시 걸어 두므로 `threshold` 넘게 못 걸면(= 프로세스가 멈춤)
그때 서 있던 자리가 파일에 남는다.

- 파일 · `<MOTION_WORKSPACE>/log/motion_coordination_stall.log` · `max_bytes` 넘으면 `.1` 로 한 번 돌린다
- 끄기 · 환경 변수 `MOTION_COORDINATION_STALL_WATCH=0`
- `faulthandler` 의 시간 감시는 프로세스에 하나뿐 · 이 노드 밖에서 쓰지 않는다

ROS 를 모른다 · 경고 한 줄은 넘겨받은 함수로.
"""

from __future__ import annotations

import faulthandler
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

#: 다시 걸어 두는 간격
STALL_WATCH_INTERVAL_SEC = 0.2
#: 이만큼 못 걸면 멈춤 · 스택을 남긴다
STALL_WATCH_THRESHOLD_SEC = 1.0
#: 파일 상한 · 넘으면 `.1` 로 돌린다(하나만 둔다)
STALL_WATCH_MAX_BYTES = 2 * 1024 * 1024


def stall_watch_enabled() -> bool:
    return str(os.environ.get('MOTION_COORDINATION_STALL_WATCH', '1')).strip().lower() not in {
        '0', 'false', 'no', 'off',
    }


def default_stall_log_path() -> Path:
    workspace = Path(os.environ.get('MOTION_WORKSPACE') or Path.cwd()).expanduser()
    return workspace / 'log' / 'motion_coordination_stall.log'


class StallWatch:
    def __init__(
        self,
        path: Path,
        warn: Callable[[str], None],
        *,
        interval_sec: float = STALL_WATCH_INTERVAL_SEC,
        threshold_sec: float = STALL_WATCH_THRESHOLD_SEC,
        max_bytes: int = STALL_WATCH_MAX_BYTES,
    ) -> None:
        self._path = Path(path)
        self._warn = warn
        self._interval_sec = max(float(interval_sec), 0.01)
        self._threshold_sec = max(float(threshold_sec), self._interval_sec * 2.0)
        self._max_bytes = max(int(max_bytes), 4096)
        self._file = None
        self._closed = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        try:
            self._open()
        except OSError as exc:
            self._warn(f'[연동 노드 멈춤 감시] 파일을 못 열어 끔 · {exc}')
            return False
        self._thread = threading.Thread(
            target=self._run, name='motion-coordination-stall-watch', daemon=True,
        )
        self._thread.start()
        return True

    def close(self) -> None:
        self._closed.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        faulthandler.cancel_dump_traceback_later()
        faulthandler.disable()
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def _open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() and self._path.stat().st_size > self._max_bytes:
            os.replace(self._path, self._path.with_name(self._path.name + '.1'))
        self._file = open(self._path, 'a', encoding='utf-8')
        # systemd 감시가 멈춘 노드를 SIGABRT 로 끝낼 때(G) 그 순간 스택도 같은 파일에
        faulthandler.enable(file=self._file, all_threads=True)

    def _size(self) -> int:
        try:
            self._file.flush()
            return os.fstat(self._file.fileno()).st_size
        except (OSError, ValueError, AttributeError):
            return 0

    def _arm(self) -> None:
        faulthandler.dump_traceback_later(self._threshold_sec, repeat=False, file=self._file, exit=False)

    def check_once(self, previous_wake: float, previous_size: int) -> tuple:
        """한 번 깸 · (지금, 파일 크기) · 시험에서 직접 부른다"""
        now = time.monotonic()
        gap = now - previous_wake
        size = self._size()
        if size > previous_size:
            # 덤프 줄에는 시각이 없다 · 바로 뒤에 한 줄
            self._file.write(f'--- 위 덤프 · {time.strftime("%Y-%m-%d %H:%M:%S")} · 멈춤 약 {gap:.1f} s ---\n\n')
            size = self._size()
            self._warn(
                f'[연동 노드 멈춤] 약 {gap:.1f} s · 그때 모든 스레드 스택을 남김 · {self._path}'
            )
        elif gap > self._threshold_sec:
            self._warn(f'[연동 노드 멈춤] 약 {gap:.1f} s · 스택은 못 남김')
        if size > self._max_bytes:
            faulthandler.cancel_dump_traceback_later()
            self._file.close()
            self._open()
            size = self._size()
        return now, size

    def _run(self) -> None:
        wake = time.monotonic()
        size = self._size()
        while not self._closed.is_set():
            try:
                self._arm()
            except (OSError, ValueError, RuntimeError) as exc:
                self._warn(f'[연동 노드 멈춤 감시] 걸기 실패 · 끔 · {exc}')
                return
            if self._closed.wait(self._interval_sec):
                break
            try:
                wake, size = self.check_once(wake, size)
            except (OSError, ValueError) as exc:
                self._warn(f'[연동 노드 멈춤 감시] 끔 · {exc}')
                return
