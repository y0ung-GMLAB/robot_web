"""직렬 서보 param 파일 생성 · Dynamixel · Feetech · 수정 목록 158 (`docs/SERIAL_SERVO_DESIGN.md` §3)

MINAS 의 `minas_params` 와 같은 방식 · 저장 때 드라이버마다 제 파일을 만들고
`drivers[].param_file` 에 **절대경로**를 적는다 (배포 설정은 프로젝트 runtime 폴더로
복사되므로 상대경로는 어긋난다).

    재료   패킷 종류 기본 yaml  config/serial_servo/dynamixel_x.yaml · dynamixel_p.yaml · feetech_sts.yaml
           + 모델 제어표          (motion_common.serial_servo_models)
           + 시리즈 값            전류 없는 모델 → 전류 칸 optional
    결과   config/serial_params/driver_<id>.yaml

- XM540-W150 · W270 결과 = 옛 `config/dynamixel_xm540_*.yaml` (`model_file` 만 절대경로) · 회귀 시험
- 옛 정적 파일은 그대로 둔다 · 저장 전 옛 설정 파일이 아직 가리킨다
- 모델을 모르는 다이나믹셀 · 전과 같이 XM540-W270 제어표 (전 동작 그대로 · `model_warning` 표시)
- 한 포트 = 한 종류 · 다이나믹셀과 Feetech 를 한 포트에 두면 저장 거부 (`port_kind_conflicts`)
- 한 포트 = 한 속도 · 같은 포트에 속도가 다른 모터를 두면 저장 거부 (`port_baudrate_conflicts`) · 수정 목록 161
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from motion_common import serial_servo_models
from motion_common.values import optional_int

OUTPUT_DIR = 'serial_params'
TEMPLATE_DIR = Path('config') / 'serial_servo'

#: 모델을 모를 때 · 전과 같은 제어표 (`dynamixel_param_file_for_model` 의 기본)
DYNAMIXEL_FALLBACK_MODEL = 'XM540-W270-R'

#: 전류 칸 · 전류 없는 모델에서 optional
_CURRENT_INTERFACES = ('Goal Current', 'Present Current')


def output_root(workspace_root: Path) -> Path:
    """생성 파일 폴더 · 시험이 바꿔 끼운다."""
    return Path(workspace_root) / 'config' / OUTPUT_DIR


def is_generated_path(workspace_root: Path, path: Any) -> bool:
    """이 모듈이 만든 파일인가 · 정규화가 덮어쓰지 않게."""
    text = str(path or '').strip()
    if not text:
        return False
    try:
        return Path(text).resolve().parent == output_root(workspace_root).resolve()
    except OSError:
        return False


def _template(workspace_root: Path, name: str) -> Dict[str, Any]:
    path = Path(workspace_root) / TEMPLATE_DIR / f'{name}.yaml'
    if not path.is_file():
        # 작업 폴더에 없으면 설치된 저장소 기본 (`paths.workspace_root`)
        from motion_common import paths

        path = paths.workspace_root() / TEMPLATE_DIR / f'{name}.yaml'
    try:
        document = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f'직렬 서보 기본 파일을 읽지 못했습니다 · {path} · {exc}') from exc
    if not isinstance(document, dict):
        raise ValueError(f'직렬 서보 기본 파일 형식이 올바르지 않습니다 · {path}')
    return document


def model_info(
    workspace_root: Path, kind: str, driver_model: Any = '', model_number: Any = None,
) -> Dict[str, Any]:
    """param 파일을 고를 모델 사실 · 다이나믹셀 모델을 모르면 옛 기본(XM540-W270)."""
    info = serial_servo_models.serial_model(
        workspace_root, kind, model_number=model_number, model_name=driver_model,
    )
    if kind == 'dynamixel' and not info.get('model_file'):
        fallback = serial_servo_models.dynamixel_model(
            workspace_root, model_name=DYNAMIXEL_FALLBACK_MODEL,
        )
        fallback['model_warning'] = (
            f'다이나믹셀 모델 확인 필요 ({info.get("model_name") or driver_model or "모름"}) · '
            f'{DYNAMIXEL_FALLBACK_MODEL} 제어표로 동작'
        )
        fallback['requested_model'] = info
        return fallback
    return info


def build_document(
    workspace_root: Path, kind: str, driver_model: Any = '', model_number: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(param 문서, 모델 사실) · 파일은 `write_param_file` 이 쓴다."""
    info = model_info(workspace_root, kind, driver_model, model_number)
    if not info:
        raise ValueError(f'직렬 서보 종류가 아닙니다 · {kind}')
    if kind == 'dynamixel' and info.get('supported') is False and not info.get('model_warning'):
        raise ValueError(
            f'{info.get("model_name") or driver_model} · {info.get("reason") or "지원 안 함"}'
        )
    model_file = str(info.get('model_file') or '')
    if not model_file or not Path(model_file).is_file():
        # 제어표 없이 쓴 param 은 motor_manager 시작을 멈춘다(그 PC 의 AC 축까지) · 저장에서 막는다
        raise ValueError(
            f'{kind} {info.get("model_name") or driver_model or ""} · 제어표 파일 없음 · '
            f'{model_file or "경로 없음"}'
        )
    document = copy.deepcopy(_template(workspace_root, str(info.get('template') or 'dynamixel_x')))
    document['model_file'] = model_file
    if kind == 'dynamixel' and not info.get('has_current', True):
        for entry in document.get('interfaces') or []:
            if isinstance(entry, dict) and entry.get('name') in _CURRENT_INTERFACES:
                entry['optional'] = True
    return document, info


