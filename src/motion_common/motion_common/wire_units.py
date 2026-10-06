"""모터 쪽 경계 단위 · 아직 deg 인 곳 · 수정 목록 6 (2026-10-06)

안쪽(조인트 매핑 · 재생 계획 · 조인트 값 · 재생 상태)은 rad 다 · 모터 쪽 세 곳은
아직 deg 라서 그 경계에서만 바꾼다 · 경계는 이 모듈의 함수만 부른다.

    MOTOR_NODE_UNIT      motor_manager 토픽 (motor_status · motor_command 의 position)
                         · motor_manager 입력이 rad 가 되면(6-1) rad
    MOTOR_COMMAND_UNIT   재생 → supervisor 명령 토픽 (MotorStatus.position)
                         · 6-4(2026-10-06)부터 rad
    MOTOR_STATE_UNIT     motion_state JSON 의 motors[] 위치·속도 · 6-5(2026-10-06)부터 rad
                         (`position_rad` · `velocity_rad_s`) · 이름에 단위가 없는 옛 칸
                         (`position` · `velocity`)만 이 단위로 읽는다 · `*_deg` 칸은 이름대로 deg
    MOTOR_CONFIG_UNIT    모터 설정 파일 drivers[].lower/upper (motion_state 에도 그대로 실린다)
                         · motor_manager 입력이 rad 가 되면(6-1) rad

상수 하나를 바꾸면 그 경계가 통째로 옮겨 간다.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from . import units
from .values import finite_float

MOTOR_NODE_UNIT = units.DEG
MOTOR_COMMAND_UNIT = units.RAD
MOTOR_STATE_UNIT = units.RAD
MOTOR_CONFIG_UNIT = units.DEG

#: 모터 상태의 위치 칸 · 앞에서부터 처음 있는 값 · (칸 이름, 단위 · None = MOTOR_STATE_UNIT)
_POSITION_KEYS = (
    ('position_rad', units.RAD),
    ('position_deg', units.DEG),
    ('position_actual_deg', units.DEG),
    ('output_position_deg', units.DEG),
    ('present_position_deg', units.DEG),
    ('position_actual', None),
    ('position', None),
)
_VELOCITY_KEYS = (
    ('velocity_rad_s', units.RAD),
    ('velocity_deg_s', units.DEG),
    ('velocity', None),
)


def from_motor_node(value: float) -> float:
    """motor_manager 토픽 위치 → rad"""
    return units.convert(value, MOTOR_NODE_UNIT, units.RAD)


def command_value(value_rad: float) -> float:
    """안쪽 모터 값(rad) → 명령 토픽 단위"""
    return units.convert(value_rad, units.RAD, MOTOR_COMMAND_UNIT)


def from_command(value: float) -> float:
    """명령 토픽 위치 → rad · supervisor 가 재생 명령을 받을 때"""
    return units.convert(value, MOTOR_COMMAND_UNIT, units.RAD)


def to_motor_node(value_rad: float) -> float:
    """안쪽 모터 값(rad) → motor_manager 토픽 단위 · supervisor 가 내보낼 때"""
    return units.convert(value_rad, units.RAD, MOTOR_NODE_UNIT)


def from_state(value: Any, unit: Optional[str] = None) -> Optional[float]:
    """motion_state 모터 값 → rad · 숫자가 아니면 None · `unit` 없으면 MOTOR_STATE_UNIT"""
    number = finite_float(value)
    return None if number is None else units.convert(number, unit or MOTOR_STATE_UNIT, units.RAD)


def _first(motor: Optional[Mapping[str, Any]], keys) -> Optional[float]:
    if motor is None:
        return None
    for key, unit in keys:
        number = from_state(motor.get(key), unit)
        if number is not None:
            return number
    return None


def motor_position(motor: Optional[Mapping[str, Any]]) -> Optional[float]:
    """motion_state 모터 한 개의 현재 위치 · rad"""
    return _first(motor, _POSITION_KEYS)


def motor_velocity(motor: Optional[Mapping[str, Any]]) -> Optional[float]:
    """motion_state 모터 한 개의 현재 속도 · rad/s"""
    return _first(motor, _VELOCITY_KEYS)


def motor_limit(motor: Mapping[str, Any], name: str) -> Optional[float]:
    """motion_state 모터의 하한·상한 · rad

    `lower`·`upper` 는 상태 모니터가 모터 설정 파일에서 그대로 옮겨 싣는 값이라
    **설정 파일 단위**(`MOTOR_CONFIG_UNIT`)다 · 위치(`MOTOR_STATE_UNIT`)와 따로 옮겨 간다.
    """
    number = finite_float(motor.get(f'{name}_rad'))
    if number is not None:
        return number
    number = finite_float(motor.get(name))
    return None if number is None else units.convert(number, MOTOR_CONFIG_UNIT, units.RAD)


def config_value(value_rad: float) -> float:
    """안쪽 모터 값(rad) → 모터 설정 파일 단위"""
    return units.convert(value_rad, units.RAD, MOTOR_CONFIG_UNIT)
