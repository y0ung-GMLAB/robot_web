"""supervisor 생존·수신 감시 · 수정 목록 29 + 14 (2026-10-06)

모터로 가는 명령은 supervisor 하나만 내보낸다 · 그것이 죽거나(29) 살아서도
재생 명령을 못 받게 되면(14, 2026-09-08 1회 · 원인 미특정) 모터는 마지막
자리에서 홀드한다(안전) · 그런데 화면은 옛 상태, 서비스는 「정상」, 스케줄은
1분마다 시작 실패만 했다 · 사람이 눈으로 볼 때까지 아무도 몰랐다.

supervisor 는 0.5초마다 `safety_status` 를 보낸다 · 여기서 그 나이를 잰다.

    2초 넘게 안 옴         「supervisor 응답 없음」 · 시작 막음 · 화면 표시
    10초 넘게 안 옴        상위 서비스 재시작 (Motor Manager 는 따로라 홀드 유지)
    재생 중인데 5초 넘게    「재생 명령 수신 정지」 · 스레드 덤프 신호 → 재시작
    재생 명령을 못 받음

재시작은 5분에 한 번까지 · 기록은 `log/supervisor_watchdog.jsonl` (원격 확인용).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

LIVENESS_SEC = 2.0
RESTART_AFTER_SEC = 10.0
RECEPTION_STOP_SEC = 5.0
RESTART_COOLDOWN_SEC = 300.0
#: 막 떴을 때 · supervisor 가 아직 안 떴을 수 있다
BOOT_GRACE_SEC = 20.0

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

    def unresponsive_reason(self) -> str:
        """시작을 막을 사유 · 막 떴을 때는 기다린다."""
        if self._safety_at is None and self.silence_sec() < BOOT_GRACE_SEC:
            return ''
        silence = self.silence_sec()
        if silence <= LIVENESS_SEC:
            return ''
        return f'supervisor 응답 없음 · {silence:.0f}초째 상태 수신 없음'

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
        if self._safety_at is None and silence < BOOT_GRACE_SEC:
            return ''
        if silence >= RESTART_AFTER_SEC:
            reason = f'supervisor 응답 없음 {silence:.0f}초 · 자동 재시작'
        elif self._safety_at is not None and silence <= LIVENESS_SEC and self._reception_stopped(
            str(run_state or '').strip().lower(),
        ):
            reason = '재생 중 supervisor 재생 명령 수신 정지 · 자동 복구'
        else:
            return ''
        last = self.last_restart_at()
        if last is not None and self._wall() - last < RESTART_COOLDOWN_SEC:
            return ''
        if 'supervisor 재생 명령 수신 정지' in reason:
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
            'silence_sec': round(self.silence_sec(), 1),
            'restart_count': len(rows),
            'last_restart': rows[-1] if rows else None,
        }
