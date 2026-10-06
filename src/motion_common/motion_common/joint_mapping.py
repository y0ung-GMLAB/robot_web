"""조인트 매핑 식 · 원본 하나 · 수정 목록 6 (2026-10-06)

    모터 = 기준점 + (조인트 + offset) × scale × 방향 × 감속·기어비

이 식이 다섯 곳(재생 규칙 · 매핑 노드 · 모터 한계 환산 · 재생 기록 역산 · 화면)에
따로 적혀 있었다 · 단위를 rad 로 옮기려면 한 곳이어야 한다.

매핑 줄의 각도 칸은 옮기는 동안 두 이름이 있을 수 있다 ·

    <이름>_rad   새 파일 (rad)
    <이름>_deg   옛 파일·옛 화면 (deg)

읽을 때는 `_rad` 가 있으면 그것, 없으면 `_deg` 를 바꿔서 · 부르는 쪽이 원하는 단위로
돌려준다 · 그래서 읽는 쪽이 모두 이 모듈을 거치면 파일 형식이 바뀌어도 값이 같다.
`reference_position` 만 **모터** 쪽 값이다 · 나머지는 조인트 쪽.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from . import units

#: 각도 칸 · 이름 → 기본값(조인트 쪽 deg 기준 · 모터 쪽은 reference 하나)
ANGLE_FIELDS: Dict[str, Optional[float]] = {
    'offset': 0.0,
    'reference_position': 0.0,      # 모터 쪽
    'motion_lower': -180.0,
    'motion_upper': 180.0,
    'initial_motion_position': 0.0,
}

#: 속도·가속도 칸 · 이름 → (rad 접미, deg 접미) · 기본값 없음(비우면 검사 안 함)
RATE_FIELDS: Dict[str, tuple] = {
    'max_velocity': ('_rad_s', '_deg_s'),
    'max_acceleration': ('_rad_s2', '_deg_s2'),
}


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    return number


def angle(row: Mapping[str, Any], name: str, unit: str = units.RAD, default: Any = 'field') -> Optional[float]:
    """매핑 줄의 각도 칸 · `unit` 으로 · 칸이 없으면 기본값(같은 단위로)"""
    units.check_unit(unit)
    value = _number(row.get(f'{name}_rad'))
    if value is not None:
        return units.convert(value, units.RAD, unit)
    value = _number(row.get(f'{name}_deg'))
    if value is not None:
        return units.convert(value, units.DEG, unit)
    fallback = ANGLE_FIELDS.get(name) if default == 'field' else default
    return None if fallback is None else units.convert(fallback, units.DEG, unit)


def rate(row: Mapping[str, Any], name: str, unit: str = units.RAD) -> Optional[float]:
    """최대 속도·가속도 · 칸이 없으면 None"""
    units.check_unit(unit)
    rad_suffix, deg_suffix = RATE_FIELDS[name]
    value = _number(row.get(f'{name}{rad_suffix}'))
    if value is not None:
        return units.convert(value, units.RAD, unit)
    value = _number(row.get(f'{name}{deg_suffix}'))
    if value is not None:
        return units.convert(value, units.DEG, unit)
    return None


def gain(row: Mapping[str, Any]) -> float:
    """조인트 1 → 모터 몇 · 단위 없음"""
    sign = -1.0 if bool(row.get('invert')) else 1.0
    scale = _number(row.get('scale')) or 1.0
    gear_ratio = _number(row.get('gear_ratio')) or 1.0
    return scale * sign * gear_ratio


def reference(row: Mapping[str, Any], unit: str = units.RAD) -> float:
    if row.get('reference_enabled') is False:
        return 0.0
    return float(angle(row, 'reference_position', unit))


def motor_target(row: Mapping[str, Any], joint: float, unit: str = units.RAD) -> float:
    """조인트 값 → 모터 값 · 들어오고 나가는 단위가 같다(`unit`)"""
    offset = float(angle(row, 'offset', unit))
    return reference(row, unit) + (float(joint) + offset) * gain(row)


def joint_from_motor(row: Mapping[str, Any], motor: float, unit: str = units.RAD) -> Optional[float]:
    """모터 값 → 조인트 값 · `motor_target` 의 역 · 이득이 0 이면 None"""
    factor = gain(row)
    if factor == 0.0:
        return None
    offset = float(angle(row, 'offset', unit))
    return (float(motor) - reference(row, unit)) / factor - offset


def row_in_unit(row: Mapping[str, Any], unit: str) -> Dict[str, Any]:
    """각도 칸을 모두 한 단위 이름으로 · 다른 단위 이름은 지운다 · 각도 아닌 칸은 그대로"""
    units.check_unit(unit)
    result = {
        key: value for key, value in row.items()
        if not any(key in (f'{name}_rad', f'{name}_deg') for name in ANGLE_FIELDS)
        and not any(key in (f'{name}{suffix}' for suffix in suffixes) for name, suffixes in RATE_FIELDS.items())
    }
    for name in ANGLE_FIELDS:
        present = row.get(f'{name}_rad') is not None or row.get(f'{name}_deg') is not None
        if present:
            result[f'{name}_{unit}'] = angle(row, name, unit)
    for name, (rad_suffix, deg_suffix) in RATE_FIELDS.items():
        value = rate(row, name, unit)
        if value is not None:
            result[f'{name}{rad_suffix if unit == units.RAD else deg_suffix}'] = value
    return result
