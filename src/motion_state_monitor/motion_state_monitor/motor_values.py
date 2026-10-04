"""모터 값 변환 · 순수 함수.

`MotionStateMonitor`에서 떼어냈다 · §6-34

**`unchecked_float`은 `motion_common.values.optional_float`과 다르다.** 이쪽은
`inf`·`nan`을 그대로 통과시킨다. 흡수하면 동작이 바뀌므로 이번에는 옮기기만 하고
이름으로 차이를 드러냈다 · §6-5의 '의도적으로 흡수하지 않은 변형'에 해당한다.

`parse_int`는 `motion_common.values.optional_int`와 완전히 같아서 그쪽으로 합쳤다.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from motion_common.values import optional_int as parse_int

MOTOR_TYPE_LABELS = {
    'minas': 'AC Servo',
    'zeroerr': 'ZeroErr Motor',
    'dynamixel': 'Dynamixel',
    'cubemars': 'CubeMars',
    'unknown': 'Unknown',
}

TRANSPORT_LABELS = {
    'ethercat': 'EtherCAT',
    'canopen': 'CANopen',
    'socketcan': 'SocketCAN',
    'serial': 'Serial',
    'unknown': 'Unknown',
}

__all__ = [
    'MOTOR_TYPE_LABELS', 'TRANSPORT_LABELS', 'parse_int',
    'pulse_per_revolution',
    'unchecked_float',
    'counts_to_degrees',
    'statusword_text',
    'dynamixel_statusword_text',
    'error_text',
    'normalized_errorcode',
    'hex16',
    'motor_type_label',
    'transport_label',
    'count_values',
    'array_value',
    'dynamixel_position_raw',
]


def pulse_per_revolution(metadata: Dict[str, Any]) -> Optional[float]:
    try:
        value = float(metadata.get('pulse_per_revolution') or 0.0)
    except (TypeError, ValueError):
        return None
    return value if value > 0.0 else None

def unchecked_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def counts_to_degrees(value: Optional[int], pulse_per_revolution: Optional[float]) -> Optional[float]:
    if value is None or not pulse_per_revolution:
        return None
    return float(value) / pulse_per_revolution * 360.0

def statusword_text(statusword: int) -> str:
    if statusword & 0x0008:
        return 'Fault'
    masked_6f = statusword & 0x006F
    masked_4f = statusword & 0x004F
    if masked_6f == 0x0027:
        return 'Operation enabled'
    if masked_6f == 0x0023:
        return 'Switched on'
    if masked_6f == 0x0021:
        return 'Ready to switch on'
    if masked_4f == 0x0040:
        return 'Switch on disabled'
    if masked_6f == 0x0007:
        return 'Quick stop active'
    if masked_4f == 0x000F:
        return 'Fault reaction active'
    if masked_4f == 0x0000:
        return 'Not ready to switch on'
    return 'Unknown status'

def dynamixel_statusword_text(statusword: int) -> str:
    return 'Torque enabled' if statusword & 0x01 else 'Torque disabled'

def error_text(errorcode: int, alarm_text: str) -> str:
    del alarm_text
    if errorcode == 0:
        return 'No error'
    return f'Error {float(errorcode):.1f}'

#: Dynamixel X 시리즈 Hardware Error Status(addr 70) 비트 · 2026-10-04
#: bit1 · bit6 · bit7 은 정의 없음 → `Unknown bit`
DYNAMIXEL_HARDWARE_ERROR_BITS = (
    (0x01, 'Input voltage error'),
    (0x04, 'Overheating error'),
    (0x08, 'Motor encoder error'),
    (0x10, 'Electrical shock error'),
    (0x20, 'Overload error'),
)

def dynamixel_error_text(errorcode: int) -> str:
    """Hardware Error Status → 비트 이름 · 복구는 전원 재투입(웹 수단 없음)."""
    code = int(errorcode) & 0xFF
    if code == 0:
        return 'No error'
    names = [name for bit, name in DYNAMIXEL_HARDWARE_ERROR_BITS if code & bit]
    known = sum(bit for bit, _ in DYNAMIXEL_HARDWARE_ERROR_BITS)
    unknown = code & ~known
    if unknown:
        names.append(f'Unknown bit 0x{unknown:02X}')
    return ' · '.join(names) + f' (0x{code:02X})'

def normalized_errorcode(raw_errorcode: int, metadata: Dict[str, Any]) -> int:
    if (
        str(metadata.get('motor_type', '')).lower() == 'minas'
        and (raw_errorcode & 0xFF00) == 0xFF00
        and (raw_errorcode & 0x00FF) != 0
    ):
        return raw_errorcode & 0x00FF
    return raw_errorcode

def hex16(value: int) -> str:
    return f'0x{int(value) & 0xFFFF:04X}'

def motor_type_label(motor_type: str) -> str:
    return MOTOR_TYPE_LABELS.get(str(motor_type), str(motor_type) or 'Unknown')

def transport_label(transport: str) -> str:
    return TRANSPORT_LABELS.get(str(transport), str(transport) or 'Unknown')

def count_values(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or 'Unknown')
        counts[value] = counts.get(value, 0) + 1
    return counts

def array_value(msg: Any, field: str, index: int, default: Any) -> Any:
    values = getattr(msg, field, None)
    if values is None or index >= len(values):
        return default
    return values[index]

def overload_ratio_pct(msg: Any, index: int) -> Optional[float]:
    """과부하율 % (모터 정격 대비 · MINAS 4D29h) · 안 읽는 축은 None.

    motor_manager 는 PDO 에 매핑하지 않은 축(기본)과 다이나믹셀에 음수를 싣는다 ·
    옛 메시지(칸 없음)도 None · 화면은 「-」로 그린다.
    """
    value = unchecked_float(array_value(msg, 'overload_ratio', index, None))
    if value is None or not math.isfinite(value) or value < 0.0:
        return None
    return round(value, 1)


def dynamixel_position_raw(
    position_deg: float,
    metadata: Dict[str, Any],
) -> Optional[int]:
    raw_per_degree = unchecked_float(metadata.get('position_raw_per_degree'))
    if raw_per_degree is None or math.isclose(raw_per_degree, 0.0):
        pulse_per_revolution = unchecked_float(metadata.get('pulse_per_revolution'))
        if pulse_per_revolution is None or pulse_per_revolution <= 0:
            return None
        raw_per_degree = pulse_per_revolution / 360.0

    zero_raw = unchecked_float(metadata.get('dynamixel_zero_position_raw'))
    if zero_raw is None:
        pulse_per_revolution = unchecked_float(metadata.get('pulse_per_revolution'))
        zero_raw = pulse_per_revolution / 2.0 if pulse_per_revolution else 0.0

    raw = int(round(zero_raw + (position_deg * raw_per_degree)))
    min_raw = unchecked_float(metadata.get('dynamixel_min_position_raw'))
    max_raw = unchecked_float(metadata.get('dynamixel_max_position_raw'))
    if min_raw is not None and max_raw is not None:
        lower = int(round(min(min_raw, max_raw)))
        upper = int(round(max(min_raw, max_raw)))
        raw = max(lower, min(upper, raw))
    return raw
