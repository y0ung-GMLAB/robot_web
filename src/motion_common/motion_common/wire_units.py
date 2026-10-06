"""모터 쪽 경계 단위 · 아직 deg 인 곳 · 수정 목록 6 (2026-10-06)

안쪽(조인트 매핑 · 재생 계획 · 조인트 값 · 재생 상태)은 rad 다 · 모터 쪽 세 곳은
아직 deg 라서 그 경계에서만 바꾼다 · 경계는 이 모듈의 함수만 부른다.

    MOTOR_NODE_UNIT      motor_manager 토픽 (motor_status · motor_command 의 position)
                         · motor_manager 입력이 rad 가 되면(6-1) rad
    MOTOR_COMMAND_UNIT   재생 → supervisor 명령 토픽 (MotorStatus.position)
                         · supervisor 가 rad 로 옮겨 가면(6-4) rad
    MOTOR_STATE_UNIT     motion_state JSON 의 motors[] 위치·한계 (`position_deg` · `lower` · `upper`)
                         · 상태 발행이 rad 로 옮겨 가면(6-5) rad
    MOTOR_CONFIG_UNIT    모터 설정 파일 drivers[].lower/upper · motor_manager 입력이 rad 가 되면(6-1) rad

상수 하나를 바꾸면 그 경계가 통째로 옮겨 간다.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from . import units
from .values import finite_float

MOTOR_NODE_UNIT = units.DEG
MOTOR_COMMAND_UNIT = units.DEG
MOTOR_STATE_UNIT = units.DEG
MOTOR_CONFIG_UNIT = units.DEG

#: 모터 상태의 위치 칸 · 앞에서부터 처음 있는 값 · 단위 이름이 붙은 칸이 먼저
_POSITION_KEYS_RAD = ('position_rad',)
_POSITION_KEYS_STATE = (
    'position_deg',
    'position_actual_deg',
    'output_position_deg',
    'present_position_deg',
    'position_actual',
    'position',
)


def from_motor_node(value: float) -> float:
    """motor_manager 토픽 위치 → rad"""
    return units.convert(value, MOTOR_NODE_UNIT, units.RAD)


def command_value(value_rad: float) -> float:
    """안쪽 모터 값(rad) → 명령 토픽 단위"""
    return units.convert(value_rad, units.RAD, MOTOR_COMMAND_UNIT)


def from_state(value: Any) -> Optional[float]:
    """motion_state 모터 값 → rad · 숫자가 아니면 None"""
    number = finite_float(value)
    return None if number is None else units.convert(number, MOTOR_STATE_UNIT, units.RAD)


def motor_position(motor: Optional[Mapping[str, Any]]) -> Optional[float]:
    """motion_state 모터 한 개의 현재 위치 · rad"""
    if motor is None:
        return None
    for key in _POSITION_KEYS_RAD:
        number = finite_float(motor.get(key))
        if number is not None:
            return number
    for key in _POSITION_KEYS_STATE:
        number = from_state(motor.get(key))
        if number is not None:
            return number
    return None


def motor_limit(motor: Mapping[str, Any], name: str) -> Optional[float]:
    """motion_state 모터의 하한·상한(`lower`·`upper`) · rad"""
    number = finite_float(motor.get(f'{name}_rad'))
    if number is not None:
        return number
    return from_state(motor.get(name))


def config_value(value_rad: float) -> float:
    """안쪽 모터 값(rad) → 모터 설정 파일 단위"""
    return units.convert(value_rad, units.RAD, MOTOR_CONFIG_UNIT)
