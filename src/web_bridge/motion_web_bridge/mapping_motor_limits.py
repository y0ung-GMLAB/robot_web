"""조인트 매핑 범위 → 모터 운전 한계(drivers[].lower/upper) · 2026-10-02

리밋의 원본은 **조인트 매핑의 최소·최대 하나**다 (사용자 결정).
모터 설정의 `lower/upper`(모터 쪽 값)는 사람이 따로 적는 값이 아니라 여기서
환산해 넣는 값이다 · 그래서 재생 클리핑(plan_builder)과 드라이브 soft limit
(MINAS 0x607D 등 · motor_manager 가 부팅 때 씀)이 늘 같은 범위를 쓴다.

    motor = ref + (motion + offset) × scale × sign × gear

식은 `motion_common.joint_mapping` 하나다 · 매핑은 rad, 모터 설정 파일은
`wire_units.MOTOR_CONFIG_UNIT`(motor_manager 입력이 rad 가 될 때까지 deg) · 수정 목록 6.
Dynamixel 도 같은 식 · 감속·기어비는 줄에 적힌 값 그대로 (외부 기어 사용 사례) ·
Dynamixel 은 Extended Position 모드라 드라이브 Min/Max Position Limit 이
안 먹고, 한계는 supervisor·plan_builder 가 이 `lower/upper` 로 지킨다 ·
2026-10-04 「감속비 1 고정」·「±180 한 바퀴 클램프」 폐지 (사용자 결정).

모터 고르기는 런타임과 같다 · `motor_ref` 가 있으면 그 이름으로, 없으면
옛 파일처럼 `motor_axis`(controller_index)로.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from motion_common import joint_mapping, units, wire_units
from motion_common import motor_ref as motor_ref_rules
from motion_common.values import optional_int

from motion_web_bridge.motor_config_rules import expand_shared_driver_profiles

#: 파일에 적을 자릿수 · deg 면 0.001° · rad 면 1e-6 rad(≈0.00006°)
LIMIT_DECIMALS = 3 if wire_units.MOTOR_CONFIG_UNIT == units.DEG else 6


def _float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float('inf') else default


def motor_target(row: Dict[str, Any], motion_value: float) -> float:
    """조인트 rad → 모터 rad · `joint_mapping.motor_target` 그대로."""
    return joint_mapping.motor_target(row, motion_value, units.RAD)


def row_motor_limits(row: Dict[str, Any]) -> Tuple[float, float]:
    """한 줄의 조인트 범위를 모터 설정 단위 (하한, 상한)으로 · 반전이면 뒤집혀 정렬된다."""
    lower = joint_mapping.angle(row, 'motion_lower', units.RAD)
    upper = joint_mapping.angle(row, 'motion_upper', units.RAD)
    first = wire_units.config_value(motor_target(row, lower))
    second = wire_units.config_value(motor_target(row, upper))
    low, high = min(first, second), max(first, second)
    return round(low, LIMIT_DECIMALS), round(high, LIMIT_DECIMALS)


def mapping_rows(mapping: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = (mapping or {}).get('mappings')
    if rows is None:
        rows = (mapping or {}).get('axes')
    return [row for row in rows or [] if isinstance(row, dict)]


def _config_axes(config: Dict[str, Any]) -> Iterable[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
    """(슬레이브, 드라이버, 런타임 모양의 모터 dict) · motor_ref 로 찾기 위한 모양."""
    drivers = {
        optional_int(driver.get('id'), None): driver
        for driver in config.get('drivers') or []
        if isinstance(driver, dict)
    }
    for master in config.get('masters') or []:
        if not isinstance(master, dict):
            continue
        for slave in master.get('slaves') or []:
            if not isinstance(slave, dict):
                continue
            driver = drivers.get(optional_int(slave.get('driver_id'), None))
            if driver is None:
                continue
            driver_type = str(driver.get('type') or '')
            motor = {
                'controller_index': optional_int(slave.get('controller_index'), None),
                'motor_type': 'dynamixel' if driver_type == 'dynamixel' else driver_type,
            }
            if master.get('type') == 'serial':
                motor.update({
                    'bus_id': optional_int(slave.get('bus_id'), None),
                    'serial_port': str(master.get('serial_port') or ''),
                })
            else:
                motor.update({
                    'ethercat_master_index': optional_int(master.get('ethercat_master_index'), 0),
                    'ethercat_alias': optional_int(slave.get('alias'), None),
                    'slave_position': optional_int(
                        slave.get('ring_position'), optional_int(slave.get('position'), None),
                    ),
                })
            yield slave, driver, motor


def _row_matches(row: Dict[str, Any], motor: Dict[str, Any]) -> bool:
    ref = str(row.get('motor_ref') or '').strip()
    if ref:
        return bool(motor_ref_rules.motors_for_ref(ref, [motor]))
    axis = optional_int(row.get('motor_axis'), None)
    return axis is not None and axis == motor.get('controller_index')


def apply_mapping_limits(
    config: Dict[str, Any],
    mapping: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """매핑 범위를 모터 설정 드라이버 lower/upper 에 넣는다.

    돌려주는 값 · (새 설정, 바뀐 축 목록) · 매핑이 없거나 연결된 줄이 없는
    모터는 그대로 둔다 · 같은 모터에 줄이 여럿이면 가장 좁은 범위.
    """
    if not isinstance(config, dict) or mapping is None:
        return config, []
    # 드라이버를 축마다 하나로 · 공유된 드라이버에 쓰면 다른 축 한계가 같이 바뀐다
    result = expand_shared_driver_profiles(config)
    rows = [row for row in mapping_rows(mapping) if row.get('enabled', True) is not False]
    changes: List[Dict[str, Any]] = []
    for slave, driver, motor in _config_axes(result):
        limits = [
            row_motor_limits(row)
            for row in rows
            if _row_matches(row, motor)
        ]
        if not limits:
            continue
        lower = max(item[0] for item in limits)
        upper = min(item[1] for item in limits)
        if lower > upper:
            # 줄끼리 범위가 안 겹친다 · 매핑 검증이 잡아야 할 일 · 드라이버는 건드리지 않는다
            continue
        previous = (driver.get('lower'), driver.get('upper'))
        if (_float(previous[0], None), _float(previous[1], None)) == (lower, upper):
            continue
        driver['lower'] = lower
        driver['upper'] = upper
        changes.append({
            'controller_index': motor.get('controller_index'),
            'lower': lower,
            'upper': upper,
            'previous_lower': previous[0],
            'previous_upper': previous[1],
        })
    return result, changes


def active_mapping(repository) -> Optional[Dict[str, Any]]:
    """선택된 프로젝트의 등록된 조인트 매핑 · 없거나 못 읽으면 None."""
    if repository is None:
        return None
    project_id = repository.selected_project_id()
    if not project_id:
        return None
    name = repository.active_file_name(project_id, 'motion_axis_matching')
    if not name:
        return None
    try:
        content = repository.read_file(project_id, 'motion_axis_matching', name)['content']
        mapping = yaml.safe_load(content)
    except (OSError, ValueError, KeyError, yaml.YAMLError):
        return None
    return mapping if isinstance(mapping, dict) else None
