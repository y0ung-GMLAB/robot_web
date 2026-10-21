"""직렬 버스 서보 모델 목록 · Dynamixel · Feetech · 수정 목록 158 (`docs/SERIAL_SERVO_DESIGN.md` §3-2 · §5)

- Dynamixel · 모델 번호 → 제어표 파일 · `motion_system` 의 `control_table/dynamixel.model` 을 실행 때 읽는다 (읽기만)
- 시리즈 표 · 운전 모드 · 가속 단위 · 전류 단위 · 위치 범위 · 지원 여부
- Feetech · STS 계열 · 모델 번호 777 STS3215 · 2825 STS3250 · 그 밖의 STS 번호 → `STS (모델 <n>)` + 확인 필요
- 이름 · 다이나믹셀은 제어표 파일 이름에서 (`xm430_w350.model` → `XM430-W350`) ·
  XM540-W270 은 `XM540-W270-R` (전부터 쓰던 이름 · `motor_identity.canonical_dynamixel_model` 과 같음)

실물 미검증 · P · MX · XL330 · Feetech 값은 e-manual · 공개 SDK 기준 (설계 §9 D-1 · F-1~F-5)
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

__all__ = [
    'DYNAMIXEL_CONTROL_TABLE_DIR',
    'FEETECH_CONTROL_TABLE_DIR',
    'FEETECH_STS_MODEL_FILE',
    'FEETECH_MODEL_NAMES',
    'DYNAMIXEL_SERIES',
    'FEETECH_SERIES',
    'dynamixel_model_table',
    'dynamixel_model_name',
    'dynamixel_scan_name',
    'dynamixel_model',
    'feetech_model_name',
    'feetech_model',
    'serial_model',
    'model_file_type_info',
]

#: 저장소 기준 경로 · 실행 때 `workspace_root` 뒤에 붙인다
DYNAMIXEL_CONTROL_TABLE_DIR = Path('src/motion_system/lib/motor_manager/hardware/dynamixel/control_table')
FEETECH_CONTROL_TABLE_DIR = Path('src/motion_system/lib/motor_manager/hardware/feetech/control_table')
#: STS 제어표 · motor_manager 쪽 작업이 만든다 (경로만 가리킨다)
FEETECH_STS_MODEL_FILE = FEETECH_CONTROL_TABLE_DIR / 'sts.model'

#: Feetech STS 모델 번호 (주소 3 · 2 바이트 · little) → 이름 · 실물 미검증 (F-1)
FEETECH_MODEL_NAMES: Dict[int, str] = {
    777: 'STS3215',
    2825: 'STS3250',
}

#: 다이나믹셀 시리즈 값 · 설계 §3-2
#:   template           · `config/serial_servo/<template>.yaml`
#:   acceleration_unit  · Profile Acceleration raw 1 = deg/s² (X 214.577 rev/min² · P 1 rev/min²)
#:   position_raw_limit · Extended Position 목표 위치 허용 raw (±)
#:   unit_effort        · 전류 raw 1 = A · None = 전류 없음(부하 %) → 전류 칸 optional
DYNAMIXEL_SERIES: Dict[str, Dict[str, Any]] = {
    'x': {
        'label': 'Dynamixel X',
        'template': 'dynamixel_x',
        'operating_mode': 4,
        'acceleration_unit': 21.4577,
        'position_raw_limit': 1048575,
        'unit_effort': 0.00269,
    },
    'x330': {
        'label': 'Dynamixel XL330 · XC330',
        'template': 'dynamixel_x',
        'operating_mode': 4,
        'acceleration_unit': 21.4577,
        'position_raw_limit': 1048575,
        'unit_effort': 0.001,
    },
    'mx': {
        'label': 'Dynamixel MX (2.0)',
        'template': 'dynamixel_x',
        'operating_mode': 4,
        'acceleration_unit': 21.4577,
        'position_raw_limit': 1048575,
        'unit_effort': 0.00336,
    },
    'p': {
        'label': 'Dynamixel P (PH · PM)',
        'template': 'dynamixel_p',
        'operating_mode': 4,
        'acceleration_unit': 0.1,
        'position_raw_limit': 2147483647,
        'unit_effort': 0.001,
    },
}

#: 전류가 없는(부하 %) 모델 · 제어표 파일 이름 앞부분
_NO_CURRENT_PREFIXES: Tuple[str, ...] = ('xl430', 'xc430', '2xl430', '2xc430', 'mx_28')

#: 지원 안 함 · 제어표 파일 이름 앞부분 → 사유
_UNSUPPORTED_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ('xl320', 'XL320 · 제어표·단위가 X 시리즈와 다름 · 지원 안 함'),
    ('ym', 'Y 시리즈 · 지원 안 함'),
    ('rh_p12_rn', 'RH-P12-RN 그리퍼 · 지원 안 함'),
    ('h42_', '옛 PRO H 시리즈 · 지원 안 함'),
    ('h54_', '옛 PRO H 시리즈 · 지원 안 함'),
    ('m42_', '옛 PRO M 시리즈 · 지원 안 함'),
    ('m54_', '옛 PRO M 시리즈 · 지원 안 함'),
)

#: Protocol 1.0 모델 번호 (Protocol 2.0 Ping 에는 답하지 않는다 · 이름만 알려 준다)
_PROTOCOL1_MODELS: Dict[int, str] = {
    12: 'AX-12A', 18: 'AX-18A', 300: 'AX-12W',
    10: 'RX-10', 24: 'RX-24F', 28: 'RX-28', 64: 'RX-64', 107: 'EX-106+',
    29: 'MX-28 (Protocol 1.0)', 310: 'MX-64 (Protocol 1.0)', 320: 'MX-106 (Protocol 1.0)',
    360: 'MX-12W',
}

#: Feetech 시리즈 값 · 설계 §3-2 · 실물 미검증 (F-2 · F-3)
FEETECH_SERIES: Dict[str, Any] = {
    'label': 'Feetech STS',
    'template': 'feetech_sts',
    'operating_mode': 0,
    'acceleration_unit': 8.7890625,     # 100 step/s² × 360/4096
    'position_raw_min': 0,
    'position_raw_max': 4095,
    'unit_effort': 0.0065,              # 6.5 mA / raw
    'pulse_per_revolution': 4096,
}

#: 같은 이름 · 다이나믹셀 (검색 이름 → 이 프로그램 이름) · `motor_identity.DYNAMIXEL_MODEL_NAMES` 와 같음
_DYNAMIXEL_CANONICAL = (
    ('XM540-W150', 'XM540-W150'),
    ('XM540-W270', 'XM540-W270-R'),
)

_TABLE_CACHE: Dict[str, Tuple[float, Dict[int, str]]] = {}


def _root(workspace_root: Any) -> Path:
    if workspace_root:
        return Path(workspace_root)
    # 환경변수 → 설치 트리 → 소스 트리 · `paths.workspace_root` 한 곳
    from motion_common import paths

    return paths.workspace_root()


def _tables_root(workspace_root: Any) -> Path:
    """제어표가 있는 저장소 루트 · 받은 작업 폴더에 `src/motion_system` 이 없으면(시험 · 따로 둔
    작업 폴더) 설치된 저장소 · 제어표는 코드와 같이 오므로 프로젝트 데이터가 아니다 ·
    기본 param 파일(`serial_params._template`)과 같은 규칙 · 수정 목록 158"""
    root = _root(workspace_root)
    if (root / DYNAMIXEL_CONTROL_TABLE_DIR).is_dir():
        return root
    from motion_common import paths

    return paths.workspace_root()


def dynamixel_model_table(workspace_root: Any = None) -> Dict[int, str]:
    """`dynamixel.model` · 모델 번호 → 제어표 파일 이름 · 못 읽으면 빈 dict."""
    path = _tables_root(workspace_root) / DYNAMIXEL_CONTROL_TABLE_DIR / 'dynamixel.model'
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _TABLE_CACHE.get(str(path))
    if cached is not None and cached[0] == mtime:
        return dict(cached[1])
    table: Dict[int, str] = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return {}
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            number = int(parts[0])
        except ValueError:
            continue   # 머리줄 `Number Name`
        table[number] = parts[1]
    _TABLE_CACHE[str(path)] = (mtime, table)
    return dict(table)


def _canonical_dynamixel(name: str) -> str:
    needle = name.upper().replace('_', '-')
    for scanned, canonical in _DYNAMIXEL_CANONICAL:
        if scanned in needle:
            return canonical
    return name


def _name_from_file(file_name: str) -> str:
    stem = file_name[:-len('.model')] if file_name.endswith('.model') else file_name
    return _canonical_dynamixel(stem.upper().replace('_', '-'))


def _stem_from_name(name: str) -> str:
    return str(name or '').strip().lower().replace('-', '_')


def dynamixel_model_name(model_number: Any, workspace_root: Any = None) -> str:
    """모델 번호 → 이 프로그램이 쓰는 이름 (`XM540-W270-R`) · 모르면 빈 글자."""
    name = dynamixel_scan_name(model_number, workspace_root)
    return _canonical_dynamixel(name) if name else ''


def dynamixel_scan_name(model_number: Any, workspace_root: Any = None) -> str:
    """검색 · 모델 번호 → 제어표 파일 이름 그대로의 이름 (`XM540-W270`) · 모르면 빈 글자.

    검색 결과에는 이 이름이 실린다 · 정식 이름은 레지스트리로 옮길 때 붙는다 (전과 같은 흐름)
    """
    try:
        number = int(model_number)
    except (TypeError, ValueError):
        return ''
    file_name = dynamixel_model_table(workspace_root).get(number)
    if file_name:
        stem = file_name[:-len('.model')] if file_name.endswith('.model') else file_name
        return stem.upper().replace('_', '-')
    return _PROTOCOL1_MODELS.get(number, '')


def _series_for_stem(stem: str) -> Tuple[str, str]:
    """(시리즈, 지원 안 하는 사유) · 시리즈를 모르면 ('', 사유)."""
    for prefix, reason in _UNSUPPORTED_PREFIXES:
        if stem.startswith(prefix):
            return '', reason
    if stem.startswith(('ph', 'pm')):
        return 'p', ''
    if stem.startswith('mx_'):
        return 'mx', ''
    if stem.startswith(('xl330', 'xc330')):
        return 'x330', ''
    if stem.startswith(('x', '2x')):
        return 'x', ''
    return '', '알 수 없는 다이나믹셀 시리즈 · 지원 안 함'


def model_file_type_info(path: Path) -> Dict[str, float]:
    """제어표 파일 `[type info]` · 위치 0 · 최대 · 최소 raw 와 rad · 못 읽으면 빈 dict."""
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError:
        return {}
    keys = {
        'value_of_zero_radian_position', 'value_of_max_radian_position',
        'value_of_min_radian_position', 'min_radian', 'max_radian',
    }
    info: Dict[str, float] = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] in keys:
            try:
                info[parts[0]] = float(parts[1])
            except ValueError:
                continue
    return info


def _pulse_per_revolution(info: Dict[str, float], default: int) -> int:
    """한 바퀴 raw · X(0~4095) 4096 · P(±303750 = ±π) 607500."""
    try:
        low = info['value_of_min_radian_position']
        high = info['value_of_max_radian_position']
        span_rad = info['max_radian'] - info['min_radian']
    except KeyError:
        return default
    if span_rad <= 0 or high <= low:
        return default
    raw = high - low + (1 if low >= 0 else 0)
    return int(round(raw * 2.0 * math.pi / span_rad))


def dynamixel_model(
    workspace_root: Any = None,
    *,
    model_number: Any = None,
    model_name: Any = '',
) -> Dict[str, Any]:
    """다이나믹셀 한 모델의 사실 · 번호가 있으면 번호로, 없으면 이름으로 제어표를 찾는다.

    돌려주는 칸 · kind · model_number · model_name · model_file(절대경로 · 없으면 '') · series ·
    supported · reason · template · operating_mode · acceleration_unit · position_raw_limit ·
    unit_effort(None = 전류 없음) · has_current · pulse_per_revolution · confirm
    """
    root = _tables_root(workspace_root)
    table = dynamixel_model_table(root)
    number: Optional[int]
    try:
        number = int(model_number) if model_number not in (None, '') else None
    except (TypeError, ValueError):
        number = None
    file_name = table.get(number, '') if number is not None else ''
    if not file_name and model_name:
        stem = _stem_from_name(str(model_name))
        candidates = [stem]
        if stem.endswith('_r'):
            candidates.append(stem[:-2])     # XM540-W270-R → xm540_w270
        for candidate in candidates:
            if (root / DYNAMIXEL_CONTROL_TABLE_DIR / f'{candidate}.model').is_file():
                file_name = f'{candidate}.model'
                break
        if not file_name:
            for table_number, table_file in table.items():
                if table_file[:-len('.model')] in candidates:
                    file_name = table_file
                    number = table_number
                    break
    if file_name and number is None:
        number = next((key for key, value in table.items() if value == file_name), None)
    result: Dict[str, Any] = {
        'kind': 'dynamixel',
        'model_number': number,
        'model_name': _name_from_file(file_name) if file_name else str(model_name or '').strip(),
        'model_file': '',
        'series': '',
        'supported': False,
        'reason': '',
        'template': '',
        'operating_mode': 4,
        'acceleration_unit': None,
        'position_raw_limit': None,
        'unit_effort': None,
        'has_current': False,
        'pulse_per_revolution': 4096,
        'confirm': False,
    }
    if not file_name:
        if number is not None and number in _PROTOCOL1_MODELS:
            result['model_name'] = _PROTOCOL1_MODELS[number]
            result['reason'] = 'Protocol 1.0 모델 · 지원 안 함'
        else:
            result['reason'] = '모르는 다이나믹셀 모델 · 제어표 없음'
        result['confirm'] = True
        return result
    stem = file_name[:-len('.model')]
    series, reason = _series_for_stem(stem)
    model_path = (root / DYNAMIXEL_CONTROL_TABLE_DIR / file_name).resolve()
    result['model_file'] = str(model_path)
    if not series:
        result['reason'] = reason
        return result
    values = DYNAMIXEL_SERIES[series]
    unit_effort = values['unit_effort']
    has_current = not stem.startswith(_NO_CURRENT_PREFIXES)
    result.update({
        'series': series,
        'supported': True,
        'template': values['template'],
        'operating_mode': values['operating_mode'],
        'acceleration_unit': values['acceleration_unit'],
        'position_raw_limit': values['position_raw_limit'],
        'unit_effort': unit_effort if has_current else None,
        'has_current': has_current,
        'pulse_per_revolution': _pulse_per_revolution(model_file_type_info(model_path), 4096),
    })
    return result


def feetech_model_name(model_number: Any) -> str:
    """검색 · 모델 번호 → 이름 · 모르는 번호는 `STS (모델 <n>)`."""
    try:
        number = int(model_number)
    except (TypeError, ValueError):
        return ''
    return FEETECH_MODEL_NAMES.get(number, f'STS (모델 {number})')


def feetech_model(
    workspace_root: Any = None,
    *,
    model_number: Any = None,
    model_name: Any = '',
) -> Dict[str, Any]:
    """Feetech 한 모델의 사실 · STS 제어표 하나 · 모르는 번호도 STS 로 동작 + 확인 필요."""
    number: Optional[int]
    try:
        number = int(model_number) if model_number not in (None, '') else None
    except (TypeError, ValueError):
        number = None
    name = str(model_name or '').strip()
    if number is None and name:
        number = next((key for key, value in FEETECH_MODEL_NAMES.items() if value == name.upper()), None)
    known = number in FEETECH_MODEL_NAMES if number is not None else name.upper() in FEETECH_MODEL_NAMES.values()
    if number is not None:
        name = feetech_model_name(number)
    elif not name:
        name = 'STS'
    return {
        'kind': 'feetech',
        'model_number': number,
        'model_name': name,
        'model_file': str((_tables_root(workspace_root) / FEETECH_STS_MODEL_FILE).resolve()),
        'series': 'sts',
        'supported': True,
        'reason': '' if known else 'STS 제어표로 동작 · 모델 확인 필요',
        'template': FEETECH_SERIES['template'],
        'operating_mode': FEETECH_SERIES['operating_mode'],
        'acceleration_unit': FEETECH_SERIES['acceleration_unit'],
        'position_raw_min': FEETECH_SERIES['position_raw_min'],
        'position_raw_max': FEETECH_SERIES['position_raw_max'],
        'unit_effort': FEETECH_SERIES['unit_effort'],
        'has_current': True,
        'pulse_per_revolution': FEETECH_SERIES['pulse_per_revolution'],
        'confirm': not known,
    }


def serial_model(
    workspace_root: Any,
    kind: str,
    *,
    model_number: Any = None,
    model_name: Any = '',
) -> Dict[str, Any]:
    """kind 로 고른다 · 직렬 서보가 아니면 빈 dict."""
    if kind == 'dynamixel':
        return dynamixel_model(workspace_root, model_number=model_number, model_name=model_name)
    if kind == 'feetech':
        return feetech_model(workspace_root, model_number=model_number, model_name=model_name)
    return {}
