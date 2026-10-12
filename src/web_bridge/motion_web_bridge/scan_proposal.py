"""검색 결과 → 모터 설정 제안 · 서버에서 한 번만 · 수정 목록 100 (2026-10-12)

전에는 화면(motor_config.js `adoptScanIntoDraft`)이 검색 응답을 받아 모터 목록을 새로 만들었다 ·
두 화면(기존 · 새 UI)이 같은 일을 하려면 같은 규칙을 두 번 짜야 해서 서버로 옮긴다.
짝 맞추기는 `scan_axis_rows.axis_rows_from_scan` 그대로(§6-216) · 여기서는 「그래서 목록을 어떻게
바꾸나」 만 한다.

옮기면서 바꾼 것(사용자 결정 2026-10-12 「추천대로」)

    검색한 통로만 바꾼다       AC 만 검색하면 다이나믹셀 모터는 그대로 둔다(전에는 사라졌다 · §6-219 의 「목록 =
                              검색 결과」 는 검색한 통로 안에서만)
    짝지은 모터는 저장된 것에서  이름 · 사용 · 드라이브 연결(driver_id → 속도·가속·브레이크 같은 드라이브 값)을 지킨다 ·
                              주소·식별값·모델만 검색값으로 (전에는 이름만 남고 나머지는 기본값이 됐다)
    이름표(id)는 서버 규칙 하나  `motor_id_for` · 화면이 따로 만들지 않는다(§6-215 · alias 가 바뀌면 이름이 풀리던 것)
    번호는 빈칸 없이           0 부터 차례로 다시 매긴다 · 바뀐 번호는 notes 로 알린다(조인트 매핑 확인 · 번호로만 가리킨
                              매핑 줄이 있으면 엉뚱한 모터를 가리킬 수 있다)

검색에서 안 보인 모터(검색한 통로인데 짝이 없음)는 뺀다 · 위치만 같아 짝지은 것(연결 확인 필요)은 넣되 알린다.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from motion_common.values import optional_int

from motion_web_bridge.motor_config_rules import motor_id_for
from motion_web_bridge.motor_identity import model_is_unknown
from motion_web_bridge import scan_axis_rows

DYNAMIXEL_DEFAULT_BAUDRATE = 1_000_000


def _raw_slave(slaves: List[Dict[str, Any]], scanned: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    master = optional_int(scanned.get('master_index'), 0)
    position = optional_int(scanned.get('slave_position'), None)
    for slave in slaves:
        if optional_int(slave.get('master_index'), 0) == master and optional_int(slave.get('slave_position'), None) == position:
            return slave
    return None


def _raw_device(devices: List[Dict[str, Any]], scanned: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    bus = optional_int(scanned.get('bus_id'), None)
    port = str(scanned.get('serial_port') or '')
    for device in devices:
        if optional_int(device.get('id'), None) == bus and str(device.get('port') or '') == port:
            return device
    return None


def _ac_identity(slave: Dict[str, Any], scanned: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'ethercat_master_index': optional_int(scanned.get('master_index'), 0),
        'ethercat_alias': scanned.get('alias'),
        'rotary_alias': scanned.get('rotary_alias'),
        'slave_position': scanned.get('slave_position'),
        'identity_source': str(slave.get('identity_source') or 'physical_sii'),
        'vendor_id': scanned.get('vendor_id'),
        'product_code': scanned.get('product_code'),
        'revision_number': scanned.get('revision_number'),
        'serial_number': scanned.get('serial_number'),
        'sii_order_number': str(slave.get('sii_order_number') or slave.get('order_number') or ''),
        'sii_device_name': str(slave.get('sii_device_name') or slave.get('device_name') or ''),
    }


def _ac_address(scanned: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'ethercat_master_index': optional_int(scanned.get('master_index'), 0),
        'alias': scanned.get('alias'),
        # 사람이 보는 Slave 값(링 위치) · §6-207 · 마스터 주소(alias 면 0)는 저장 때 서버가 만든다
        'position': scanned.get('slave_position'),
        'vendor_id': scanned.get('vendor_id'),
        'product_id': scanned.get('product_code'),
        'revision_number': scanned.get('revision_number'),
        'serial_number': scanned.get('serial_number'),
    }


def _dxl_identity(scanned: Dict[str, Any], baudrate: Any) -> Dict[str, Any]:
    bus = scanned.get('bus_id')
    return {'node_id': bus, 'bus_id': bus, 'serial_port': str(scanned.get('serial_port') or ''), 'serial_baudrate': baudrate}


def _scanned_profile(scanned: Dict[str, Any], transport: str) -> Optional[Dict[str, Any]]:
    model = str(scanned.get('model') or '').strip()
    if not model or model_is_unknown(model):
        return None
    return {
        'driver_model': model,
        'model_confirmed': True,
        'model_source': 'physical_sii' if transport == 'ethercat' else 'physical_protocol',
    }


def _motor_id(motor: Dict[str, Any]) -> str:
    identity = motor.get('identity') or {}
    config = motor.get('config') or {}
    return motor_id_for(
        motor_type=str(motor.get('motor_type') or ''),
        transport=str(motor.get('transport') or ''),
        axis=motor.get('axis'),
        ethercat_master_index=identity.get('ethercat_master_index', config.get('ethercat_master_index')),
        alias=identity.get('ethercat_alias', config.get('alias')),
        rotary_alias=identity.get('rotary_alias'),
        slave_position=identity.get('slave_position', config.get('position')),
        serial_port=identity.get('serial_port') or config.get('serial_port'),
        bus_id=identity.get('bus_id', config.get('bus_id')),
    )


def _matched_motor(saved: Dict[str, Any], scanned: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """저장된 모터 그대로 · 주소·식별값·모델만 검색값"""
    motor = copy.deepcopy(saved)
    transport = str(motor.get('transport') or '')
    identity = dict(motor.get('identity') or {})
    config = dict(motor.get('config') or {})
    if transport == 'ethercat':
        identity.update(_ac_identity(raw, scanned))
        config.update(_ac_address(scanned))
    else:
        baudrate = identity.get('serial_baudrate') or config.get('serial_baudrate') or DYNAMIXEL_DEFAULT_BAUDRATE
        identity.update(_dxl_identity(scanned, baudrate))
        config.update({'bus_id': scanned.get('bus_id'), 'serial_port': str(scanned.get('serial_port') or ''), 'serial_baudrate': baudrate})
    motor['identity'] = identity
    motor['config'] = config
    profile = _scanned_profile(scanned, transport)
    if profile is not None:
        motor['profile'] = profile
    return motor


def _new_motor(row: Dict[str, Any], raw: Dict[str, Any], dxl_driver_id: int) -> Dict[str, Any]:
    scanned = row['scanned']
    axis = row['proposed_axis']
    if row['transport'] == 'ethercat':
        alias = scanned.get('alias')
        name = f'alias {alias}' if optional_int(alias, 0) else f'slave {scanned.get("slave_position")}'
        profile = _scanned_profile(scanned, 'ethercat') or {'driver_model': '', 'model_confirmed': False, 'model_source': ''}
        return {
            'id': row['id'], 'enabled': True, 'hidden': False, 'deleted': False, 'axis': axis, 'name': name,
            'motor_type': 'ac_servo', 'driver_family': 'minas', 'transport': 'ethercat',
            'identity': _ac_identity(raw, scanned),
            'profile': profile,
            'config': {'controller_index': axis, 'driver_id': 0, 'profile_mode': 0, **_ac_address(scanned)},
        }
    bus = scanned.get('bus_id')
    profile = _scanned_profile(scanned, 'serial') or {'driver_model': '', 'model_confirmed': False, 'model_source': ''}
    return {
        'id': row['id'], 'enabled': True, 'hidden': False, 'deleted': False, 'axis': axis,
        'name': f'ID {bus}' if bus is not None else 'ID -',
        'motor_type': 'dynamixel', 'driver_family': 'dynamixel', 'transport': 'serial',
        'identity': _dxl_identity(scanned, DYNAMIXEL_DEFAULT_BAUDRATE),
        'profile': profile,
        'config': {'controller_index': axis, 'driver_id': dxl_driver_id, 'bus_id': bus,
                   'serial_port': str(scanned.get('serial_port') or ''), 'serial_baudrate': DYNAMIXEL_DEFAULT_BAUDRATE,
                   'profile_mode': 0},
    }


def _label(motor: Dict[str, Any]) -> str:
    name = str(motor.get('name') or '').strip()
    return f'{motor.get("axis")}번{f" · {name}" if name else ""}'


def proposed_registry(registry: Dict[str, Any], scan: Dict[str, Any], axis_rows: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """저장된 모터 목록 + 검색 결과 → 제안 목록 · {registry, notes, summary}"""
    registry = registry or {}
    scan = scan or {}
    rows = axis_rows or scan_axis_rows.axis_rows_from_scan(registry, scan)
    scanned_transports = set(rows.get('scanned_transports') or [])
    slaves = [s for s in (scan.get('ethercat_scan') or {}).get('slaves') or [] if isinstance(s, dict)]
    devices = [d for d in (scan.get('dynamixel_scan') or {}).get('devices') or [] if isinstance(d, dict)]
    saved = {str(m.get('id')): m for m in registry.get('motors') or [] if isinstance(m, dict) and not m.get('deleted')}
    dxl_driver_id = next((optional_int((m.get('config') or {}).get('driver_id'), None) for m in saved.values()
                          if m.get('transport') != 'ethercat' and optional_int((m.get('config') or {}).get('driver_id'), None) is not None), 1)

    notes: List[str] = []
    picked: List[Tuple[int, int, Dict[str, Any], Optional[int], bool]] = []   # (정렬 번호, 순서, 모터, 저장 번호, 이름표 새로)
    counts = {'matched': 0, 'added': 0, 'removed': 0, 'kept': 0}
    order = 0

    for row in rows.get('axes') or []:
        motor = saved.get(str(row.get('id')))
        if motor is None:
            continue
        old_axis = row.get('axis')
        if row['state'] == 'not_scanned':
            # 검색 안 한 통로 · 손대지 않는다(이름표도 그대로)
            picked.append((old_axis if old_axis is not None else 10_000, order, copy.deepcopy(motor), old_axis, False))
            counts['kept'] += 1
        elif row['state'] == 'missing':
            notes.append(f'{_label(motor)} · 검색되지 않아 목록에서 뺍니다. 배선과 전원을 확인하세요.')
            counts['removed'] += 1
        else:
            raw = _raw_slave(slaves, row['scanned']) if motor.get('transport') == 'ethercat' else _raw_device(devices, row['scanned'])
            matched = _matched_motor(motor, row['scanned'], raw or {})
            picked.append((old_axis if old_axis is not None else 10_000, order, matched, old_axis, True))
            counts['matched'] += 1
            if row.get('confirmation_required'):
                notes.append(f'{_label(motor)} · 위치만 같아서 연결했습니다. 같은 드라이브가 맞는지 확인하세요.')
            if row.get('changed'):
                notes.append(f'{_label(motor)} · 바뀐 값 {", ".join(row["changed"])}')
        order += 1

    for row in rows.get('new_devices') or []:
        raw = _raw_slave(slaves, row['scanned']) if row['transport'] == 'ethercat' else _raw_device(devices, row['scanned'])
        motor = _new_motor(row, raw or {}, dxl_driver_id)
        picked.append((row['proposed_axis'], order, motor, None, True))
        counts['added'] += 1
        if row.get('association_candidates'):
            notes.append(f'새 장치 {motor["name"]} · 같은 위치의 모터가 여럿({", ".join(str(a) for a in row["association_candidates"])}번)이라 새로 추가했습니다. 어느 모터인지 확인하세요.')
        order += 1

    # 번호 · 0 부터 빈칸 없이 · 순서는 지금 번호대로
    picked.sort(key=lambda item: (item[0], item[1]))
    motors = []
    renumbered = []
    for index, (_sort, _order, motor, old_axis, refresh_id) in enumerate(picked):
        motor['axis'] = index
        motor.setdefault('config', {})['controller_index'] = index
        if refresh_id:
            motor['id'] = _motor_id(motor)
        if old_axis is not None and old_axis != index:
            name = str(motor.get('name') or '')
            renumbered.append(f'{old_axis}번 → {index}번' + (f' ({name})' if name else ''))
        motors.append(motor)
    if renumbered:
        notes.append(f'모터 번호가 바뀝니다 · {" · ".join(renumbered)}. 번호로 연결된 조인트 매핑 줄을 확인하세요.')

    return {
        'registry': {'version': int(registry.get('version') or 1), 'motors': motors},
        'notes': notes,
        'summary': {**counts, 'renumbered': len(renumbered), 'scanned_transports': sorted(scanned_transports)},
    }
