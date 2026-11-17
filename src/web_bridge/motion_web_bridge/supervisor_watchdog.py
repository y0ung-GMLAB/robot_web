"""supervisor 생존·수신 감시 · 수정 목록 29 + 14 (2026-10-06)

모터로 가는 명령은 supervisor 하나만 내보낸다 · 그것이 죽거나(29) 살아서도
재생 명령을 못 받게 되면(14, 2026-09-08 1회 · 원인 미특정) 모터는 마지막
자리에서 홀드한다(안전) · 그런데 화면은 옛 상태, 서비스는 「정상」, 스케줄은
1분마다 시작 실패만 했다 · 사람이 눈으로 볼 때까지 아무도 몰랐다.

supervisor 는 0.5초마다 `safety_status` 를 보낸다 · 여기서 그 나이를 잰다.
아래는 첫 상태(= supervisor 「준비 끝」)를 받은 **뒤**의 생존 감시다 · 0.5 s 마다 오던 것이 끊긴 것.

    2초 넘게 안 옴         「supervisor 응답 없음」 · 시작 막음 · 화면 표시
    10초 넘게 안 옴        상위 서비스 재시작 (Motor Manager 는 따로라 홀드 유지)
    재생 중인데 5초 넘게    「재생 명령 수신 정지」 · 스레드 덤프 신호 → 재시작
    재생 명령을 못 받음

첫 상태 전은 「아직 안 뜸」 · 고장이 아니다 · 시작 막음은 `StartupReadiness`(「프로그램 시작 중」) ·
`STARTUP_FAILURE_SEC` 넘게 한 번도 안 오면 「supervisor 시작 안 됨」 · 화면 표시 + 재시작 한 번 ·
전에는 기동 뒤 20 s(`BOOT_GRACE_SEC`) 만 기다리고 곧바로 「응답 없음」 + 재시작 · 느린 PC 의 정상 기동을
끊고 처음부터 다시 띄웠다 · 수정 목록 202.

재시작은 5분에 한 번까지 · 기록은 `log/supervisor_watchdog.jsonl` (원격 확인용).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

#: 아래 셋은 첫 상태를 받은 뒤의 생존 감시 · supervisor 는 0.5 s 마다 보낸다
LIVENESS_SEC = 2.0
RESTART_AFTER_SEC = 10.0
RECEPTION_STOP_SEC = 5.0
RESTART_COOLDOWN_SEC = 300.0
#: 살아 있는데 재생 명령을 못 받는 사유 · 이 글이면 스레드 덤프를 남긴다
RECEPTION_STOP_REASON = '재생 중 모터 프로그램의 재생 명령 수신 중단, 자동 복구'
#: 기동 뒤 첫 상태를 이만큼 한 번도 못 받으면 「supervisor 시작 안 됨」 · 그 전은 「아직 안 뜸」(고장 아님) ·
#: 느린 PC 도 넘지 않을 만큼 길게 · 전 `BOOT_GRACE_SEC` 20 s · 수정 목록 202
STARTUP_FAILURE_SEC = 300.0

LOG_NAME = 'supervisor_watchdog.jsonl'


class SupervisorWatchdog:
    def __init__(
        self,
        *,
        log_dir: Path,
        restart: Callable[[], str],
        dump_threads: Callable[[], None],
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._log_path = Path(log_dir) / LOG_NAME
        self._restart = restart
        self._dump_threads = dump_threads
        self._monotonic = monotonic
        self._wall = wall
        self._started = monotonic()
        self._safety_at: Optional[float] = None
        self._safety: Dict[str, Any] = {}
        self._running_since: Optional[float] = None

    # -- 받기 ------------------------------------------------------------ #

    def safety_received(self, payload: Dict[str, Any]) -> None:
        self._safety_at = self._monotonic()
        self._safety = dict(payload) if isinstance(payload, dict) else {}

    # -- 판정 ------------------------------------------------------------ #

    def silence_sec(self) -> float:
        return self._monotonic() - (self._safety_at if self._safety_at is not None else self._started)

    @property
    def ready(self) -> bool:
        """첫 상태를 받았나 · supervisor 「준비 끝」 · 수정 목록 202"""
        return self._safety_at is not None

    def unresponsive_reason(self) -> str:
        """고장으로 볼 사유(화면 빨간 줄 · 시작 막음) · 아직 안 뜬 것은 고장이 아니다 · 수정 목록 202"""
        silence = self.silence_sec()
        if self._safety_at is None:
            if silence < STARTUP_FAILURE_SEC:
                return ''
            return f'모터 프로그램 미시작 ({silence:.0f}초간 상태 미수신)'
        if silence <= LIVENESS_SEC:
            return ''
        return f'모터 프로그램 응답 없음 ({silence:.0f}초간 상태 미수신)'

    def _reception_stopped(self, run_state: str) -> bool:
        now = self._monotonic()
        if run_state != 'running':
            self._running_since = None
            return False
        if self._running_since is None:
            self._running_since = now
        # 막 재생을 시작했으면 옛 나이가 남아 있다 · 재생이 5초 넘게 이어졌을 때만 본다
        if now - self._running_since < RECEPTION_STOP_SEC:
            return False
        age = self._safety.get('motion_run_received_age_sec')
        try:
            return age is not None and float(age) > RECEPTION_STOP_SEC
        except (TypeError, ValueError):
            return False

    # -- 1초마다 ---------------------------------------------------------- #

    def tick(self, run_state: str) -> str:
        """재시작했으면 그 사유 · 아니면 빈 글자."""
        silence = self.silence_sec()
        if self._safety_at is None:
            # 아직 안 뜸 · 오래 안 뜨면 그때 한 번 · 수정 목록 202
            if silence < STARTUP_FAILURE_SEC:
                return ''
            reason = f'모터 프로그램 미시작 {silence:.0f}초, 자동 재시작'
        elif silence >= RESTART_AFTER_SEC:
            reason = f'모터 프로그램 응답 없음 {silence:.0f}초, 자동 재시작'
        elif self._safety_at is not None and silence <= LIVENESS_SEC and self._reception_stopped(
            str(run_state or '').strip().lower(),
        ):
            reason = RECEPTION_STOP_REASON
        else:
            return ''
        last = self.last_restart_at()
        if last is not None and self._wall() - last < RESTART_COOLDOWN_SEC:
            return ''
        if reason == RECEPTION_STOP_REASON:
            # 살아 있으니 그 순간의 스레드를 남긴다 · 원인 미특정 결함 (14-2)
            try:
                self._dump_threads()
            except Exception:  # noqa: BLE001 · 덤프는 덤일 뿐 복구가 먼저다
                pass
        result = self._restart()
        self._record({'reason': reason, 'result': result})
        self._running_since = None
        return reason

    # -- 기록 ------------------------------------------------------------ #

    def _record(self, entry: Dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'at': self._wall(), **entry}, ensure_ascii=False) + '\n')
        except OSError:
            pass

    def history(self) -> list:
        try:
            lines = self._log_path.read_text(encoding='utf-8').splitlines()
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def last_restart_at(self) -> Optional[float]:
        rows = self.history()
        return float(rows[-1].get('at') or 0.0) if rows else None

    def snapshot(self) -> Dict[str, Any]:
        rows = self.history()
        return {
            'ok': not self.unresponsive_reason(),
            'message': self.unresponsive_reason(),
            # 첫 상태를 받았나 · 전이면 「아직 안 뜸」 · 수정 목록 202
            'ready': self.ready,
            'silence_sec': round(self.silence_sec(), 1),
            'restart_count': len(rows),
            'last_restart': rows[-1] if rows else None,
        }
