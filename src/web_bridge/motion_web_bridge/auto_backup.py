"""프로젝트 자동 백업 · 하루 1회 · 수정 목록 33-4 (2026-10-06)

브리지가 1분마다 `tick` 을 부른다 · 30분마다 한 번 「오늘 백업이 있나」 를 보고,
없으면 별도 스레드에서 만든다(zip 은 애니메이션이 많으면 몇 초 걸린다 · ROS 타이머를
막지 않게) · 오늘 것이 있으면 아무것도 안 한다 · 켠 뒤 2분은 기다린다(부팅 직후
모터 적용·스케줄 시작과 겹치지 않게).

만드는 일은 저장소(`ProjectRepository.auto_backup`)가 한다 · 여기는 언제만 정한다.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

FIRST_DELAY_SEC = 120.0
CHECK_INTERVAL_SEC = 1800.0


class AutoBackupService:
    def __init__(
        self,
        run_backup: Callable[[], Dict[str, Any]],
        *,
        log_info: Callable[[str], None] = print,
        log_error: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
        start_thread: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self._run_backup = run_backup
        self._log_info = log_info
        self._log_error = log_error
        self._clock = clock
        self._start_thread = start_thread or self._thread
        self._next_at = clock() + FIRST_DELAY_SEC
        self._running = False
        self._lock = threading.Lock()
        self.last_result: Dict[str, Any] = {}

    @staticmethod
    def _thread(work: Callable[[], None]) -> None:
        threading.Thread(target=work, name='project_auto_backup', daemon=True).start()

    def tick(self) -> bool:
        """때가 됐으면 백업을 시작한다 · 시작했으면 True"""
        now = self._clock()
        with self._lock:
            if self._running or now < self._next_at:
                return False
            self._running = True
            self._next_at = now + CHECK_INTERVAL_SEC
        self._start_thread(self._work)
        return True

    def _work(self) -> None:
        try:
            result = self._run_backup()
            self.last_result = {**result, 'finished_at': time.time()}
            if result.get('created'):
                self._log_info(
                    f'[자동 백업] {result.get("day")} · 프로젝트 {len(result.get("projects") or [])}개'
                    + (f' · 지난 것 정리 {len(result["pruned"])}' if result.get('pruned') else '')
                )
        except Exception as exc:  # noqa: BLE001 · 백업 실패가 브리지를 죽이면 안 된다
            self.last_result = {'error': str(exc), 'finished_at': time.time()}
            self._log_error(f'[자동 백업] 실패 · {exc}')
        finally:
            with self._lock:
                self._running = False
