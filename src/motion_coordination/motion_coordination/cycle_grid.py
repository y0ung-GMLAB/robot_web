"""회차 눈금 · 진행 PC 가 없어도 같은 순간에 회차를 시작한다 · 수정 목록 178 (2026-11-08)

사용자 결정 「재생 신호는 마스터를 따른다 · 슬레이브가 빠지면(마스터가 안 보이면) 모션 시간에 맞춰
올림처리한 주기로 스스로 재생 · 인터넷 시계」.

- 진행 PC · 2회차부터 시작 시각을 눈금에 놓는다 · 주기 = (자연스러운 시작 − 앞 회차 시작 + 여유)를
  10 s 단위로 올림 · 한 번 정하면 줄이지 않는다(늦은 회차가 있으면 그만큼 늘린다) · 그래서 회차 사이
  간격은 늘 「지금 주기」 와 같다
- 참가 PC · 진행 PC 가 보낸 시작 시각 둘의 간격으로 주기를 안다(메시지 칸을 늘리지 않는다 · 스피커 ·
  옛 PC 와 형식이 같다) · 진행 PC 가 안 보이면 마지막 시작 + n × 주기 에 스스로 시작한다
- 시계 · 단조 시계(시스템 시간이 NTP 로 맞춰지며 빠르기도 함께 맞춰진다) · 시작 시각은 회차마다
  진행 PC 와 다시 맞춘다(DDS 시계 맞춤)

ROS 를 모른다 · 계산만.
"""

from __future__ import annotations

import math
from typing import Tuple

#: 주기 올림 단위 · 사용자 2026-11-08 「10 초」
GRID_STEP_SEC = 10.0
#: 자연스러운 시작보다 넉넉히 · 회차 초기화 · 시계 맞춤이 조금 늦어도 눈금을 지키게
GRID_MARGIN_SEC = 2.0


def round_up_period(span_sec: float, *, step: float = GRID_STEP_SEC, margin: float = GRID_MARGIN_SEC) -> float:
    """앞 회차 시작부터 다음 회차가 시작될 수 있는 시각까지 + 여유 · 단위로 올림 · 0 보다 크다"""
    raw = max(float(span_sec), 0.0) + float(margin)
    return max(math.ceil(raw / float(step) - 1e-9), 1) * float(step)


def aligned_start(*, natural: float, last_start: float, period: float) -> Tuple[float, float]:
    """다음 회차 시작 · (시작 시각, 주기) · 주기를 모르거나 자연스러운 시작이 눈금을 넘으면 주기를 늘린다

    늘 `시작 = 앞 회차 시작 + 주기` 이므로 참가 PC 는 간격 하나로 주기를 안다.
    """
    period = float(period or 0.0)
    if period <= 0.0 or float(natural) > float(last_start) + period:
        period = round_up_period(float(natural) - float(last_start))
    return float(last_start) + period, period


def next_grid_start(*, last_start: float, period: float, earliest: float) -> Tuple[int, float]:
    """마지막 시작 뒤 눈금 가운데 `earliest` 이후 첫 칸 · (몇 칸 뒤, 시각) · 칸을 건너뛰면 그만큼 쉰다"""
    period = float(period)
    if period <= 0.0:
        raise ValueError('주기를 모릅니다')
    steps = max(int(math.ceil((float(earliest) - float(last_start)) / period - 1e-9)), 1)
    return steps, float(last_start) + steps * period


#: 잰 간격을 눈금으로 붙이는 한도 · 시계 맞춤 오차(수십 ms)는 붙이고 · 그보다 크면 잰 값 그대로
SNAP_TOLERANCE_SEC = 1.0


def snap_period(measured: float, *, step: float = GRID_STEP_SEC, tolerance: float = SNAP_TOLERANCE_SEC) -> float:
    """참가 PC 가 잰 주기 · 진행 PC 의 주기는 늘 `step` 의 배수다 · 가까운 배수로 붙인다 · 끊김 시험 L

    두 회차 시작의 이 PC 시각 차이에는 시계 맞춤 오차(± 수십 ms)가 들어 있다 · 그대로 쓰면 스스로 잇는
    회차마다 그 오차가 쌓인다(n 회차 뒤 n 배) · 배수에서 `tolerance` 넘게 벗어나면(옛 진행 PC 등) 잰 값.
    """
    measured = float(measured)
    snapped = max(round(measured / float(step)), 1) * float(step)
    return snapped if abs(snapped - measured) <= float(tolerance) else measured