def write_param_file(
    workspace_root: Path,
    driver_id: Any,
    kind: str,
    driver_model: Any = '',
    model_number: Any = None,
) -> str:
    """이 드라이버만의 param yaml 을 만들고 **절대경로**를 돌려준다."""
    document, info = build_document(workspace_root, kind, driver_model, model_number)
    out_dir = output_root(workspace_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'driver_{driver_id}.yaml'
    lines = [
        '# 이 파일은 저장할 때마다 다시 만들어진다 · 손으로 고치지 말 것',
        f'# (모터 관리 저장 → config/serial_params/) · 수정 목록 158 · {kind} '
        f'{info.get("model_name") or ""} (모델 번호 {info.get("model_number")})',
    ]
    if info.get('model_warning'):
        lines.append(f'# {info["model_warning"]}')
    elif info.get('confirm') and info.get('reason'):
        lines.append(f'# {info["reason"]}')
    out_path.write_text(
        '\n'.join(lines) + '\n' + yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding='utf-8',
    )
    return str(out_path)


def port_kind_conflicts(masters: List[Dict[str, Any]], drivers: List[Dict[str, Any]]) -> List[str]:
    """한 포트 = 한 종류 · 어기는 포트마다 사유 한 줄 · 설계 §0 (U2D2 한 버스에 섞지 않음)."""
    kinds_by_driver = {
        optional_int(driver.get('id'), None): str(driver.get('type') or '')
        for driver in drivers or []
        if isinstance(driver, dict)
    }
    kinds_by_port: Dict[str, set] = {}
    for master in masters or []:
        if not isinstance(master, dict) or master.get('type') != 'serial':
            continue
        port = str(master.get('serial_port') or master.get('port') or '').strip()
        for slave in master.get('slaves') or []:
            if not isinstance(slave, dict):
                continue
            kind = kinds_by_driver.get(optional_int(slave.get('driver_id'), None), '')
            if kind:
                kinds_by_port.setdefault(port, set()).add(kind)
    return [
        f'직렬 포트 {port} 에 {" · ".join(sorted(kinds))} 가 같이 있습니다 · 한 포트에는 한 종류만 (어댑터를 나누세요)'
        for port, kinds in sorted(kinds_by_port.items())
        if len(kinds) > 1
    ]


def registry_port_kind_conflicts(motors: List[Dict[str, Any]]) -> List[str]:
    """저장 전 레지스트리 판정 · 포트마다 종류(`driver_family` / `motor_type`)."""
    kinds_by_port: Dict[str, set] = {}
    for motor in motors or []:
        if not isinstance(motor, dict) or motor.get('deleted') or not motor.get('enabled', False):
            continue
        if motor.get('transport') != 'serial':
            continue
        config = motor.get('config') if isinstance(motor.get('config'), dict) else {}
        identity = motor.get('identity') if isinstance(motor.get('identity'), dict) else {}
        port = str(config.get('serial_port') or identity.get('serial_port') or '').strip()
        kind = str(motor.get('driver_family') or motor.get('motor_type') or '').strip().lower()
        if port and kind:
            kinds_by_port.setdefault(port, set()).add(kind)
    return [
        f'직렬 포트 {port} 에 {" · ".join(sorted(kinds))} 가 같이 있습니다 · 한 포트에는 한 종류만 (어댑터를 나누세요)'
        for port, kinds in sorted(kinds_by_port.items())
        if len(kinds) > 1
    ]


#: 속도 칸이 비었을 때 · `motor_config_build.DYNAMIXEL_BAUDRATE` 와 같은 값 · 같은 종류에만
DEFAULT_SERIAL_BAUDRATE = 1000000
_DEFAULT_BAUDRATE_KINDS = ('dynamixel', 'feetech')

#: 한 포트에 속도가 둘 이상일 때 · 무엇을 해야 하는지까지 · 수정 목록 161
_BAUDRATE_FIX = (
    '한 포트에는 한 속도만 (한 선을 두 속도로 두 번 열면 어느 쪽도 제대로 답하지 않습니다) · '
    '그 포트의 서보를 모두 같은 속도로 바꾼 뒤(다이나믹셀은 Dynamixel Wizard 의 Baud Rate) 다시 검색하세요'
)


def _baud_text(baudrate: int) -> str:
    return f'{baudrate:,} bps'


def _baudrate_conflict_lines(axes_by_port: Dict[str, Dict[int, List[str]]]) -> List[str]:
    lines = []
    for port, by_baud in sorted(axes_by_port.items()):
        if len(by_baud) < 2:
            continue
        parts = ' / '.join(
            f'{_baud_text(baud)} · {"·".join(axes)}번 모터' if axes else _baud_text(baud)
            for baud, axes in sorted(by_baud.items(), key=lambda item: (-len(item[1]), item[0]))
        )
        lines.append(f'직렬 포트 {port} 에 통신 속도가 다른 모터가 있습니다 ({parts}) · {_BAUDRATE_FIX}')
    return lines


def registry_motor_baudrate(motor: Dict[str, Any]) -> Optional[int]:
    """레지스트리 직렬 모터의 속도 · `serial_masters_from_registry` 와 같은 순서 (config → identity → 1 Mbps)."""
    config = motor.get('config') if isinstance(motor.get('config'), dict) else {}
    identity = motor.get('identity') if isinstance(motor.get('identity'), dict) else {}
    baudrate = optional_int(config.get('serial_baudrate'), optional_int(identity.get('serial_baudrate'), None))
    if baudrate is None and str(motor.get('driver_family') or motor.get('motor_type') or '') in _DEFAULT_BAUDRATE_KINDS:
        baudrate = DEFAULT_SERIAL_BAUDRATE
    return baudrate


def registry_port_baudrate_conflicts(motors: List[Dict[str, Any]]) -> List[str]:
    """한 포트 = 한 속도 · 저장 전 레지스트리 판정 · 수정 목록 161 (chicken2 실물 2026-10-29)

    직렬 마스터는 (포트, 속도) 마다 하나다 · 같은 포트에 1 Mbps 둘 · 57600 하나를 저장하면
    마스터가 둘이 되어 **한 선을 두 번** 연다 · 57600 서보는 끝내 답하지 않았고 1 Mbps 서보는
    온라인 · 오프라인을 오갔다 · 쓰는 모터(사용 · 안 지움)만 본다
    """
    axes_by_port: Dict[str, Dict[int, List[str]]] = {}
    for motor in motors or []:
        if not isinstance(motor, dict) or motor.get('deleted') or not motor.get('enabled', False):
            continue
        if motor.get('transport') != 'serial':
            continue
        config = motor.get('config') if isinstance(motor.get('config'), dict) else {}
        identity = motor.get('identity') if isinstance(motor.get('identity'), dict) else {}
        port = str(config.get('serial_port') or identity.get('serial_port') or '').strip()
        baudrate = registry_motor_baudrate(motor)
        if not port or baudrate is None:
            continue
        axis = optional_int(config.get('controller_index'), optional_int(motor.get('axis'), None))
        axes = axes_by_port.setdefault(port, {}).setdefault(baudrate, [])
        if axis is not None:
            axes.append(str(axis))
    return _baudrate_conflict_lines(axes_by_port)


def port_baudrate_conflicts(masters: List[Dict[str, Any]]) -> List[str]:
    """한 포트 = 한 속도 · 만든 설정(직렬 마스터) 판정 · 설정 파일을 손으로 고친 저장 길도 · 수정 목록 161"""
    axes_by_port: Dict[str, Dict[int, List[str]]] = {}
    for master in masters or []:
        if not isinstance(master, dict) or master.get('type') != 'serial':
            continue
        port = str(master.get('serial_port') or master.get('port') or '').strip()
        baudrate = optional_int(master.get('serial_baudrate'), None)
        if not port or baudrate is None:
            continue
        axes = axes_by_port.setdefault(port, {}).setdefault(baudrate, [])
        for slave in master.get('slaves') or []:
            axis = optional_int(slave.get('controller_index'), None) if isinstance(slave, dict) else None
            if axis is not None:
                axes.append(str(axis))
    return _baudrate_conflict_lines(axes_by_port)


def identity_model_number(motor: Optional[Dict[str, Any]]) -> Optional[int]:
    """registry 모터의 검색 모델 번호 · 없으면 None."""
    if not isinstance(motor, dict):
        return None
    identity = motor.get('identity') if isinstance(motor.get('identity'), dict) else {}
    return optional_int(identity.get('model_number'), None)
