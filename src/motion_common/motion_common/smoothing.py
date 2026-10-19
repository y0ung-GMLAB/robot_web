"""X-Touch 목표 스무딩 · 화면은 받은 페이더 값 그대로 보내고, 거르는 것은 여기(중간)서 · 수정 목록 156

사용자 결정 2026-10-19 「미디 신호는 로우데이터대로 · 필터링·스무딩은 중간에서 · 정도는 내가 고르게」 ·
supervisor 수동 스트림 램프와 재생 노드 구간 덮어쓰기(펀치인)가 같이 쓴다.

    날 값(raw) → 1차 저역 두 번(각 시간상수 = 고른 시간 ÷ 2) → 램프(속도·가속 상한) → 모터

두 번 거르면 날 값이 계단처럼 띄엄띄엄 와도 거른 값의 속도가 끊기지 않는다(한 번이면 계단마다 속도가 툭 뛴다) ·
고른 시간 ≈ 늦음 · 0 이면 거르지 않음 · 단위는 부르는 쪽 마음(모터 rad 든 조인트 rad 든 한 단위로만).
"""

from __future__ import annotations

import math
from typing import Any

#: 고를 수 있는 가장 긴 시간 · 초 · 화면 단계보다 넉넉히
MAX_SMOOTH_SEC = 2.0
#: 날 값에 이만큼 가까우면 다 따라간 것 · rad · 램프 도착 판정(`ramp.ARRIVE_RAD`)과 같은 크기
SETTLE_RAD = math.radians(1e-4)


def smooth_sec_from(value: Any) -> float:
    """요청의 `smooth_sec` · 없거나 틀리면 0(거르지 않음) · 0 ~ 2 초"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number <= 0.0:
        return 0.0
    return min(number, MAX_SMOOTH_SEC)


class Smoother:
    """1차 저역 두 번 · 시작은 지금 자리(잡은 자리에서 튐 없이)"""

    def __init__(self, value: float) -> None:
        self.first = float(value)
        self.value = float(value)

    def reset(self, value: float) -> None:
        self.first = float(value)
        self.value = float(value)

    def update(self, raw: float, dt: float, seconds: float) -> float:
        """한 주기 · 거른 값"""
        raw = float(raw)
        if seconds <= 0.0:
            self.reset(raw)
            return raw
        alpha = 1.0 - math.exp(-max(float(dt), 0.0) / (seconds / 2.0))
        self.first += (raw - self.first) * alpha
        self.value += (self.first - self.value) * alpha
        if self.settled(raw):
            self.reset(raw)
        return self.value

    def settled(self, raw: float) -> bool:
        return abs(raw - self.first) <= SETTLE_RAD and abs(raw - self.value) <= SETTLE_RAD
