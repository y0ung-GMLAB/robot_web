"""모터 종류 표 · 한 곳에서 판단 · 수정 목록 158 (`docs/SERIAL_SERVO_DESIGN.md` §1)

전에는 같은 「이 모터가 무엇인가」 판단이 여러 곳에 문자열 추측으로 복사돼 있었다
(`motor_config_rules.is_ac_servo_motor` · `is_dynamixel_motor` · `motor_ref.motor_type` ·
`supervisor_node._is_ac_servo` · `_is_dynamixel` · `connection_state` 의 serial ⇒ 다이나믹셀) ·
모두 이 표를 부른다.

    kind        driver_family  transport  패킷   짧은 이름  토크 켜기/끄기  재부팅  다회전
    ac_servo    minas          ethercat   CiA402  AC        서보 ON/OFF     알람 리셋  드라이브
    dynamixel   dynamixel      serial     dxl2    DXL       O               O        Extended(4)
    feetech     feetech        serial     scs     FT        O               X        X (0~4095)

- 판단 근거 · 모터 dict 의 `motor_type` · `motor_type_label` · `driver_model` · `driver_name` ·
  `transport` 를 소문자로 이은 글 · 옛 판정과 같은 낱말 · 같은 순서 (다이나믹셀 → AC)
- 새 낱말 · `feetech` 만 · **맨 먼저** 본다 · 이 낱말이 없는 모터(ac_servo · minas · dynamixel ·
  unknown · 칸 없음 · cubemars · zeroerr · 옛 `serial`+`xm` 추측 …)는 옛 판정과 **결과가 같다**
  (사용자 조건 · AC 로봇 동작 변화 없음 · `test_motor_kinds.py` 가 옛 구현과 표로 맞춰 본다)
- 모르는 종류 · `motor_kind` 는 `unknown` · 옛 호출부의 결과는 옛 그대로 둔다
- `is_serial_servo` · 다이나믹셀 · Feetech 공통 동작(토크 · 조그 · 절대 이동 · 오류 표시 · 전류)
- 종류별 동작(재부팅 · 모델 이름 · 검색)은 kind 로 따로
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

__all__ = [
    'AC_SERVO',
    'DYNAMIXEL',
    'FEETECH',
    'UNKNOWN',
    'KINDS',
    'SERIAL_SERVO_KINDS',
    'KIND_TABLE',
    'kind_text',
    'kind_from_text',
    'motor_kind',
    'is_ac_servo',
    'is_dynamixel',
    'is_feetech',
    'is_serial_servo',
    'kind_info',
    'kind_for_driver_type',
    'kind_table_payload',
]

AC_SERVO = 'ac_servo'
DYNAMIXEL = 'dynamixel'
FEETECH = 'feetech'
UNKNOWN = 'unknown'

#: 표 순서 · 화면 목록 순서도 이것
KINDS: Tuple[str, ...] = (AC_SERVO, DYNAMIXEL, FEETECH)
SERIAL_SERVO_KINDS: Tuple[str, ...] = (DYNAMIXEL, FEETECH)

#: 종류 표 · 화면 사본 `static/v2/js/motor_kinds.js` · 서버가 `kind_table` 로 내려준다
KIND_TABLE: Dict[str, Dict[str, Any]] = {
    AC_SERVO: {
        'kind': AC_SERVO,
        'driver_family': 'minas',
        'transport': 'ethercat',
        'packet': 'cia402',
        'short_label': 'AC',
        'label': 'AC 서보',
        'type_label': 'AC Servo',
        'serial_servo': False,
        'capabilities': {
            'servo_power': True,      # 서보 ON/OFF (CiA402)
            'torque_toggle': False,   # 직렬 서보의 토크 켜기/끄기 아님
            'fault_reset': True,      # 알람 리셋
            'reboot': False,
            'multiturn': True,        # 드라이브 다회전 · 다회전 클리어
            'drive_gains': True,
            'eeprom_save': True,
            'absolute_mode': True,
            'overload_ratio': True,
            'brake_delay': True,
            'torque_reading': True,   # effort = 토크
            'current_reading': False,
        },
    },
    DYNAMIXEL: {
        'kind': DYNAMIXEL,
        'driver_family': 'dynamixel',
        'transport': 'serial',
        'packet': 'dxl2',
        'short_label': 'DXL',
        'label': '다이나믹셀',
        'type_label': 'Dynamixel',
        'serial_servo': True,
        'capabilities': {
            'servo_power': False,
            'torque_toggle': True,
            'fault_reset': False,
            'reboot': True,           # REBOOT 0x08 · 하드웨어 오류 해제
            'multiturn': True,        # Extended Position(4)
            'drive_gains': False,
            'eeprom_save': False,
            'absolute_mode': False,
            'overload_ratio': False,
            'brake_delay': False,
            'torque_reading': False,
            'current_reading': True,  # effort = 전류
        },
    },
    FEETECH: {
        'kind': FEETECH,
        'driver_family': 'feetech',
        'transport': 'serial',
        'packet': 'scs',
        'short_label': 'FT',
        'label': 'Feetech',
        'type_label': 'Feetech',
        'serial_servo': True,
        'capabilities': {
            'servo_power': False,
            'torque_toggle': True,
            'fault_reset': False,
            'reboot': False,          # 재부팅 없음 · 0x06 = 공장 초기화 · 금지
            'multiturn': False,       # 한 바퀴 · raw 0~4095
            'drive_gains': False,
            'eeprom_save': False,
            'absolute_mode': False,
            'overload_ratio': False,
            'brake_delay': False,
            'torque_reading': False,
            'current_reading': True,
        },
    },
}

#: kind 를 가리키는 낱말 · 판단 순서 = 이 순서
#: **Feetech 먼저** · `feetech` 낱말이 있는 모터만 새 동작 · 다이나믹셀·`serial`+`xm` 추측에 빠지지 않는다
#: 그 밖(낱말 `feetech` 없음)은 옛 `motor_ref.motor_type` 과 같은 순서 (다이나믹셀 → AC) · 결과도 같다
_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (FEETECH, ('feetech',)),
    (DYNAMIXEL, ('dynamixel',)),
    (AC_SERVO, ('minas', 'ac servo', 'ac_servo')),
)

#: 판단에 쓰는 칸 · 옛 판정 다섯 곳이 모두 이 다섯 칸을 이 순서로 읽었다
_TEXT_FIELDS: Tuple[str, ...] = (
    'motor_type', 'motor_type_label', 'driver_model', 'driver_name', 'transport',
)

#: 모터 설정 파일 `drivers[].type` → kind
_DRIVER_TYPE_KIND = {
    'minas': AC_SERVO,
    'dynamixel': DYNAMIXEL,
    'feetech': FEETECH,
}


def kind_text(motor: Optional[Mapping[str, Any]]) -> str:
    """판단 글 · 다섯 칸을 소문자로 이어 붙인다."""
    if not isinstance(motor, Mapping):
        return ''
    return ' '.join(str(motor.get(field) or '').lower() for field in _TEXT_FIELDS)


def _mentions(text: str, kind: str) -> bool:
    for name, words in _KEYWORDS:
        if name == kind:
            return any(word in text for word in words)
    return False


def kind_from_text(text: str, *, serial_xm_is_dynamixel: bool = False) -> str:
    """글 → kind · 처음 맞는 낱말이 이긴다.

    `serial_xm_is_dynamixel` · 옛 `supervisor_node._is_dynamixel` 규칙(`serial` 과 `xm` 이 같이
    있으면 다이나믹셀) · 그 호출부만 켠다 · 다른 곳 판정은 바꾸지 않는다.
    """
    lowered = str(text or '').lower()
    for kind, words in _KEYWORDS:
        if any(word in lowered for word in words):
            return kind
    if serial_xm_is_dynamixel and 'serial' in lowered and 'xm' in lowered:
        return DYNAMIXEL
    return UNKNOWN


def motor_kind(
    motor: Optional[Mapping[str, Any]], *, serial_xm_is_dynamixel: bool = False,
) -> str:
    """모터 dict → `ac_servo` | `dynamixel` | `feetech` | `unknown`."""
    return kind_from_text(kind_text(motor), serial_xm_is_dynamixel=serial_xm_is_dynamixel)


def is_ac_servo(motor: Optional[Mapping[str, Any]]) -> bool:
    """옛 `is_ac_servo_motor` · `_is_ac_servo` 와 같은 판정 · AC 낱말이 하나라도 있으면 참.

    Feetech 로 밝혀진 모터만 거짓 · 그 밖은 옛 결과 그대로.
    """
    text = kind_text(motor)
    return not _mentions(text, FEETECH) and _mentions(text, AC_SERVO)


def is_dynamixel(
    motor: Optional[Mapping[str, Any]], *, serial_xm_is_dynamixel: bool = False,
) -> bool:
    """옛 `is_dynamixel_motor` · `_is_dynamixel` 와 같은 판정 · Feetech 로 밝혀진 모터만 거짓."""
    text = kind_text(motor)
    if _mentions(text, FEETECH):
        return False
    if _mentions(text, DYNAMIXEL):
        return True
    return bool(serial_xm_is_dynamixel and 'serial' in text and 'xm' in text)


def is_feetech(motor: Optional[Mapping[str, Any]]) -> bool:
    return _mentions(kind_text(motor), FEETECH)


def is_serial_servo(kind_or_motor: Any, *, serial_xm_is_dynamixel: bool = False) -> bool:
    """다이나믹셀 · Feetech 공통 동작인가 · kind 글자나 모터 dict 둘 다 받는다."""
    if isinstance(kind_or_motor, Mapping):
        if is_dynamixel(kind_or_motor, serial_xm_is_dynamixel=serial_xm_is_dynamixel):
            return True
        return is_feetech(kind_or_motor)
    return str(kind_or_motor or '').strip().lower() in SERIAL_SERVO_KINDS


def kind_info(kind: Any) -> Dict[str, Any]:
    """kind → 표 한 줄 · 모르는 종류는 빈 dict."""
    return dict(KIND_TABLE.get(str(kind or '').strip().lower(), {}))


def kind_for_driver_type(driver_type: Any) -> str:
    """모터 설정 파일 `drivers[].type` (`minas` · `dynamixel` · `feetech`) → kind."""
    return _DRIVER_TYPE_KIND.get(str(driver_type or '').strip().lower(), UNKNOWN)


def kind_table_payload(kinds: Iterable[str] = KINDS) -> Dict[str, Dict[str, Any]]:
    """화면에 내려줄 표 · `kind_table`."""
    return {kind: kind_info(kind) for kind in kinds if kind in KIND_TABLE}
