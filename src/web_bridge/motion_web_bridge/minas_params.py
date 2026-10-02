"""MINAS 드라이브 파라미터(yaml) 생성 · 브레이크 타이밍 · 앱솔루트 모드 · P8

MINAS 의 드라이브 객체 값(SDO)은 드라이버의 `param_file` 이 가리키는
`minas.yaml` 의 `items` 목록으로 부팅 때 써진다 · 그 파일은 motion_system
(수정 금지) 안에 있어서, 모터별로 값을 바꾸려면 **스택이 제 파일을 만들어
드라이버가 그쪽을 보게** 한다 · 로더는 param_file 이 .yaml 이면 그대로,
디렉터리면 `<dir>/minas.yaml` 을 읽고, 상대경로는 설정 파일 기준으로 푼다
(`motor_manager resolveDriverParamPath` · 포크 기준 코드 확인 · 핀 버전
동작은 미니PC 검증 항목).

객체 번호 규칙 · Pr X.YY → 0x3XYY (플랫폼 파일의 0x3511 = Pr5.11 로 확인):

    encoder_absolute_mode   Pr0.15 → 0x3015  절대 엔코더 설정
                            0 = 인크리멘털로 사용 · 1 = 절대 사용 ·
                            2 = 절대 사용(다회전 카운터 넘침 무시)
                            ⚠ 반영은 드라이브 전원 재투입 후 (MINAS 사양)
    brake_delay_stop_ms     Pr4.37 → 0x3437  정지 중 서보OFF → 브레이크 동작 지연
    brake_delay_run_ms      Pr4.38 → 0x3438  회전 중 서보OFF → 브레이크 동작 설정

기반 목록은 motion_system 의 `param/minas.yaml` 을 그대로 읽어 쓰고(있으면),
없으면 같은 내용의 내장 사본을 쓴다 · 모터별 오버라이드는 registry
`motor.config` 의 위 키에서 온다 (운전 한계와 같은 자리 · P3b).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from motion_common.values import optional_int

#: registry motor.config 키 → (MINAS 객체, 타입, 설명)
PARAM_FIELDS: Dict[str, Tuple[int, str, str]] = {
    'encoder_absolute_mode': (0x3015, 's16', 'Pr0.15 절대 엔코더 설정 (0 인크리멘털 · 1 절대 · 2 절대-다회전무시) · 전원 재투입 후 반영'),
    'brake_delay_stop_ms': (0x3437, 's16', 'Pr4.37 정지 중 서보OFF 시 브레이크 동작 지연 (ms)'),
    'brake_delay_run_ms': (0x3438, 's16', 'Pr4.38 회전 중 서보OFF 시 브레이크 동작 설정 (ms)'),
}

#: motion_system 기준 param 파일 위치 (서브모듈이 받아져 있을 때)
PLATFORM_PARAM = Path('src/motion_system/ros2/motion_system_ros2/motion_control_bridge/param/minas.yaml')

#: 생성 위치 · 설정 파일(config/active_motor_config.yaml) 기준 상대경로로 적는다
OUTPUT_DIR = 'minas_params'

#: 플랫폼 `param/minas.yaml` 의 items 사본 · 서브모듈이 없을 때의 기반
#: (motion_system_ros2 2026-10-02 확인본 · 플랫폼이 바뀌면 여기도 맞출 것)
EMBEDDED_BASE_ITEMS: List[Dict[str, Any]] = [
    {'id': 30, 'index': 0x6060, 'subindex': 0x00, 'value': 1, 'type': 's8'},
    {'id': 31, 'index': 0x3511, 'subindex': 0x00, 'value': 100, 'type': 's16'},
    {'id': 32, 'index': 0x3512, 'subindex': 0x00, 'value': 50, 'type': 's16'},
    {'id': 33, 'index': 0x3513, 'subindex': 0x00, 'value': 0, 'type': 's16'},
    {'id': 34, 'index': 0x3514, 'subindex': 0x00, 'value': 1, 'type': 's16'},
    {'id': 35, 'index': 0x607F, 'subindex': 0x00, 'value': 279620000, 'type': 'u32'},
    {'id': 36, 'index': 0x6082, 'subindex': 0x00, 'value': 500, 'type': 'u32'},
    {'id': 37, 'index': 0x60B1, 'subindex': 0x00, 'value': 0, 'type': 's32'},
    {'id': 38, 'index': 0x60B2, 'subindex': 0x00, 'value': 0, 'type': 's16'},
    {'id': 50, 'index': 0x6072, 'subindex': 0x00, 'value': 0, 'type': 'u16'},
    {'id': 51, 'index': 0x607B, 'subindex': 0x01, 'value': 0, 'type': 's32'},
    {'id': 52, 'index': 0x607B, 'subindex': 0x02, 'value': 0, 'type': 's32'},
    {'id': 51, 'index': 0x607D, 'subindex': 0x01, 'value': 0, 'type': 's32'},
    {'id': 52, 'index': 0x607D, 'subindex': 0x02, 'value': 0, 'type': 's32'},
    {'id': 53, 'index': 0x6080, 'subindex': 0x00, 'value': 0, 'type': 'u32'},
    {'id': 54, 'index': 0x6081, 'subindex': 0x00, 'value': 0, 'type': 'u32'},
    {'id': 55, 'index': 0x6083, 'subindex': 0x00, 'value': 0, 'type': 'u32'},
    {'id': 56, 'index': 0x6084, 'subindex': 0x00, 'value': 0, 'type': 'u32'},
    {'id': 57, 'index': 0x60C5, 'subindex': 0x00, 'value': 0, 'type': 'u32'},
    {'id': 58, 'index': 0x60C6, 'subindex': 0x00, 'value': 0, 'type': 'u32'},
]

#: 인터페이스(PDO) 구획은 값이 아니라 배선이다 · 플랫폼 그대로 복사한다
EMBEDDED_INTERFACES: List[Dict[str, Any]] = [
    {'id': 98, 'index': 0x1600},
    {'id': 0, 'index': 0x6040, 'subindex': 0x00, 'size': 2, 'type': 'u16'},
    {'id': 1, 'index': 0x607A, 'subindex': 0x00, 'size': 4, 'type': 's32'},
    {'id': 2, 'index': 0x60FF, 'subindex': 0x00, 'size': 4, 'type': 's32'},
    {'id': 3, 'index': 0x6071, 'subindex': 0x00, 'size': 2, 'type': 's16'},
    {'id': 99, 'index': 0x1A00},
    {'id': 4, 'index': 0x6041, 'subindex': 0x00, 'size': 2, 'type': 'u16'},
    {'id': 5, 'index': 0x603F, 'subindex': 0x00, 'size': 2, 'type': 'u16'},
    {'id': 6, 'index': 0x6064, 'subindex': 0x00, 'size': 4, 'type': 's32'},
    {'id': 7, 'index': 0x606C, 'subindex': 0x00, 'size': 4, 'type': 's32'},
    {'id': 8, 'index': 0x6077, 'subindex': 0x00, 'size': 2, 'type': 's16'},
]


def param_overrides(motor: Dict[str, Any]) -> Dict[str, int]:
    """registry 모터에서 드라이브 파라미터 오버라이드만 걷는다 · 정수."""
    config = motor.get('config') if isinstance(motor.get('config'), dict) else {}
    overrides: Dict[str, int] = {}
    for key in PARAM_FIELDS:
        value = optional_int(config.get(key))
        if value is not None:
            overrides[key] = value
    return overrides


def _base_document(workspace_root: Path) -> Dict[str, Any]:
    platform = Path(workspace_root) / PLATFORM_PARAM
    try:
        payload = yaml.safe_load(platform.read_text(encoding='utf-8'))
        if isinstance(payload, dict) and isinstance(payload.get('items'), list):
            return payload
    except (OSError, yaml.YAMLError):
        pass
    return {
        'items': [dict(item) for item in EMBEDDED_BASE_ITEMS],
        'interfaces': [dict(item) for item in EMBEDDED_INTERFACES],
    }


def write_param_file(
    workspace_root: Path,
    driver_id: Any,
    overrides: Dict[str, int],
) -> str:
    """이 드라이버만의 minas.yaml 을 만들고 **절대경로**를 돌려준다.

    배포에서 motor_manager 가 읽는 설정은 프로젝트 runtime 폴더로 복사되므로
    상대경로는 어긋난다 · 다이나믹셀 param 과 같은 방식으로 절대경로를 적는다.
    같은 객체가 기반 목록에 이미 있으면 값을 바꾸고, 없으면 뒤에 더한다.
    """
    document = _base_document(Path(workspace_root))
    items = [dict(item) for item in document.get('items', [])]
    next_id = max((int(item.get('id') or 0) for item in items), default=0) + 1
    for key, value in sorted(overrides.items()):
        index, type_name, note = PARAM_FIELDS[key]
        for item in items:
            if int(item.get('index') or 0) == index and int(item.get('subindex') or 0) == 0:
                item['value'] = int(value)
                break
        else:
            items.append({
                'id': next_id, 'index': index, 'subindex': 0x00,
                'value': int(value), 'type': type_name,
            })
            next_id += 1
    document = dict(document)
    document['items'] = items

    out_dir = Path(workspace_root) / 'config' / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'driver_{driver_id}.yaml'
    header = (
        '# 이 파일은 저장할 때마다 다시 만들어진다 · 손으로 고치지 말 것\n'
        '# (모터 관리 화면의 드라이브 설정 → config/minas_params/) · P8\n'
        + ''.join(
            f'# {key}={overrides[key]} · {PARAM_FIELDS[key][2]}\n'
            for key in sorted(overrides)
        )
    )
    out_path.write_text(
        header + yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding='utf-8',
    )
    return str(out_path)
