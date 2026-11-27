"""통신성 드라이브 알람 자동 초기화 · 수정 목록 178 (2026-11-08)

사용자 결정 「재생은 최대한 · 그 헤드만 정지 · 스스로 초기화하고 다시 붙게」 · 다만 기구 · 부하성
알람(과부하 Err16 · 위치 편차 Err24 · 리밋 Err38 …)은 원인이 그대로 남아 있을 수 있다 · 실물 NY
floating1 목 과부하는 기구 걸림이었다 · 그런 알람을 계속 다시 켜면 기구가 상한다 · 그래서 **통신성**
(EtherCAT 표시가 있는 알람 · Err80 · 81 · 84 · 85 · 88)만 자동으로 초기화하고 서보를 다시 켠다.

- 스케줄 모드(사람 없는 운영)에서만 · 수동 모드는 사람이 본다
- 알람이 2 s 넘게 그대로일 때(버스가 자리 잡을 시간)
- 축마다 1시간에 3번까지 · 넘으면 그 헤드는 정지 그대로 · 사람 확인(운영 로그에 한 번)
- 그룹 복귀는 연동 노드가 회차 경계에서 한다(알람이 풀리면 「실행 준비 안 됨」 이 사라진다)

ROS 를 모른다 · 브리지가 1초마다 모터 상태와 운전 모드를 넘기고 고른 축을 초기화한다.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Iterable, List, Mapping, Optional

from motion_common.minas_alarms import KIND_ALARM, SERVO_ALARM_CATALOG, code_kind

#: 자동으로 초기화하는 알람 · 카탈로그의 EtherCAT 표시 · 기구 · 부하성은 넣지 않는다
AUTO_RESET_CODES = frozenset(
    int(entry['code']) for entry in SERVO_ALARM_CATALOG if entry.get('ethercat_related')
)
#: 축마다 한도 · 1시간에 3번
LIMIT = 3
WINDOW_SEC = 3600.0
#: 알람이 이만큼 그대로일 때 · 버스가 다시 잡히는 동안 서두르지 않는다
SETTLE_SEC = 2.0
#: 같은 축을 다시 시도하기 전 최소 간격 · 초기화 → 서보 켜기 → 상태 반영
RETRY_GAP_SEC = 15.0


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AutoFaultRecovery:
    """축마다 알람이 처음 보인 시각과 시도 기록 · 고르기만 한다(보내기는 부르는 쪽)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._first_seen: Dict[int, float] = {}
        self._attempts: Dict[int, Deque[float]] = {}
        self._exhausted_noted: Dict[int, float] = {}

    def plan(self, motors: Iterable[Mapping[str, Any]], *, enabled: bool) -> Dict[str, List[Dict[str, Any]]]:
        """{'reset': [{axis, code, attempt}], 'exhausted': [{axis, code}]} · `exhausted` 는 처음 넘을 때 한 번"""
        now = self._clock()
        reset: List[Dict[str, Any]] = []
        exhausted: List[Dict[str, Any]] = []
        seen = set()
        for motor in motors or ():
            if not isinstance(motor, Mapping):
                continue
            axis = _int(motor.get('controller_index'))
            code = _int(motor.get('errorcode')) or 0
            if axis is None:
                continue
            if not motor.get('fault') or code_kind(code) != KIND_ALARM:
                continue
            seen.add(axis)
            first = self._first_seen.setdefault(axis, now)
            if not enabled or code not in AUTO_RESET_CODES or now - first < SETTLE_SEC:
                continue
            attempts = self._attempts.setdefault(axis, deque())
            while attempts and now - attempts[0] > WINDOW_SEC:
                attempts.popleft()
            if attempts and now - attempts[-1] < RETRY_GAP_SEC:
                continue
            if len(attempts) >= LIMIT:
                if axis not in self._exhausted_noted:
                    self._exhausted_noted[axis] = now
                    exhausted.append({'axis': axis, 'code': code})
                continue
            attempts.append(now)
            reset.append({'axis': axis, 'code': code, 'attempt': len(attempts)})
        for axis in list(self._first_seen):
            if axis not in seen:
                # 알람이 풀렸다 · 다음 알람은 처음부터 2 s 를 센다 · 한도 기록(1시간)은 남긴다
                self._first_seen.pop(axis, None)
                self._exhausted_noted.pop(axis, None)
        return {'reset': reset, 'exhausted': exhausted}
