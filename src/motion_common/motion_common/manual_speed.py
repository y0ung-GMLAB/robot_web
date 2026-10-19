"""수동 조작 속도·가속 상한 · 조인트 기준 · 수정 목록 126 (사용자 결정 2026-10-13)

페이더 · 다이얼 · 조그 · 목표 위치 「이동」 · 범위 복구 전부 같은 상한 · 잘못 찍어도
그 자리까지 이 속도로 천천히 간다(잘못인지 의도인지 판단하지 않는다).

상한은 **조인트** °/s · 모터로는 매핑 이득(|scale × 감속·기어비|)을 곱한다 · 그래서
감속비가 다른 축도 같은 체감 속도 · 이득을 모르면(매핑 줄 없음 · MIDI 처럼 브리지를
안 거친 요청) 이득 1 로 친다 · 모터 기준 2 °/s · 가장 느린 쪽(보수적).

브리지가 매핑으로 모터 rad/s 를 계산해 요청에 싣는다(`REQUEST_FIELDS`) · supervisor 는
실린 값을 쓰고, 없으면 이득 1 값을 쓴다.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from . import units

#: 조인트 최대 속도 · °/s
JOINT_MAX_VELOCITY_DEG_S = 2.0
#: 조인트 최대 가속 · °/s²
JOINT_MAX_ACCELERATION_DEG_S2 = 4.0

#: X-Touch 는 조인트 매핑 최대 속도·가속도의 이만큼으로 따라간다 · 수정 목록 156 · floating4 실물 2026-10-19 ·
#: 상한에 딱 맞춘 녹화는 파일에 쓸 때 반올림(소수 9자리)만으로 재생 검사 여유(1e-6)를 넘어 「가속도 35 > 상한 35」 로
#: 재생이 거절됐다 · 2 % 여유
XTOUCH_LIMIT_RATIO = 0.98

#: 요청 칸 이름 · 모터 rad/s · rad/s²
VELOCITY_FIELD = 'manual_max_velocity_rad_s'
ACCELERATION_FIELD = 'manual_max_acceleration_rad_s2'
REQUEST_FIELDS = (VELOCITY_FIELD, ACCELERATION_FIELD)


def motor_limits(gain: Optional[float] = None) -> Dict[str, float]:
    """조인트 상한 → 모터 rad/s · rad/s² · 이득을 모르거나 0 이면 1"""
    factor = abs(float(gain)) if gain is not None and math.isfinite(float(gain)) else 0.0
    if factor <= 0.0:
        factor = 1.0
    return {
        VELOCITY_FIELD: units.deg_to_rad(JOINT_MAX_VELOCITY_DEG_S) * factor,
        ACCELERATION_FIELD: units.deg_to_rad(JOINT_MAX_ACCELERATION_DEG_S2) * factor,
    }


def _positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def limits_from_request(request: Any) -> Dict[str, float]:
    """요청에 실린 상한 · 없거나 틀리면 이득 1 값(가장 느림)"""
    fallback = motor_limits(None)
    if not isinstance(request, dict):
        return fallback
    velocity = _positive(request.get(VELOCITY_FIELD))
    acceleration = _positive(request.get(ACCELERATION_FIELD))
    return {
        VELOCITY_FIELD: velocity if velocity is not None else fallback[VELOCITY_FIELD],
        ACCELERATION_FIELD: acceleration if acceleration is not None else fallback[ACCELERATION_FIELD],
    }
