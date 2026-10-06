"""각도 단위 · 변환은 여기 한 곳 · 수정 목록 6 (2026-10-06)

내부 제어·파일·토픽 값은 라디안으로 옮겨 간다(사용자 결정 2026-10-03) · 화면만 도(deg).
옮기는 동안 경계마다 바꿔야 해서, 흩어져 있던 `* 6.0`(rpm → deg/s) · `/ 360` ·
`math.radians` 를 여기로 모은다 · 경계에서 이 함수만 부른다.
"""

from __future__ import annotations

import math

DEG = 'deg'
RAD = 'rad'
UNITS = (DEG, RAD)

#: 1 rad = 57.29…°
DEG_PER_RAD = 180.0 / math.pi
RAD_PER_DEG = math.pi / 180.0


def check_unit(unit: str) -> str:
    if unit not in UNITS:
        raise ValueError(f'각도 단위는 deg 또는 rad 입니다: {unit}')
    return unit


def deg_to_rad(value: float) -> float:
    return float(value) * RAD_PER_DEG


def rad_to_deg(value: float) -> float:
    return float(value) * DEG_PER_RAD


def convert(value: float, source: str, target: str) -> float:
    """`source` 단위 값을 `target` 단위로 · 같으면 그대로."""
    check_unit(source)
    check_unit(target)
    if source == target:
        return float(value)
    return deg_to_rad(value) if target == RAD else rad_to_deg(value)


def rpm_to_deg_s(rpm: float) -> float:
    """모터 회전 속도 rpm → deg/s (1 rpm = 6 deg/s)"""
    return float(rpm) * 6.0


def rpm_to_rad_s(rpm: float) -> float:
    return float(rpm) * 2.0 * math.pi / 60.0
