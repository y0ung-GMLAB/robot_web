"""MINAS 드라이브 파라미터(yaml) 생성 · 브레이크 타이밍 · 과부하율 읽기 · P8

MINAS 의 드라이브 객체 값(SDO)은 드라이버의 `param_file` 이 가리키는
`minas.yaml` 의 `items` 목록으로 부팅 때 써진다 · 그 파일은 motion_system
(수정 금지) 안에 있어서, 모터별로 값을 바꾸려면 **스택이 제 파일을 만들어
드라이버가 그쪽을 보게** 한다 · 로더는 param_file 이 .yaml 이면 그대로,
디렉터리면 `<dir>/minas.yaml` 을 읽고, 상대경로는 설정 파일 기준으로 푼다
(`motor_manager resolveDriverParamPath` · 포크 기준 코드 확인 · 핀 버전
동작은 미니PC 검증 항목).

객체 번호 규칙 · Pr X.YY → 0x3XYY (플랫폼 파일의 0x3511 = Pr5.11 로 확인):

    brake_delay_stop_ms     Pr4.37 → 0x3437  정지 중 서보OFF → 브레이크 동작 지연 (속성 B)
    brake_delay_run_ms      Pr4.38 → 0x3438  회전 중 서보OFF → 브레이크 동작 설정 (속성 B)

부팅 때 **쓰지 않는** 것 · 2026-10-06 · 수정 목록 34 · 매뉴얼 SX-DSV03241 R10.0 기준:

    Pr0.15 앱솔루트 (0x3015)  값 뜻 · 0 = 절대 · 1 = 인크리멘털 · 2 = 절대·넘침
                              무시 · 3 = 한 바퀴 절대 · 4 = 연속 회전 (p.176)
                              속성 C · 제어 전원 재투입 때 EEPROM 을 다시 읽으므로
                              부팅 RAM 쓰기로는 **반영되지 않는다** (p.241) ·
                              예전 화면은 0/1 뜻이 반대였다 · 남은 RAM 값이 나중
                              EEPROM 저장에 박히지 않게 아예 안 쓴다 · 바꾸기는
                              EEPROM 저장(1010h · 수정 목록 15) 과 같이
    Pr5.04 리밋 스위치 (0x3504) 1 = 「사용 안 함」이 아니라 CiA402 감속 정지
                              (리밋 살아 있음 · p.155) · 화면에서 뺐다 · 명령어로
                              (`docs/사용법.md` 12장)
    registry 에 옛 값(`encoder_absolute_mode` · `limit_switch_mode`)이 남아 있어도
    무시한다 (지우지 않는다)

과부하율 읽기는 SDO 값이 아니라 **PDO 배선**이다 (2026-10-02):

    overload_monitor        1 = TxPDO 에 4D29h(과부하율 · 0.1% U16)를 더한다
                            빈 칸·0 = 더하지 않음 (기본 · 플랫폼 그대로)
                            ⚠ 드라이브 소프트웨어 Ver1.03 이상만 지원 · 미만이면
                              EtherCAT 설정이 실패해 motor_manager 가 안 뜬다

정지 방식(Pr5.05)·입력 핀 할당(Pr4.00~)은 값의 의미를 매뉴얼로 확인하기
전까지 넣지 않는다 · 드라이브에 있는 값을 그대로 쓴다.

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
    'brake_delay_stop_ms': (0x3437, 's16', 'Pr4.37 정지 중 서보OFF 시 브레이크 동작 지연 (ms)'),
    'brake_delay_run_ms': (0x3438, 's16', 'Pr4.38 회전 중 서보OFF 시 브레이크 동작 설정 (ms)'),
}

#: 부팅 때 쓰지 않는 옛 키 · 남아 있어도 드라이브로 보내지 않는다 (위 설명)
RETIRED_FIELDS: Tuple[str, ...] = ('encoder_absolute_mode', 'limit_switch_mode')

#: 정해진 값만 받는 항목 · 범위 밖은 드라이브에 보내지 않는다
ALLOWED_VALUES: Dict[str, Tuple[int, ...]] = {
    'overload_monitor': (0, 1),
}

#: PDO 에 더하는 감시 값 · registry 키 → (인터페이스 항목, 설명) · 1 일 때만 더한다
#: id 12 = motor_manager `ID_OVERLOAD_RATIO` (src/motion_system · 2026-10-02)
MONITOR_FIELDS: Dict[str, Tuple[Dict[str, Any], str]] = {
    'overload_monitor': (
        {'id': 12, 'index': 0x4D29, 'subindex': 0x00, 'size': 2, 'type': 'u16'},
        '4D29h 과부하율 읽기 (0 끔 · 1 켬) · 드라이브 Ver1.03 이상만',
    ),
}

#: 범위로 받는 항목 · 브레이크 시간(ms) · s16 이지만 음수·과대값은 실수다
RANGE_VALUES: Dict[str, Tuple[int, int]] = {
    'brake_delay_stop_ms': (0, 10000),
    'brake_delay_run_ms': (0, 10000),
}

#: motion_system 기준 param 파일 위치 (서브모듈이 받아져 있을 때)
PLATFORM_PARAM = Path('src/motion_system/ros2/motion_system_ros2/motion_control_bridge/param/minas.yaml')

#: 생성 위치 · 프로젝트 모터 설정 파일 기준 상대경로로 적는다
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
    """registry 모터에서 드라이브 파라미터 오버라이드만 걷는다 · 정수.

    허용 값·범위를 벗어난 것은 **버린다** (드라이브 값 유지) · 화면이 먼저
    거절하지만, 파일을 손으로 고친 경우에도 이상한 값이 드라이브로 가면 안 된다.
    """
    config = motor.get('config') if isinstance(motor.get('config'), dict) else {}
    overrides: Dict[str, int] = {}
    for key in (*PARAM_FIELDS, *MONITOR_FIELDS):
        value = optional_int(config.get(key))
        if value is None:
            continue
        if key in ALLOWED_VALUES and value not in ALLOWED_VALUES[key]:
            continue
        if key in RANGE_VALUES:
            low, high = RANGE_VALUES[key]
            if not low <= value <= high:
                continue
        if key in MONITOR_FIELDS and value != 1:
            continue   # 끔 = 플랫폼 그대로 · 제 파일을 만들 이유가 아니다
        overrides[key] = value
    return overrides


def _describe(key: str) -> str:
    if key in PARAM_FIELDS:
        return PARAM_FIELDS[key][2]
    return MONITOR_FIELDS[key][1]


def _with_monitors(interfaces: List[Dict[str, Any]], overrides: Dict[str, int]) -> List[Dict[str, Any]]:
    """켠 감시 값을 TxPDO 구획 끝에 더한다 · 이미 있으면 그대로."""
    result = [dict(item) for item in interfaces]
    for key, (entry, _) in MONITOR_FIELDS.items():
        if overrides.get(key) != 1:
            continue
        if any(int(item.get('index') or 0) == entry['index'] for item in result):
            continue
        headers = [int(item.get('id') or 0) for item in result if 'subindex' not in item]
        if not headers or headers[-1] != 99:
            raise ValueError('minas param 의 마지막 PDO 구획이 TxPDO(0x1A00)가 아닙니다')
        result.append(dict(entry))
    return result


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
        if key not in PARAM_FIELDS:
            continue   # 감시 값 · SDO 가 아니라 PDO (아래 _with_monitors)
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
    document['interfaces'] = _with_monitors(document.get('interfaces', []), overrides)

    out_dir = Path(workspace_root) / 'config' / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'driver_{driver_id}.yaml'
    header = (
        '# 이 파일은 저장할 때마다 다시 만들어진다 · 손으로 고치지 말 것\n'
        '# (모터 관리 화면의 드라이브 설정 → config/minas_params/) · P8\n'
        + ''.join(
            f'# {key}={overrides[key]} · {_describe(key)}\n'
            for key in sorted(overrides)
        )
    )
    out_path.write_text(
        header + yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding='utf-8',
    )
    return str(out_path)
